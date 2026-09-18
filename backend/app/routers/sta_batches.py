from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..auth import require_project
from ..models import StaBatchExecution, StaBatchExecutionEvent, StaBatchExecutionItem
from ..schemas import StaBatchExecutionOut, StaBatchExecutionPage, StaBatchRetryRequest
from ..services.sta_batch_queue import retry_batch
from .projects import get_project_or_404

router = APIRouter(tags=['sta-batches'])


@router.get('/projects/{project_id}/sta-batches', response_model=StaBatchExecutionPage)
def list_sta_batches(
    project_id: int,
    before_id: int | None = Query(default=None, ge=1, le=2**63 - 1),
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    query = select(StaBatchExecution).where(StaBatchExecution.project_id == project_id)
    if before_id is not None:
        query = query.where(StaBatchExecution.id < before_id)
    rows = list(db.scalars(query.options(selectinload(StaBatchExecution.items),
                                         selectinload(StaBatchExecution.events))
                           .order_by(StaBatchExecution.id.desc()).limit(21)))
    return {'items': rows[:20], 'next_before_id': rows[19].id if len(rows) > 20 else None}


@router.get('/projects/{project_id}/sta-batches/{batch_id}', response_model=StaBatchExecutionOut)
def get_sta_batch(project_id: int, batch_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    row = db.scalar(select(StaBatchExecution).where(
        StaBatchExecution.id == batch_id,
        StaBatchExecution.project_id == project_id,
    ).options(selectinload(StaBatchExecution.items), selectinload(StaBatchExecution.events)))
    if row is None:
        raise HTTPException(404, 'STA batch not found')
    return row


@router.post('/projects/{project_id}/sta-batches/{batch_id}/retry', status_code=202,
             response_model=StaBatchExecutionOut)
def retry_sta_batch(project_id: int, batch_id: int, payload: StaBatchRetryRequest,
                    db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    require_project(db, project_id, 'editor')
    row = db.scalar(select(StaBatchExecution).where(
        StaBatchExecution.id == batch_id, StaBatchExecution.project_id == project_id,
    ).options(selectinload(StaBatchExecution.items), selectinload(StaBatchExecution.events)))
    if row is None:
        raise HTTPException(404, 'STA batch not found')
    return retry_batch(db, row, db.info.get('user'), payload.request_key)


@router.post('/projects/{project_id}/sta-batches/{batch_id}/cancel', response_model=StaBatchExecutionOut)
def cancel_sta_batch(project_id: int, batch_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    require_project(db, project_id, 'editor')
    row = db.scalar(select(StaBatchExecution).where(
        StaBatchExecution.id == batch_id, StaBatchExecution.project_id == project_id,
    ).options(selectinload(StaBatchExecution.items), selectinload(StaBatchExecution.events)))
    if row is None:
        raise HTTPException(404, 'STA batch not found')
    if row.status not in {'queued', 'running'}:
        raise HTTPException(409, 'only queued or running STA batches can be cancelled')
    if row.status == 'queued':
        now = datetime.now(timezone.utc)
        changed = db.execute(update(StaBatchExecution).where(
            StaBatchExecution.id == batch_id, StaBatchExecution.status == 'queued',
        ).values(status='cancelled', cancel_requested=True, finished_at=now)
            .execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'STA batch state changed; reload and try again')
        db.execute(update(StaBatchExecutionItem).where(
            StaBatchExecutionItem.batch_id == batch_id, StaBatchExecutionItem.status == 'pending',
        ).values(status='cancelled', detail='Batch request was cancelled.', finished_at=now)
            .execution_options(synchronize_session=False))
        for item in row.items:
            if item.status == 'pending':
                db.add(StaBatchExecutionEvent(batch_id=batch_id, kind='scenario_cancelled',
                    status='cancelled', position=item.position, scenario=item.scenario,
                    actor=db.info.get('user').username if db.info.get('user') else 'local',
                    actor_user_id=db.info.get('user').id if db.info.get('user') else None,
                    detail='Batch request was cancelled.'))
        db.add(StaBatchExecutionEvent(batch_id=batch_id, kind='finalized', status='cancelled',
            actor=db.info.get('user').username if db.info.get('user') else 'local',
            actor_user_id=db.info.get('user').id if db.info.get('user') else None,
            detail='Cancelled before worker start.'))
    else:
        changed = db.execute(update(StaBatchExecution).where(
            StaBatchExecution.id == batch_id, StaBatchExecution.status == 'running',
            StaBatchExecution.cancel_requested.is_(False),
        ).values(cancel_requested=True).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'STA batch cancellation is already pending')
        db.add(StaBatchExecutionEvent(batch_id=batch_id, kind='cancel_requested', status='running',
            actor=db.info.get('user').username if db.info.get('user') else 'local',
            actor_user_id=db.info.get('user').id if db.info.get('user') else None))
    db.commit()
    db.expire_all()
    return db.scalar(select(StaBatchExecution).where(StaBatchExecution.id == batch_id)
                     .options(selectinload(StaBatchExecution.items), selectinload(StaBatchExecution.events)))
