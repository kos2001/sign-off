from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import StaBatchExecution
from ..schemas import StaBatchExecutionOut, StaBatchExecutionPage
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
    rows = list(db.scalars(query.options(selectinload(StaBatchExecution.items))
                           .order_by(StaBatchExecution.id.desc()).limit(21)))
    return {'items': rows[:20], 'next_before_id': rows[19].id if len(rows) > 20 else None}


@router.get('/projects/{project_id}/sta-batches/{batch_id}', response_model=StaBatchExecutionOut)
def get_sta_batch(project_id: int, batch_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    row = db.scalar(select(StaBatchExecution).where(
        StaBatchExecution.id == batch_id,
        StaBatchExecution.project_id == project_id,
    ).options(selectinload(StaBatchExecution.items)))
    if row is None:
        raise HTTPException(404, 'STA batch not found')
    return row
