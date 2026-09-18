"""Reconcile expired containers belonging to this Sign-off deployment."""
import argparse
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import anyio

from .services.rtl.lifecycle import deployment_owner, LEASE_SECONDS
from .services.rtl.worker_client import remove_container, container_mode, WorkerError
from .worker_state import SweepCheckpoint, SweepBusy

SCAN_LIMIT = 100
INVENTORY_LIMIT = 10000
INSPECT_FORMAT = '{"id":{{json .Id}},"name":{{json .Name}},"created":{{json .Created}},"labels":{{json .Config.Labels}},"state":{{json .State.Status}}}'
logger = logging.getLogger('uvicorn.error.signoff')


class InventoryOverflow(WorkerError):
    pass


def docker_read(arguments, missing_id=None):
    try:
        result = subprocess.run(['docker', *arguments], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkerError('Worker inventory is unavailable.') from error
    if result.returncode:
        if missing_id is not None:
            absent = rb'no such (?:object|container):\s*' + re.escape(missing_id.encode('ascii')) + rb'(?:\s|$)'
            if re.search(absent, result.stderr.lower()):
                return None
        raise WorkerError('Worker inventory is unavailable.')
    return result.stdout.decode('utf-8')


def inspect_one(container_id):
    try:
        raw = docker_read(['container', 'inspect', '--format', INSPECT_FORMAT, container_id], missing_id=container_id)
        if raw is None:
            return None
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, UnicodeError) as error:
        raise WorkerError('Invalid worker inventory response.') from error


def eligible(record, owner, now):
    try:
        if not isinstance(record, dict) or re.fullmatch(r'[0-9a-f]{64}', record.get('id', '')) is None:
            return False
        if re.fullmatch(r'/signoff-rtl-job-[0-9a-f]{32}', record.get('name', '')) is None:
            return False
        labels = record.get('labels')
        if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in {
            'signoff.rtl-worker': '1', 'signoff.rtl-owner': owner,
            'signoff.rtl-lease-seconds': str(LEASE_SECONDS),
        }.items()):
            return False
        created = datetime.fromisoformat(record['created'].replace('Z', '+00:00'))
        if created.utcoffset() is None:
            return False
        return (now - created).total_seconds() >= LEASE_SECONDS
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


class ReconciliationSweep:
    """An in-memory inventory, consumed across bounded passes without ID cursors."""

    def __init__(self):
        self.pending = deque()
        self.owner = None

    def refresh(self, owner):
        if self.owner == owner and self.pending:
            return
        raw = docker_read(['ps', '-a', '--no-trunc', '--last', str(INVENTORY_LIMIT + 1),
                          '--filter', 'label=signoff.rtl-worker=1',
                          '--filter', f'label=signoff.rtl-owner={owner}', '--format', '{{.ID}}'])
        ids = raw.splitlines()
        if len(ids) > INVENTORY_LIMIT:
            raise InventoryOverflow('Worker inventory exceeds 10000 containers; operator intervention is required.')
        if len(set(ids)) != len(ids) or any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in ids):
            raise WorkerError('Invalid worker inventory response.')
        self.pending = deque(ids)
        self.owner = owner


def reconcile(*, apply=False, limit=25, now=None, stop=None, sweep=None):
    if type(limit) is not int or not 1 <= limit <= SCAN_LIMIT:
        raise ValueError('limit must be between 1 and 100')
    owner = deployment_owner()
    deadline = time.monotonic() + 20
    if now is None:
        # Created timestamps belong to the daemon clock, which can differ from
        # the API host when a remote Docker daemon is used.
        try:
            now = datetime.fromisoformat(docker_read(['info', '--format', '{{.SystemTime}}']).strip().replace('Z', '+00:00'))
        except (ValueError, UnicodeError) as error:
            raise WorkerError('Docker reference time is unavailable.') from error
    if now.utcoffset() is None:
        raise ValueError('reference time must include a timezone')
    if sweep is None:
        sweep = ReconciliationSweep()
    sweep.refresh(owner)
    listed = len(sweep.pending)
    items = []
    scanned = 0
    for _ in range(min(SCAN_LIMIT, listed)):
        if (stop is not None and stop.is_set()) or time.monotonic() >= deadline or len(items) >= limit:
            break
        container_id = sweep.pending[0]
        # Preserve unfinished work on a stop/deadline, but defer a failed object
        # until the next inventory so it cannot keep this sweep alive forever.
        sweep.pending.rotate(-1)
        try:
            record = inspect_one(container_id)
            scanned += 1
            if record is None or record.get('id') != container_id or not eligible(record, owner, now):
                sweep.pending.pop()
                continue
            if apply:
                if time.monotonic() >= deadline or (stop is not None and stop.is_set()):
                    break
                # Recheck identity and ownership immediately before removal. Use
                # immutable IDs so a reused name cannot target a replacement job.
                current = inspect_one(container_id)
                if current is None or current.get('id') != container_id or not eligible(current, owner, now):
                    sweep.pending.pop()
                    continue
                if time.monotonic() >= deadline or (stop is not None and stop.is_set()):
                    break
                remove_container(container_id)
        except WorkerError:
            sweep.pending.pop()
            # The failure still reaches the caller/log; this is not a successful
            # removal. If it remains in Docker, the next inventory includes it.
            raise
        sweep.pending.pop()
        items.append({'id': container_id, 'name': record['name'], 'created': record['created'],
                      'action': 'removed' if apply else 'would_remove'})
    return {'mode': 'apply' if apply else 'preview', 'owner': owner, 'reference_time': now.isoformat(),
            'scan_limit': SCAN_LIMIT, 'scanned': scanned, 'listed': listed,
            'remaining': len(sweep.pending), 'scan_truncated': bool(sweep.pending), 'items': items}


