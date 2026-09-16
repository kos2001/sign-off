import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import anyio
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services.rtl.admission import AdmittedIterator, AdmittedStreamingResponse, acquire_slot, capacity


@pytest.fixture(autouse=True)
def slots(tmp_path, monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_SLOT_DIR', str(tmp_path / 'slots'))
    monkeypatch.setenv('SIGNOFF_RTL_MAX_CONCURRENT', '1')


def test_capacity_is_shared_across_processes_and_recovers_after_exit():
    with acquire_slot():
        process = subprocess.run([sys.executable, '-c', "from app.services.rtl.admission import acquire_slot; from fastapi import HTTPException\ntry:\n acquire_slot()\nexcept HTTPException as e:\n print(e.status_code, e.headers['Retry-After'])"], capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        assert process.stdout.strip() == '429 5'
    process = subprocess.Popen([sys.executable, '-u', '-c', "from app.services.rtl.admission import acquire_slot; import time; slot=acquire_slot(); print('held', flush=True); time.sleep(20)"], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'held'
        with pytest.raises(HTTPException):
            acquire_slot()
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
    with acquire_slot():
        pass


def test_disconnected_stream_keeps_slot_until_active_stage_finishes():
    entered, finish, closed = threading.Event(), threading.Event(), []
    def source():
        try:
            entered.set()
            assert finish.wait(5)
            yield 'stage done'
            raise AssertionError('next stage must not execute after disconnect')
        finally:
            closed.append(True)
    iterator = AdmittedIterator(source(), acquire_slot())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(next, iterator)
        try:
            assert entered.wait(5)
            iterator.close()
            with pytest.raises(HTTPException):
                acquire_slot()
        finally:
            finish.set()
        assert future.result(timeout=5) == 'stage done'
    assert closed == [True]
    with pytest.raises(StopIteration):
        next(iterator)
    with acquire_slot():
        pass


@pytest.mark.parametrize('mode', ['unstarted', 'exhausted', 'failure'])
def test_iterator_releases_on_all_terminal_paths(mode):
    def source():
        if mode == 'failure':
            raise ValueError('tool failed')
        yield 'chunk'
    iterator = AdmittedIterator(source(), acquire_slot())
    if mode == 'unstarted':
        iterator.close()
    elif mode == 'exhausted':
        assert list(iterator) == ['chunk']
    else:
        with pytest.raises(ValueError):
            next(iterator)
    iterator.close()
    with acquire_slot():
        pass


@pytest.mark.parametrize('path', ['/analysis/rtl-signoff', '/analysis/rtl-signoff/stream'])
def test_both_api_variants_reject_before_starting_work(client, monkeypatch, path):
    calls = []
    def unexpected(*args):
        calls.append(True)
        raise AssertionError('capacity rejection must not execute tools')
    monkeypatch.setattr('app.routers.analysis.run_signoff', unexpected)
    monkeypatch.setattr('app.routers.analysis.stream_signoff', unexpected)
    with acquire_slot():
        response = client.post(path, json={'code': 'module top; endmodule'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '5'
    assert response.headers['content-type'].startswith('application/json')
    assert calls == []


def test_sync_and_stream_requests_share_capacity(client, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    def run(*args):
        entered.set()
        assert finish.wait(5)
        return SimpleNamespace(to_dict=lambda: {'verdict': 'REJECTED'})
    monkeypatch.setattr('app.routers.analysis.run_signoff', run)
    def first():
        with TestClient(client.app) as c:
            return c.post('/analysis/rtl-signoff', json={'code': 'module top; endmodule'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(first)
        try:
            assert entered.wait(5)
            assert client.post('/analysis/rtl-signoff/stream', json={'code': 'module top; endmodule'}).status_code == 429
            assert client.get('/health').status_code == 200
        finally:
            finish.set()
        assert request.result(timeout=5).status_code == 200
    with acquire_slot():
        pass


@pytest.mark.parametrize('value', ['0', '-1', '17', 'invalid'])
def test_invalid_capacity_rejected(value, monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_MAX_CONCURRENT', value)
    with pytest.raises(RuntimeError):
        capacity()


def test_response_send_failure_releases_unstarted_stream():
    import asyncio
    from app.services.rtl.admission import AdmittedStreamingResponse
    from starlette.requests import ClientDisconnect
    response = AdmittedStreamingResponse(iter(['chunk']), acquire_slot())
    async def send(message):
        raise OSError('client disconnected')
    async def receive():
        return {'type': 'http.disconnect'}
    with pytest.raises(ClientDisconnect):
        asyncio.run(response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send))
    with acquire_slot():
        pass


@pytest.mark.parametrize('version', ['2.3', '2.4'])
def test_disconnect_cancels_blocked_worker_before_next_event(version):
    entered, cancel = threading.Event(), threading.Event()
    def progress():
        entered.set()
        assert cancel.wait(2), 'worker never received disconnect cancellation'
        return
        yield 'unreachable'
    slot = acquire_slot()
    response = AdmittedStreamingResponse(progress(), slot, on_close=cancel.set)
    async def check():
        async def receive():
            assert await anyio.to_thread.run_sync(entered.wait, 1)
            return {'type': 'http.disconnect'}
        async def send(message):
            pass
        with anyio.fail_after(2):
            await response({'type': 'http', 'asgi': {'spec_version': version}}, receive, send)
    anyio.run(check)
    assert cancel.is_set() and slot.fd is None
    with acquire_slot():
        pass
