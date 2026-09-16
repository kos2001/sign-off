from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

import anyio
import pytest

from app import worker_maintenance as maintenance
from app.services.rtl.worker_client import WorkerError, worker_command

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def record(number=1, age=360):
    return {'id': f'{number:064x}', 'name': f'/signoff-rtl-job-{number:032x}',
            'created': (NOW - timedelta(seconds=age)).isoformat(), 'state': 'running',
            'labels': {'signoff.rtl-worker': '1', 'signoff.rtl-owner': 'qa-scope', 'signoff.rtl-lease-seconds': '360'}}


@pytest.mark.parametrize('age,expected', [(359.9, False), (360, True), (361, True), (-1, False)])
def test_expiry_boundary(age, expected):
    assert maintenance.eligible(record(age=age), 'qa-scope', NOW) is expected


@pytest.mark.parametrize('kind', ['owner', 'legacy', 'lease', 'name', 'id', 'created', 'naive'])
def test_unowned_or_unverifiable_containers_are_preserved(kind):
    value = record()
    if kind == 'owner':
        value['labels']['signoff.rtl-owner'] = 'another-service'
    elif kind == 'legacy':
        del value['labels']['signoff.rtl-lease-seconds']
    elif kind == 'lease':
        value['labels']['signoff.rtl-lease-seconds'] = '1'
    elif kind == 'name':
        value['name'] = '/another-application'
    elif kind == 'id':
        value['id'] = 'short'
    elif kind == 'created':
        value['created'] = 'broken'
    else:
        value['created'] = '2020-01-01T00:00:00'
    assert not maintenance.eligible(value, 'qa-scope', NOW)


@pytest.fixture
def inventory(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa-scope')
    values = {value['id']: value for value in [record(1), record(2, 10), record(3, 1000)]}
    monkeypatch.setattr(maintenance, 'docker_read', lambda *args, **kwargs: '\n'.join(values))
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: deepcopy(values.get(identifier)))
    removed = []
    monkeypatch.setattr(maintenance, 'remove_container', removed.append)
    return values, removed


def test_preview_and_bounded_apply_use_immutable_ids(inventory):
    values, removed = inventory
    preview = maintenance.reconcile(now=NOW)
    assert [item['id'] for item in preview['items']] == [record(1)['id'], record(3)['id']]
    assert not removed
    applied = maintenance.reconcile(now=NOW, apply=True, limit=1)
    assert removed == [record(1)['id']]
    assert applied['scan_truncated'] and applied['items'][0]['action'] == 'removed'


@pytest.mark.parametrize('changed', ['owner', 'name', 'gone'])
def test_rechecks_before_deletion(inventory, monkeypatch, changed):
    values, removed = inventory
    selected = record()
    monkeypatch.setattr(maintenance, 'docker_read', lambda *args, **kwargs: selected['id'])
    second = deepcopy(selected)
    if changed == 'owner':
        second['labels']['signoff.rtl-owner'] = 'another-service'
    elif changed == 'name':
        second['name'] = '/adopted-by-operator'
    else:
        second = None
    snapshots = iter([selected, second])
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: next(snapshots))
    assert maintenance.reconcile(now=NOW, apply=True)['items'] == []
    assert not removed


def test_missing_container_is_not_a_daemon_error(monkeypatch):
    identifier = record()['id']
    monkeypatch.setattr(maintenance.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr=f'error: no such object: {identifier}'.encode()))
    assert maintenance.inspect_one(identifier) is None
    monkeypatch.setattr(maintenance.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr=b'cannot connect: no such host'))
    with pytest.raises(WorkerError):
        maintenance.inspect_one(identifier)


def test_stop_signal_prevents_removals(inventory):
    _, removed = inventory
    stop = threading.Event()
    stop.set()
    assert maintenance.reconcile(now=NOW, apply=True, stop=stop)['items'] == []
    assert not removed


