"""Run-scoped, persisted advisory reviews of captured evidence."""
import asyncio
import hashlib
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from ..services.rtl.artifacts import netlist_metadata_only
from ..db import get_db
from ..auth import require_project
from ..hermes import REVIEW_GUIDANCE, ROLES, Settings
from ..models import RunAgentReview
from .agents import _run_role
from .runs import get_run_or_404

router = APIRouter(tags=['run-reviews'])
SUMMARY_FIELDS = ('id', 'run_id', 'request_key', 'requester', 'requester_user_id', 'role', 'status', 'created_at')
COMPLETION_NOTICE_AFTER = timedelta(minutes=2)
MAX_EXPORT_BYTES = 2 * 1024 * 1024


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID


class CloseReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=1000)


def finish_review(db, review_id, outcome):
    # Only the first terminal transition wins, including an operator closure.
    db.execute(update(RunAgentReview).where(
        RunAgentReview.id == review_id, RunAgentReview.status == 'running',
    ).values(status='completed' if outcome['available'] else 'failed', outcome=outcome)
        .execution_options(synchronize_session=False))
    db.commit()
    db.expire_all()
    return db.get(RunAgentReview, review_id)


def snapshot(run):
    evidence = run.evidence
    if evidence is None or evidence.source not in {'rtl_ladder', 'opensta_report', 'opensta_execution',
                                                   'commercial_sta_report'}:
        raise HTTPException(409, '저장된 RTL 또는 STA 실행 근거가 필요합니다.')
    if evidence.source_text is None or hashlib.sha256(evidence.source_text.encode()).hexdigest() != evidence.source_sha256:
        raise HTTPException(409, '원본 해시가 일치하지 않아 검토를 시작할 수 없습니다.')
    data = {'run_id': run.id, 'project_id': run.project_id, 'stage': run.stage.value,
            'design_revision': evidence.design_revision, 'source_sha256': evidence.source_sha256,
            'evidence_source': evidence.source}
    if evidence.source == 'rtl_ladder':
        role = ROLES['a1_rtl']
        data['analysis'] = netlist_metadata_only(evidence.result)
    else:
        role = ROLES['a2_timing']
        result = evidence.result
        paths = result['paths']
        ranked = sorted(paths, key=lambda path: (path['slack_ps'] is None, path['slack_ps'] or 0, path['index']))
        data['analysis'] = {'metadata': result.get('metadata', {}), 'coverage': result['coverage'],
                            'coverage_note': result['coverage_note'], 'metrics': result['metrics'],
                            'reported_total': len(paths), 'included_paths': ranked[:20],
                            'selection_note': 'Reported paths only; at most 20 lowest-slack paths, unconstrained last. Not full STA coverage.'}
    data['review_mode'] = 'User-requested saved evidence review, including missing coverage; automatic trigger predicates do not apply.'
    # Round-trip detaches the snapshot from mutable ORM JSON references.
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 256 * 1024:
        raise HTTPException(413, '검토 입력이 256 KiB를 초과합니다.')
    return role, json.loads(encoded)


def summary(row, *, now=None):
    data = {key: getattr(row, key) for key in SUMMARY_FIELDS}
    created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    data['created_at'] = created
    data['completion_overdue'] = row.status == 'running' and (now or datetime.now(timezone.utc)) - created >= COMPLETION_NOTICE_AFTER
    return data


def detail(row):
    return {**summary(row), 'input_snapshot': row.input_snapshot, 'review_policy': row.review_policy,
            'model_alias': row.model_alias, 'outcome': row.outcome}


@router.get('/runs/{run_id}/agent-reviews')
def list_reviews(run_id: int, before_id: int | None = Query(None, ge=1, le=2**63-1), db: Session = Depends(get_db)):
    get_run_or_404(run_id, db)
    query = select(RunAgentReview).options(
        load_only(*(getattr(RunAgentReview, key) for key in SUMMARY_FIELDS), raiseload=True)
    ).where(RunAgentReview.run_id == run_id)
    if before_id is not None:
        query = query.where(RunAgentReview.id < before_id)
    rows = list(db.scalars(query.order_by(RunAgentReview.id.desc()).limit(21)))
    return {'items': [summary(row) for row in rows[:20]], 'next_before_id': rows[19].id if len(rows) > 20 else None}


