"""Persist OpenSTA results and batch lifecycle without HTTP-layer dependencies."""
from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db import SessionLocal
from ..models import (Domain, RunArtifact, RunEvidence, Severity, SignoffRun,
                      StaBatchExecution, StaBatchExecutionEvent, StaBatchExecutionItem, Violation)


def slack_text(value: float) -> str:
    compact = format(value, '.12g')
    return compact if float(compact) == value else str(value)


def record_sta_run(db, payload, worker, result, image_id, submitted_by):
    result['metadata'] = {'filename': 'server-generated-report.json', 'tool_version': f"OpenSTA {worker['opensta_commit'][:12]}",
                          'scenario': payload.scenario, 'top_module': payload.top_module,
                          'parasitics': 'spef' if payload.spef is not None else 'none'}
    result['execution'] = {'backend': 'container', 'image_id': image_id, 'opensta_commit': worker['opensta_commit'],
                           'agent_involved': False, 'log': worker['log'], 'inputs': worker['inputs']}
    result['input_artifacts'] = worker['inputs']
    result['submitted_by'] = submitted_by
    run = SignoffRun(project_id=payload.project_id, domain=Domain.sta, stage=payload.stage, tool='OpenSTA',
                     status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='opensta_execution', source_text=worker['report'],
                               source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    run.artifacts = [RunArtifact(kind=key, content_text=getattr(payload, key), **metadata)
                     for key, metadata in worker['inputs'].items()]
    for path in result['paths']:
        if path['slack_ps'] is None or path['slack_ps'] < 0:
            run.violations.append(Violation(
                check_name=f"opensta/{path['path_type']}/{path['fingerprint'][:32]}",
                severity=Severity.warning if path['slack_ps'] is None else Severity.error,
                location=path['endpoint'],
                description=f"{payload.scenario} · {path['path_group']} · {path['startpoint']} → {path['endpoint']}\n" +
                            ('Unconstrained path' if path['slack_ps'] is None else f"Reported slack: {slack_text(path['slack_ps'])} ps")))
    db.add(run)
    db.commit()
    return {'run_id': run.id, **result}


def update_batch_item(batch_id, position, status, *, run_id=None, detail=None):
    with SessionLocal() as session:
        item = session.scalar(select(StaBatchExecutionItem).where(
            StaBatchExecutionItem.batch_id == batch_id,
            StaBatchExecutionItem.position == position,
        ))
        if item is None or item.status == status:
            return False
        allowed = {'pending': {'running', 'failed', 'cancelled'},
                   'running': {'completed', 'failed', 'cancelled'}}
        if status not in allowed.get(item.status, set()):
            return False
        now = datetime.now(timezone.utc)
        item.status, item.run_id, item.detail = status, run_id, detail
        if status == 'running':
            item.started_at = now
        elif status in {'completed', 'failed', 'cancelled'}:
            item.finished_at = now
        kind = {'running': 'scenario_started', 'completed': 'scenario_completed',
                'failed': 'scenario_failed', 'cancelled': 'scenario_cancelled'}[status]
        session.add(StaBatchExecutionEvent(batch_id=batch_id, kind=kind, status=status,
            position=position, scenario=item.scenario, actor='system', detail=detail))
        session.commit()
        return True


def finish_sta_batch(batch_id, outcome, *, expired_before=None):
    with SessionLocal() as session:
        if expired_before is not None:
            claimed = session.execute(update(StaBatchExecution).where(
                StaBatchExecution.id == batch_id, StaBatchExecution.status == 'running',
                StaBatchExecution.finished_at.is_(None),
                StaBatchExecution.lease_expires_at.is_not(None),
                StaBatchExecution.lease_expires_at < expired_before,
            ).values(worker_token=None, lease_expires_at=None)
                .execution_options(synchronize_session=False))
            if claimed.rowcount != 1:
                session.rollback()
                return False
        batch = session.get(StaBatchExecution, batch_id)
        if batch is None or batch.finished_at is not None:
            session.rollback()
            return False
        now = datetime.now(timezone.utc)
        unfinished = session.scalars(select(StaBatchExecutionItem).where(
            StaBatchExecutionItem.batch_id == batch_id,
            StaBatchExecutionItem.status.in_(['pending', 'running']),
        )).all()
        if outcome != 'normal':
            state = 'cancelled' if outcome == 'cancelled' else 'failed'
            detail = 'Batch request was cancelled.' if outcome == 'cancelled' else 'Batch execution was interrupted.'
            for item in unfinished:
                item.status, item.detail, item.finished_at = state, detail, now
                session.add(StaBatchExecutionEvent(batch_id=batch_id,
                    kind='scenario_cancelled' if state == 'cancelled' else 'scenario_failed',
                    status=state, position=item.position, scenario=item.scenario,
                    actor='system', detail=detail))
        statuses = list(session.scalars(select(StaBatchExecutionItem.status).where(
            StaBatchExecutionItem.batch_id == batch_id,
        )))
        if outcome == 'cancelled':
            status = 'cancelled'
        else:
            completed = statuses.count('completed')
            status = 'completed' if completed == len(statuses) else 'partial' if completed else 'failed'
        batch.status, batch.finished_at = status, now
        batch.worker_token = batch.lease_expires_at = None
        session.add(StaBatchExecutionEvent(batch_id=batch_id, kind='finalized', status=status,
            actor='system', detail={'normal': None, 'cancelled': 'Cancellation completed.',
                                    'interrupted': 'Worker execution was interrupted.'}[outcome]))
        session.commit()
        return True