def test_background_reaper_starts_and_stops_with_lifespan(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_REAPER_ENABLED', '1')
    monkeypatch.setenv('SIGNOFF_RTL_EXECUTION', 'container')
    invoked = threading.Event()
    def reconcile(**kwargs):
        assert kwargs['stop'] is not None
        invoked.set()
        return {'items': []}
    monkeypatch.setattr(maintenance, 'persistent_reconcile', reconcile)
    async def check():
        async with maintenance.worker_lifespan(None):
            assert await anyio.to_thread.run_sync(invoked.wait, 1)
    anyio.run(check)
    assert not any(thread.name == 'rtl-worker-reaper' and thread.is_alive() for thread in threading.enumerate())


def test_new_jobs_carry_ownership_and_lifetime(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa-scope')
    command = worker_command('signoff-rtl-job-' + 'a' * 32, 'sha256:' + 'b' * 64)
    assert 'signoff.rtl-owner=qa-scope' in command
    assert 'signoff.rtl-lease-seconds=360' in command


def test_age_uses_daemon_clock_instead_of_api_host(inventory, monkeypatch):
    _, removed = inventory
    def read(arguments, **kwargs):
        return NOW.isoformat() if arguments[0] == 'info' else record(2)['id']
    monkeypatch.setattr(maintenance, 'docker_read', read)
    result = maintenance.reconcile(apply=True)
    assert result['reference_time'] == NOW.isoformat()
    assert result['items'] == [] and not removed  # This record is only 10 seconds old on the daemon.


def test_sweep_reaches_old_jobs_despite_new_arrivals(monkeypatch):
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa-scope')
    values = {value['id']: value for value in [*[record(i, 10) for i in range(1, 102)], record(102, 1000)]}
    reads = []
    def read(*args, **kwargs):
        reads.append(args)
        return '\n'.join(values)
    monkeypatch.setattr(maintenance, 'docker_read', read)
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: deepcopy(values.get(identifier)))
    removed = []
    monkeypatch.setattr(maintenance, 'remove_container', removed.append)
    sweep = maintenance.ReconciliationSweep()
    first = maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    assert first['scanned'] == 100 and first['remaining'] == 2
    # New arrivals cannot displace the tail of the inventory already captured.
    values.update({value['id']: value for value in [record(i, 10) for i in range(103, 250)]})
    second = maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    assert removed == [record(102)['id']]
    assert second['remaining'] == 0 and len(reads) == 1
    maintenance.reconcile(now=NOW, sweep=sweep)
    assert len(reads) == 2  # New inventory after the previous one is exhausted.


def test_sweep_retries_failed_job_after_other_jobs(inventory, monkeypatch):
    values, removed = inventory
    sweep = maintenance.ReconciliationSweep()
    def inspect(identifier):
        if identifier == record(1)['id']:
            raise WorkerError('unavailable')
        return deepcopy(values.get(identifier))
    monkeypatch.setattr(maintenance, 'inspect_one', inspect)
    with pytest.raises(WorkerError):
        maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    result = maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    assert result['remaining'] == 0
    assert removed == [record(3)['id']]
    # The failed object is retried only after a new inventory is captured.
    with pytest.raises(WorkerError):
        maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    assert list(sweep.pending) == [record(2)['id'], record(3)['id']]


def test_sweep_handles_disappearing_jobs_and_removal_limit(inventory):
    values, removed = inventory
    sweep = maintenance.ReconciliationSweep()
    maintenance.reconcile(now=NOW, apply=True, limit=1, sweep=sweep)
    del values[record(2)['id']]
    result = maintenance.reconcile(now=NOW, apply=True, limit=1, sweep=sweep)
    assert result['remaining'] == 0
    assert removed == [record(1)['id'], record(3)['id']]


@pytest.mark.parametrize('kind', ['duplicate', 'overflow', 'invalid'])
def test_inventory_rejects_incomplete_or_invalid_listing(monkeypatch, kind):
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa-scope')
    rows = {'duplicate': [record()['id']] * 2,
            'overflow': [f'{i:064x}' for i in range(maintenance.INVENTORY_LIMIT + 1)],
            'invalid': ['not-an-id']}[kind]
    monkeypatch.setattr(maintenance, 'docker_read', lambda *args, **kwargs: '\n'.join(rows))
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: pytest.fail('must not inspect'))
    with pytest.raises(WorkerError):
        maintenance.reconcile(now=NOW, apply=True)


