import logging
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.worker_readiness import WorkerReadiness

IMAGE_ID = b'sha256:' + b'a' * 64


def test_local_mode_does_not_require_docker(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'local')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not call Docker'))
    assert WorkerReadiness().ready()


@pytest.mark.parametrize('failure', ['missing', 'timeout', 'daemon', 'invalid_id'])
def test_unavailable_worker_is_not_ready_and_probe_is_bounded(monkeypatch, failure):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    def run(command, **kwargs):
        assert command[:3] == ['docker', 'image', 'inspect']
        assert kwargs['timeout'] == 3 and kwargs['stderr'] == subprocess.DEVNULL
        assert kwargs['stdin'] == subprocess.DEVNULL
        if failure == 'missing':
            raise FileNotFoundError('secret executable path')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 3)
        return SimpleNamespace(returncode=1 if failure == 'daemon' else 0, stdout=b'invalid')
    monkeypatch.setattr(subprocess, 'run', run)
    assert not WorkerReadiness().ready()


def test_success_and_failure_cache_expire_and_recover(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    now, calls = [0], []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if now[0] == 5 else 0, stdout=IMAGE_ID)
    monkeypatch.setattr(subprocess, 'run', run)
    probe = WorkerReadiness(clock=lambda: now[0])
    assert probe.ready() and probe.ready() and len(calls) == 1
    now[0] = 5
    assert not probe.ready() and not probe.ready() and len(calls) == 2
    now[0] = 10
    assert probe.ready() and len(calls) == 3


@pytest.mark.parametrize('setting', ['SIGNOFF_RTL_WORKER_IMAGE', 'DOCKER_HOST', 'DOCKER_CONTEXT',
                                     'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'])
def test_configuration_change_invalidates_cached_success(monkeypatch, setting):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout=IMAGE_ID)
    monkeypatch.setattr(subprocess, 'run', run)
    probe = WorkerReadiness()
    assert probe.ready()
    monkeypatch.setenv(setting, 'different')
    assert not probe.ready() and len(calls) == 2


def test_concurrent_probe_does_not_wait_or_launch_another_process(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    entered, release = threading.Event(), threading.Event()
    calls, results = [], []
    def run(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(returncode=0, stdout=IMAGE_ID)
    monkeypatch.setattr(subprocess, 'run', run)
    probe = WorkerReadiness()
    thread = threading.Thread(target=lambda: results.append(probe.ready()))
    thread.start()
    try:
        assert entered.wait(1)
        assert not probe.ready()
        assert len(calls) == 1
    finally:
        release.set()
        thread.join(timeout=2)
    assert results == [True] and probe.ready()


def test_http_readiness_reports_worker_failure_without_leaking_details(client, monkeypatch, caplog):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    monkeypatch.setattr(client.app.state, 'worker_readiness', WorkerReadiness())
    def fail(*args, **kwargs):
        raise OSError('secret Docker connection credentials')
    monkeypatch.setattr(subprocess, 'run', fail)
    with caplog.at_level(logging.WARNING, logger='uvicorn.error.signoff'):
        response = client.get('/ready')
    assert response.status_code == 503 and response.json() == {'status': 'not_ready'}
    assert response.headers['retry-after'] == '5'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id'] in caplog.text
    assert 'secret Docker' not in caplog.text + response.text
    assert client.get('/health').json() == {'status': 'ok'}


def test_http_readiness_accepts_valid_container_image(client, monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    monkeypatch.setattr(client.app.state, 'worker_readiness', WorkerReadiness())
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=IMAGE_ID))
    assert client.get('/ready').json() == {'status': 'ready'}


def test_valid_cache_does_not_report_failure_due_to_lock_contention(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=IMAGE_ID))
    probe = WorkerReadiness()
    assert probe.ready()
    with probe.lock:
        assert probe.ready()