@router.get('/runs/{run_id}/agent-reviews/{review_id}')
def get_review(run_id: int, review_id: int, db: Session = Depends(get_db)):
    get_run_or_404(run_id, db)
    row = db.scalar(select(RunAgentReview).where(RunAgentReview.run_id == run_id, RunAgentReview.id == review_id))
    if row is None:
        raise HTTPException(404, 'review not found')
    return detail(row)


@router.get('/runs/{run_id}/agent-reviews/{review_id}/export')
def export_review(run_id: int, review_id: int, db: Session = Depends(get_db)):
    review = get_review(run_id, review_id, db)
    bundle = {
        'format': 'signoff/run-agent-review-export/v1',
        'exported_at': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
        'review': review,
        'scope_note': 'Saved advisory review and submitted evidence snapshot. Not a sign-off approval, provider model-version attestation, or immutable external audit record.',
    }
    content = json.dumps(jsonable_encoder(bundle), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(content) > MAX_EXPORT_BYTES:
        raise HTTPException(413, '검토 내보내기가 2 MiB를 초과합니다.')
    return Response(content, media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="run-{run_id}-review-{review_id}.json"',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


@router.post('/runs/{run_id}/agent-reviews', status_code=201)
async def create_review(run_id: int, payload: ReviewRequest, response: Response, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    key = str(payload.request_key)
    def existing():
        return db.scalar(select(RunAgentReview).where(RunAgentReview.run_id == run_id, RunAgentReview.request_key == key))
    previous = existing()
    if previous is not None:
        response.status_code = 200
        return detail(previous)
    role, data = snapshot(run)
    user = db.info.get('user')
    row = RunAgentReview(run_id=run_id, request_key=key, requester_user_id=user.id if user else None,
                         requester=user.username if user else 'local', role=role.id, input_snapshot=data,
                         review_policy=REVIEW_GUIDANCE + '\n' + role.system_prompt,
                         model_alias=Settings.from_env().model[:200])
    db.add(row)
    try:
        db.commit()  # Persist receipt and release DB transaction before waiting for the provider.
    except IntegrityError:
        db.rollback()
        previous = existing()
        if previous is None:
            raise
        response.status_code = 200
        return detail(previous)
    try:
        outcome = await _run_role(role, data, session_id=f'run-review:{row.id}')
        if len(json.dumps(outcome, ensure_ascii=False).encode()) > 1024 * 1024:
            outcome = {'available': False, 'review': None, 'error': 'review_too_large'}
    except asyncio.CancelledError:
        finish_review(db, row.id, {'available': False, 'review': None, 'error': 'review_interrupted'})
        raise
    except Exception:
        outcome = {'available': False, 'review': None, 'error': 'review_unavailable'}
    return detail(finish_review(db, row.id, outcome))


@router.post('/runs/{run_id}/agent-reviews/{review_id}/close')
def close_review(run_id: int, review_id: int, payload: CloseReviewRequest, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    require_project(db, run.project_id, 'owner')
    row = db.scalar(select(RunAgentReview).where(RunAgentReview.id == review_id, RunAgentReview.run_id == run_id))
    if row is None:
        raise HTTPException(404, 'review not found')
    now = datetime.now(timezone.utc)
    user = db.info.get('user')
    outcome = {'available': False, 'review': None, 'error': 'review_closed_by_operator',
               'closure': {'actor': user.username if user else 'local', 'actor_user_id': user.id if user else None,
                           'reason': payload.reason, 'closed_at': now.isoformat()}}
    changed = db.execute(update(RunAgentReview).where(
        RunAgentReview.id == review_id, RunAgentReview.run_id == run_id,
        RunAgentReview.status == 'running', RunAgentReview.created_at <= now - COMPLETION_NOTICE_AFTER,
    ).values(status='failed', outcome=outcome).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '접수 후 2분 이상 지난 미완료 검토만 종결할 수 있습니다. 최신 상태를 확인하세요.')
    db.commit()
    db.refresh(row)
    return detail(row)