def test_changing_owner_discards_old_inventory(inventory, monkeypatch):
    values, _ = inventory
    sweep = maintenance.ReconciliationSweep()
    maintenance.reconcile(now=NOW, limit=1, sweep=sweep)
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'other-deployment')
    monkeypatch.setattr(maintenance, 'docker_read', lambda *args, **kwargs: '')
    result = maintenance.reconcile(now=NOW, apply=True, sweep=sweep)
    assert result['listed'] == 0 and not sweep.pending


def test_cli_continues_one_inventory_and_reports_each_pass(inventory, monkeypatch, capsys):
    import json
    values, removed = inventory
    def read(arguments, **kwargs):
        return NOW.isoformat() if arguments[0] == 'info' else '\n'.join(values)
    monkeypatch.setattr(maintenance, 'docker_read', read)
    maintenance.main(['--apply', '--limit', '1', '--passes', '3'])
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(results) == 2
    assert [result['remaining'] for result in results] == [2, 0]
    assert removed == [record(1)['id'], record(3)['id']]


@pytest.mark.parametrize('failure_stage', ['inspect', 'recheck', 'remove'])
def test_persistent_failure_does_not_block_future_inventories(monkeypatch, tmp_path, failure_stage):
    monkeypatch.setenv('SIGNOFF_RTL_REAPER_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('SIGNOFF_RTL_WORKER_OWNER', 'qa-scope')
    values = {value['id']: value for value in [record(1), record(2)]}
    listings, removed, attempts = [], [], []
    def read(arguments, **kwargs):
        if arguments[0] == 'info':
            return 'qa-daemon'
        listings.append(list(values))
        return '\n'.join(values)
    def inspect(identifier):
        if identifier == record(1)['id']:
            attempts.append(identifier)
            if failure_stage == 'inspect' or (failure_stage == 'recheck' and len(attempts) % 2 == 0):
                raise WorkerError('persistent inspection failure')
        return deepcopy(values.get(identifier))
    def remove(identifier):
        if identifier == record(1)['id']:
            raise WorkerError('persistent removal failure')
        removed.append(identifier)
        del values[identifier]
    monkeypatch.setattr(maintenance, 'docker_read', read)
    monkeypatch.setattr(maintenance, 'inspect_one', inspect)
    monkeypatch.setattr(maintenance, 'remove_container', remove)
    for index in range(4):
        if index == 2:
            values[record(3)['id']] = record(3)
        try:
            maintenance.persistent_reconcile(now=NOW)
        except WorkerError:
            pass
    assert len(listings) == 2
    assert removed == [record(2)['id'], record(3)['id']]
    assert record(1)['id'] in values  # Failed operations are never reported as successful removal.
    assert len(attempts) >= 2  # The failed job is retried, not permanently forgotten.


@pytest.mark.parametrize('reason', ['stop', 'deadline'])
def test_interrupted_before_removal_remains_in_current_inventory(inventory, monkeypatch, reason):
    values, removed = inventory
    stop, elapsed = threading.Event(), threading.Event()
    monkeypatch.setattr(maintenance.time, 'monotonic', lambda: 21 if elapsed.is_set() else 0)
    def inspect(identifier):
        (stop if reason == 'stop' else elapsed).set()
        return deepcopy(values.get(identifier))
    monkeypatch.setattr(maintenance, 'inspect_one', inspect)
    sweep = maintenance.ReconciliationSweep()
    result = maintenance.reconcile(now=NOW, apply=True, sweep=sweep, stop=stop)
    assert result['remaining'] == 3 and not removed
    assert record(1)['id'] in sweep.pending
    stop.clear()
    elapsed.clear()
    monkeypatch.setattr(maintenance, 'inspect_one', lambda identifier: deepcopy(values.get(identifier)))
    result = maintenance.reconcile(now=NOW, apply=True, sweep=sweep, stop=stop)
    assert result['remaining'] == 0
    assert set(removed) == {record(1)['id'], record(3)['id']}
