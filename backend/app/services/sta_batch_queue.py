"""Durable, detachable OpenSTA batch queue backed by the application database."""
import hashlib
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import StaBatchExecution, StaBatchExecutionItem, StaBatchInputArtifact
from ..schemas import StaSignoffRequest
from .rtl.admission import acquire_slot
from .sta_execution import finish_sta_batch, record_sta_run, update_batch_item
from .sta_worker_client import StaWorkerError, run_sta

logger = logging.getLogger('uvicorn.error.signoff')
_wake = threading.Event()
LEASE_SECONDS = 15


def _artifact(batch_id, position, kind, content):
    encoded = content.encode('utf-8')
    return StaBatchInputArtifact(batch_id=batch_id, position=position, kind=kind,
        content_text=content, sha256=hashlib.sha256(encoded).hexdigest(), byte_length=len(encoded))


def submit_batch(db, payload, user, expected):
    batch = StaBatchExecution(
        project_id=payload.project_id, stage=payload.stage, top_module=payload.top_module,
        design_revision=payload.design_revision.strip(), submitted_by_user_id=user.id if user else None,
        submitted_by=user.username if user else 'local', status='queued',
        items=[StaBatchExecutionItem(position=index, scenario=item.scenario.strip(),
            require_spef=expected.get(item.scenario.strip(), False), status='pending')
            for index, item in enumerate(payload.scenarios)],
    )
    db.add(batch)
    db.flush()
    artifacts = [_artifact(batch.id, -1, 'netlist', payload.netlist)]
    for index, item in enumerate(payload.scenarios):
        artifacts += [_artifact(batch.id, index, 'liberty', item.liberty),
                      _artifact(batch.id, index, 'sdc', item.sdc)]
        if item.spef is not None:
            artifacts.append(_artifact(batch.id, index, 'spef', item.spef))
    db.add_all(artifacts)
    db.commit()
    db.refresh(batch)
    _wake.set()
    return batch


def retry_batch(db, source, user, request_key):
    """Clone an immutable terminal batch and its verified inputs as a new queued attempt."""
    key = str(request_key)
    existing = db.scalar(select(StaBatchExecution).where(StaBatchExecution.retry_request_key == key)
                         .options(selectinload(StaBatchExecution.items)))
    if existing is not None:
        if existing.retry_of_batch_id != source.id:
            raise HTTPException(409, 'retry request key already belongs to another STA batch')
        return existing
    if source.status in {'queued', 'running'}:
        raise HTTPException(409, 'only terminal STA batches can be retried')
    artifacts = list(db.scalars(select(StaBatchInputArtifact).where(
        StaBatchInputArtifact.batch_id == source.id).order_by(StaBatchInputArtifact.id)))
    expected = {(-1, 'netlist'), *((item.position, kind) for item in source.items for kind in ('liberty', 'sdc'))}
    actual = {(item.position, item.kind) for item in artifacts}
    if not expected.issubset(actual) or any(
        item.byte_length != len(item.content_text.encode('utf-8')) or
        item.sha256 != hashlib.sha256(item.content_text.encode('utf-8')).hexdigest()
        for item in artifacts
    ):
        raise HTTPException(409, 'stored STA batch inputs are incomplete or fail integrity verification')
    batch = StaBatchExecution(
        project_id=source.project_id, stage=source.stage, top_module=source.top_module,
        design_revision=source.design_revision, retry_of_batch_id=source.id,
        retry_request_key=key, attempt=source.attempt + 1,
        submitted_by_user_id=user.id if user else None,
        submitted_by=user.username if user else 'local', status='queued',
        items=[StaBatchExecutionItem(position=item.position, scenario=item.scenario,
            require_spef=item.require_spef, status='pending') for item in source.items],
    )
    db.add(batch)
    try:
        db.flush()
        db.add_all([StaBatchInputArtifact(batch_id=batch.id, position=item.position, kind=item.kind,
            content_text=item.content_text, sha256=item.sha256, byte_length=item.byte_length)
            for item in artifacts])
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(StaBatchExecution).where(StaBatchExecution.retry_request_key == key)
                             .options(selectinload(StaBatchExecution.items)))
        if existing is None or existing.retry_of_batch_id != source.id:
            raise
        return existing
    db.refresh(batch)
    _wake.set()
    return batch


def claim_next(worker_token):
    for _ in range(10):
        with SessionLocal() as db:
            batch_id = db.scalar(select(StaBatchExecution.id).where(
                StaBatchExecution.status == 'queued', StaBatchExecution.cancel_requested.is_(False),
            ).order_by(StaBatchExecution.id).limit(1))
            if batch_id is None:
                return None
            changed = db.execute(update(StaBatchExecution).where(
                StaBatchExecution.id == batch_id, StaBatchExecution.status == 'queued',
                StaBatchExecution.cancel_requested.is_(False),
            ).values(status='running', worker_token=worker_token,
                     started_at=datetime.now(timezone.utc), lease_expires_at=int(time.time()) + LEASE_SECONDS)
                .execution_options(synchronize_session=False))
            db.commit()
            if changed.rowcount == 1:
                return batch_id
    return None


def _cancel_monitor(batch_id, worker_token, cancel, done, stop):
    while not done.wait(0.25):
        if stop.is_set():
            cancel.set()
            return
        try:
            with SessionLocal() as db:
                requested = db.scalar(select(StaBatchExecution.cancel_requested).where(
                    StaBatchExecution.id == batch_id, StaBatchExecution.worker_token == worker_token))
                changed = db.execute(update(StaBatchExecution).where(
                    StaBatchExecution.id == batch_id, StaBatchExecution.worker_token == worker_token,
                    StaBatchExecution.status == 'running',
                ).values(lease_expires_at=int(time.time()) + LEASE_SECONDS)
                    .execution_options(synchronize_session=False))
                db.commit()
                if changed.rowcount != 1:
                    cancel.set()
                    return
        except Exception as error:
            logger.error('sta_batch_heartbeat_failed batch_id=%s failure=%s', batch_id, type(error).__name__)
            cancel.set()
            return
        if requested:
            cancel.set()
            return


