from datetime import datetime, timezone
import json
import os
import subprocess
import sys

import pytest

from app import worker_maintenance as maintenance
from app.services.rtl.worker_client import WorkerError
from app.worker_state import SweepCheckpoint, SweepBusy

ID = 'a' * 64


@pytest.fixture
def checkpoint(tmp_path):
    return SweepCheckpoint(tmp_path / 'state', 'qa', 'daemon-one', 10000)


def test_checkpoint_survives_process_exit_and_kernel_lock_is_released(checkpoint):
    program = '''
import os, sys
from app.worker_state import SweepCheckpoint
checkpoint = SweepCheckpoint(sys.argv[1], 'qa', 'daemon-one', 10000)
with checkpoint.locked():
    checkpoint.save(['a' * 64])
    os._exit(7)
'''
    result = subprocess.run([sys.executable, '-c', program, str(checkpoint.directory)], timeout=5)
    assert result.returncode == 7
    with checkpoint.locked():
        assert checkpoint.load() == [ID]
    assert checkpoint.path.stat().st_mode & 0o777 == 0o600
    assert checkpoint.directory.stat().st_mode & 0o777 == 0o700


def test_concurrent_process_cannot_overwrite_live_sweep(checkpoint):
    program = '''
import sys
from app.worker_state import SweepCheckpoint, SweepBusy
try:
    with SweepCheckpoint(sys.argv[1], 'qa', 'daemon-one', 10000).locked():
        sys.exit(4)
except SweepBusy:
    sys.exit(0)
'''
    with checkpoint.locked():
        checkpoint.save([ID])
        result = subprocess.run([sys.executable, '-c', program, str(checkpoint.directory)], timeout=5)
        assert result.returncode == 0
        assert checkpoint.load() == [ID]


@pytest.mark.parametrize('bad', [b'{', b'[]', b'\xff', b'[' * 2000,
    b'{"version":1,"version":1}', b' ' * (1024 * 1024 + 1)])
def test_corrupt_checkpoint_refreshes_inventory(checkpoint, bad, caplog):
    with checkpoint.locked():
        checkpoint.path.write_bytes(bad)
        checkpoint.path.chmod(0o600)
        assert checkpoint.load() == []
    assert 'inventory will be refreshed' in caplog.text


@pytest.mark.parametrize('field,value', [('owner', 'other'), ('daemon_id', 'other'),
    ('version', True), ('pending', [ID, ID]), ('pending', ['--other']), ('pending', [None])])
def test_invalid_checkpoint_metadata_is_not_trusted(checkpoint, field, value):
    with checkpoint.locked():
        checkpoint.save([ID])
        data = json.loads(checkpoint.path.read_text())
        data[field] = value
        checkpoint.path.write_text(json.dumps(data))
        assert checkpoint.load() == []


def test_daemon_and_owner_have_independent_checkpoints(checkpoint):
    with checkpoint.locked():
        checkpoint.save([ID])
    for owner, daemon in [('other', 'daemon-one'), ('qa', 'daemon-two')]:
        other = SweepCheckpoint(checkpoint.directory, owner, daemon, 10000)
        with other.locked():
            assert other.load() == []
    with checkpoint.locked():
        assert checkpoint.load() == [ID]


def test_failed_atomic_replace_preserves_previous_checkpoint(checkpoint, monkeypatch):
    with checkpoint.locked():
        checkpoint.save([ID])
        def fail(*args):
            raise OSError('disk unavailable')
        monkeypatch.setattr(os, 'replace', fail)
        with pytest.raises(OSError):
            checkpoint.save(['b' * 64])
        assert checkpoint.load() == [ID]
        assert not list(checkpoint.directory.glob('.checkpoint-*'))


@pytest.mark.parametrize('kind', ['directory', 'state', 'lock'])
def test_symlinks_are_rejected_without_touching_target(checkpoint, tmp_path, kind):
    target = tmp_path / 'target'
    if kind == 'directory':
        target.mkdir(mode=0o700)
        checkpoint.directory.symlink_to(target, target_is_directory=True)
    else:
        checkpoint.directory.mkdir(mode=0o700)
        target.write_text('untouched')
        (checkpoint.path if kind == 'state' else checkpoint.lock_path).symlink_to(target)
    with pytest.raises((OSError, WorkerError)):
        with checkpoint.locked():
            checkpoint.load()
    if kind != 'directory':
        assert target.read_text() == 'untouched'


def test_persistent_pass_resumes_and_does_not_relist(monkeypatch, tmp_path):
    monkeypatch.setenv('SIGNOFF_RTL_REAPER_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa')
    calls = []
    def read(args, **kwargs):
        calls.append(args[0])
        return 'daemon-one' if args[0] == 'info' else '\n'.join([ID, 'b' * 64])
    monkeypatch.setattr(maintenance, 'docker_read', read)
    monkeypatch.setattr(maintenance, 'SCAN_LIMIT', 1)
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: None)
    first = maintenance.persistent_reconcile(limit=1, now=datetime.now(timezone.utc))
    second = maintenance.persistent_reconcile(limit=1, now=datetime.now(timezone.utc))
    assert first['remaining'] == 1 and second['remaining'] == 0
    assert calls.count('ps') == 1


def test_failed_inspect_deferral_to_next_inventory_is_saved(monkeypatch, tmp_path):
    monkeypatch.setenv('SIGNOFF_RTL_REAPER_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa')
    monkeypatch.setattr(maintenance, 'docker_read', lambda args, **kwargs:
                        'daemon-one' if args[0] == 'info' else '\n'.join([ID, 'b' * 64]))
    def fail(identifier):
        raise WorkerError('unavailable')
    monkeypatch.setattr(maintenance, 'inspect_one', fail)
    with pytest.raises(WorkerError):
        maintenance.persistent_reconcile(now=datetime.now(timezone.utc))
    checkpoint = SweepCheckpoint(tmp_path / 'state', 'qa', 'daemon-one', 10000)
    with checkpoint.locked():
        assert checkpoint.load() == ['b' * 64]


def test_storage_failure_prevents_container_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv('SIGNOFF_RTL_REAPER_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(maintenance, 'docker_read', lambda *args, **kwargs: 'daemon-one')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(SweepCheckpoint, 'save', fail)
    monkeypatch.setattr(maintenance, 'reconcile', lambda **kwargs: pytest.fail('must not mutate'))
    with pytest.raises(WorkerError, match='storage is unavailable'):
        maintenance.persistent_reconcile()


def test_preview_cannot_advance_shared_checkpoint(capsys):
    with pytest.raises(SystemExit) as error:
        maintenance.main(['--resume'])
    assert error.value.code == 1
    assert '--resume requires --apply' in capsys.readouterr().err