def persistent_reconcile(*, limit=25, now=None, stop=None):
    owner = deployment_owner()
    daemon_id = docker_read(['info', '--format', '{{.ID}}']).strip()
    if re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', daemon_id) is None:
        raise WorkerError('Docker daemon identity is unavailable.')
    directory = os.environ.get('SIGNOFF_RTL_REAPER_STATE_DIR', str(Path(__file__).resolve().parents[1] / '.rtl-reaper'))
    checkpoint = SweepCheckpoint(directory, owner, daemon_id, INVENTORY_LIMIT)
    sweep = ReconciliationSweep()
    try:
        with checkpoint.locked():
            sweep.pending = deque(checkpoint.load())
            sweep.owner = owner
            # Check storage before container mutations. The previous checkpoint
            # remains usable if a later save fails or the process is killed.
            checkpoint.save(sweep.pending)
            try:
                return reconcile(apply=True, limit=limit, now=now, stop=stop, sweep=sweep)
            finally:
                checkpoint.save(sweep.pending)
    except OSError as error:
        raise WorkerError('Worker checkpoint storage is unavailable.') from error


def reaper_loop(stop, interval):
    while not stop.is_set():
        try:
            result = persistent_reconcile(stop=stop)
            if result['items']:
                logger.info('Removed %d expired RTL worker containers for %s', len(result['items']), result['owner'])
        except InventoryOverflow:
            logger.error('RTL worker inventory exceeds 10000 containers; operator intervention is required.')
        except SweepBusy:
            pass  # The process holding the kernel lock is advancing this sweep.
        except Exception as error:
            logger.error('RTL worker reconciliation failed: %s', type(error).__name__)
        stop.wait(interval)


@asynccontextmanager
async def worker_lifespan(app):
    enabled = os.environ.get('SIGNOFF_RTL_REAPER_ENABLED', '0')
    if enabled not in {'0', '1'}:
        raise ValueError('SIGNOFF_RTL_REAPER_ENABLED must be 0 or 1')
    stop, thread = threading.Event(), None
    from .services.sta_batch_queue import dispatcher_loop
    sta_thread = threading.Thread(target=dispatcher_loop, args=(stop,), name='sta-batch-dispatcher', daemon=True)
    sta_thread.start()
    isolated = container_mode()
    if isolated:
        deployment_owner()
    if enabled == '1':
        if not isolated:
            raise ValueError('RTL reaper requires container execution mode')
        deployment_owner()
        thread = threading.Thread(target=reaper_loop, args=(stop, 60), name='rtl-worker-reaper', daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread is not None:
            # Docker calls have bounded waits; allow an in-flight removal to finish.
            await anyio.to_thread.run_sync(lambda: thread.join(timeout=30))
        await anyio.to_thread.run_sync(lambda: sta_thread.join(timeout=30))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='remove expired owned workers (default: preview)')
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--passes', type=int, default=1, help='continue the inventory for up to 1–100 passes')
    parser.add_argument('--resume', action='store_true', help='use the shared automatic-reaper checkpoint (requires --apply)')
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.passes <= 100:
            raise ValueError('passes must be between 1 and 100')
        if args.resume and not args.apply:
            raise ValueError('--resume requires --apply; preview does not advance automatic cleanup')
        sweep = ReconciliationSweep()
        for _ in range(args.passes):
            result = (persistent_reconcile(limit=args.limit) if args.resume else
                      reconcile(apply=args.apply, limit=args.limit, sweep=sweep))
            print(json.dumps(result), flush=True)
            if not result['remaining']:
                break
    except (ValueError, WorkerError) as error:
        parser.exit(1, f'Worker reconciliation failed: {error}\n')


if __name__ == '__main__':
    main()