def execute_claimed(batch_id, stop):
    with SessionLocal() as db:
        batch = db.scalar(select(StaBatchExecution).where(StaBatchExecution.id == batch_id)
                          .options(selectinload(StaBatchExecution.items)))
        artifacts = list(db.scalars(select(StaBatchInputArtifact).where(
            StaBatchInputArtifact.batch_id == batch_id)))
    if batch is None:
        return
    if any(item.byte_length != len(item.content_text.encode('utf-8')) or
           item.sha256 != hashlib.sha256(item.content_text.encode('utf-8')).hexdigest()
           for item in artifacts):
        logger.error('sta_batch_input_integrity_failed batch_id=%s', batch_id)
        finish_sta_batch(batch_id, 'interrupted')
        return
    values = {(item.position, item.kind): item.content_text for item in artifacts}
    netlist = values.get((-1, 'netlist'))
    if netlist is None:
        logger.error('sta_batch_input_missing batch_id=%s', batch_id)
        finish_sta_batch(batch_id, 'interrupted')
        return
    submitted_by = ({'user_id': batch.submitted_by_user_id, 'username': batch.submitted_by}
                    if batch.submitted_by_user_id is not None else None)
    cancel, monitor_done = threading.Event(), threading.Event()
    monitor = threading.Thread(target=_cancel_monitor, args=(batch_id, batch.worker_token, cancel, monitor_done, stop),
                               name=f'sta-batch-cancel-{batch_id}', daemon=True)
    monitor.start()
    try:
        for item in batch.items:
            if cancel.is_set():
                break
            liberty, sdc = values.get((item.position, 'liberty')), values.get((item.position, 'sdc'))
            if liberty is None or sdc is None:
                update_batch_item(batch_id, item.position, 'failed', detail='Stored batch input is incomplete.')
                continue
            spef = values.get((item.position, 'spef'))
            update_batch_item(batch_id, item.position, 'running')
            request = StaSignoffRequest(project_id=batch.project_id, stage=batch.stage,
                top_module=batch.top_module, design_revision=batch.design_revision,
                scenario=item.scenario, netlist=netlist, liberty=liberty, sdc=sdc, spef=spef)
            try:
                worker, result, image_id = run_sta(netlist, liberty, sdc, batch.top_module, spef, cancel=cancel)
                if cancel.is_set():
                    break
                with SessionLocal() as db:
                    recorded = record_sta_run(db, request, worker, result, image_id, submitted_by)
                update_batch_item(batch_id, item.position, 'completed', run_id=recorded['run_id'])
            except StaWorkerError as error:
                if cancel.is_set():
                    break
                update_batch_item(batch_id, item.position, 'failed', detail=str(error)[:2000])
            except Exception as error:
                logger.error('sta_detached_batch_failed batch_id=%s position=%s failure=%s',
                             batch_id, item.position, type(error).__name__)
                update_batch_item(batch_id, item.position, 'failed', detail='STA result could not be recorded.')
    finally:
        monitor_done.set()
        monitor.join(timeout=2)
        finish_sta_batch(batch_id, 'cancelled' if cancel.is_set() else 'normal')


def dispatcher_loop(stop):
    token = uuid.uuid4().hex
    while not stop.is_set():
        reconcile_stale_batches()
        batch_id = claim_next(token)
        if batch_id is None:
            _wake.wait(1)
            _wake.clear()
            continue
        slot = None
        while not stop.is_set() and slot is None:
            with SessionLocal() as db:
                cancelled = db.scalar(select(StaBatchExecution.cancel_requested).where(
                    StaBatchExecution.id == batch_id, StaBatchExecution.worker_token == token))
            if cancelled:
                break
            try:
                slot = acquire_slot()
            except HTTPException as error:
                if error.status_code != 429:
                    logger.error('sta_batch_dispatch_capacity_failed failure=%s', type(error).__name__)
                stop.wait(1)
        if slot is None:
            finish_sta_batch(batch_id, 'cancelled')
            continue
        try:
            execute_claimed(batch_id, stop)
        except Exception as error:
            logger.error('sta_batch_dispatch_failed failure=%s', type(error).__name__)
        finally:
            slot.close()


def wake_dispatcher():
    _wake.set()


def reconcile_stale_batches(now=None):
    now = int(time.time()) if now is None else now
    with SessionLocal() as db:
        candidates = list(db.execute(select(
            StaBatchExecution.id, StaBatchExecution.cancel_requested,
        ).where(StaBatchExecution.status == 'running',
                StaBatchExecution.lease_expires_at.is_not(None),
                StaBatchExecution.lease_expires_at < now).limit(100)))
    for batch_id, cancelled in candidates:
        with SessionLocal() as db:
            claimed = db.execute(update(StaBatchExecution).where(
                StaBatchExecution.id == batch_id, StaBatchExecution.status == 'running',
                StaBatchExecution.lease_expires_at < now,
            ).values(status='cancelled' if cancelled else 'failed', worker_token=None,
                     lease_expires_at=None).execution_options(synchronize_session=False))
            db.commit()
        if claimed.rowcount == 1:
            finish_sta_batch(batch_id, 'cancelled' if cancelled else 'interrupted')
            logger.warning('sta_batch_stale_finalized batch_id=%s', batch_id)
