import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors import issue_credential
from ..db import get_db
from ..models import CollectorCredential, CollectorCredentialEvent
from ..schemas import (CollectorCredentialCreate, CollectorCredentialEventPage,
                       CollectorCredentialIssuedOut, CollectorCredentialOut)
from .projects import get_project_or_404

router = APIRouter(prefix='/projects/{project_id}/collectors', tags=['collectors'])


def credential_out(item: CollectorCredential) -> dict:
    status = 'revoked' if item.revoked_at is not None else 'expired' if item.expires_at <= int(time.time()) else 'active'
    return {
        'id': item.id, 'project_id': item.project_id, 'name': item.name,
        'expires_at': item.expires_at, 'revoked_at': item.revoked_at,
        'last_used_at': item.last_used_at, 'created_at': item.created_at, 'status': status,
    }


@router.get('', response_model=list[CollectorCredentialOut])
def list_collector_credentials(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    rows = db.scalars(select(CollectorCredential).where(
        CollectorCredential.project_id == project_id,
    ).order_by(CollectorCredential.id.desc())).all()
    return [credential_out(item) for item in rows]


@router.post('', response_model=CollectorCredentialIssuedOut, status_code=201)
def create_collector_credential(project_id: int, payload: CollectorCredentialCreate,
                                response: Response, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    user = db.info.get('user')
    try:
        item, token = issue_credential(
            db, project_id, payload.name, payload.valid_days,
            actor=user.username if user else 'local operator',
            actor_user_id=user.id if user else None,
        )
        db.commit()
        db.refresh(item)
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    response.headers['Cache-Control'] = 'no-store'
    return {**credential_out(item), 'token': token}


@router.get('/history', response_model=CollectorCredentialEventPage)
def collector_credential_history(project_id: int, before_id: int | None = Query(None, ge=1),
                                 limit: int = Query(25, ge=1, le=100),
                                 db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filters = [CollectorCredentialEvent.project_id == project_id]
    if before_id is not None:
        filters.append(CollectorCredentialEvent.id < before_id)
    rows = db.scalars(select(CollectorCredentialEvent).where(*filters)
                      .order_by(CollectorCredentialEvent.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {'items': items, 'next_before_id': items[-1].id if len(rows) > limit else None}


@router.delete('/{credential_id}', response_model=CollectorCredentialOut)
def revoke_collector_credential(project_id: int, credential_id: int,
                                db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    item = db.scalar(select(CollectorCredential).where(
        CollectorCredential.id == credential_id,
        CollectorCredential.project_id == project_id,
    ))
    if item is None:
        raise HTTPException(404, 'collector credential not found')
    if item.revoked_at is None:
        user = db.info.get('user')
        item.revoked_at = datetime.now(timezone.utc)
        db.add(CollectorCredentialEvent(
            project_id=project_id, credential_id=item.id, credential_name=item.name,
            action='revoked', actor=user.username if user else 'local operator',
            actor_user_id=user.id if user else None, expires_at=item.expires_at,
        ))
        db.commit()
        db.refresh(item)
    return credential_out(item)
