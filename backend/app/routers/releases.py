import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from ..auth import require_project
from ..db import get_db
from ..models import SignoffReleaseDecision
from ..schemas import (
    SignoffReleaseDecisionCreate,
    SignoffReleaseDecisionOut,
    SignoffReleaseDecisionPage,
)
from .runs import export_signoff_package

router = APIRouter(prefix='/projects/{project_id}/signoff-releases', tags=['signoff-releases'])


def decision_digest(record: SignoffReleaseDecision) -> str:
    created_at = record.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    payload = {
        'project_id': record.project_id, 'stage': record.stage.value,
        'decision': record.decision, 'reason': record.reason,
        'design_revision': record.design_revision, 'decided_by': record.decided_by,
        'decided_by_user_id': record.decided_by_user_id,
        'manifest_sha256': record.manifest_sha256,
        'package_sha256': record.package_sha256,
        'byte_length': record.byte_length,
        'created_at': created_at.astimezone(timezone.utc).isoformat(),
    }
    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def release_out(record: SignoffReleaseDecision) -> SignoffReleaseDecisionOut:
    if not record.decision_sha256 or decision_digest(record) != record.decision_sha256:
        raise HTTPException(409, '보관된 사인오프 결정 무결성 검증에 실패했습니다.')
    return SignoffReleaseDecisionOut(
        id=record.id, project_id=record.project_id, stage=record.stage,
        decision=record.decision, reason=record.reason,
        design_revision=record.design_revision, decided_by=record.decided_by,
        decided_by_user_id=record.decided_by_user_id,
        manifest_sha256=record.manifest_sha256,
        package_sha256=record.package_sha256, decision_sha256=record.decision_sha256,
        byte_length=record.byte_length,
        created_at=record.created_at, gate=record.gate_snapshot or record.manifest['gate'],
    )


@router.post('', response_model=SignoffReleaseDecisionOut, status_code=201)
def create_release_decision(
    project_id: int,
    payload: SignoffReleaseDecisionCreate,
    db: Session = Depends(get_db),
):
    require_project(db, project_id, 'approver')
    package = export_signoff_package(project_id, payload.stage, db)
    content = bytes(package.body)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        manifest_bytes = archive.read('manifest.json')
    manifest = json.loads(manifest_bytes)
    gate = manifest['gate']
    if payload.decision == 'approved' and not gate['ready']:
        raise HTTPException(409, '차단된 게이트는 승인할 수 없습니다. 차단 결정을 기록하거나 근거를 보완하세요.')

    user = db.info.get('user')
    record = SignoffReleaseDecision(
        project_id=project_id, stage=payload.stage, decision=payload.decision,
        reason=payload.reason, design_revision=gate['revision_check']['common_revision'],
        decided_by=user.username if user else 'local-operator',
        decided_by_user_id=user.id if user else None,
        gate_snapshot=gate, manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        package_sha256=hashlib.sha256(content).hexdigest(),
        package_bytes=content, byte_length=len(content), created_at=datetime.now(timezone.utc),
    )
    record.decision_sha256 = decision_digest(record)
    db.add(record)
    db.commit()
    db.refresh(record)
    return release_out(record)


@router.get('', response_model=SignoffReleaseDecisionPage)
def list_release_decisions(
    project_id: int,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    require_project(db, project_id)
    statement = select(SignoffReleaseDecision).where(SignoffReleaseDecision.project_id == project_id).options(
        defer(SignoffReleaseDecision.package_bytes), defer(SignoffReleaseDecision.manifest),
    )
    if before_id is not None:
        statement = statement.where(SignoffReleaseDecision.id < before_id)
    rows = list(db.scalars(statement.order_by(SignoffReleaseDecision.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return SignoffReleaseDecisionPage(
        items=[release_out(row) for row in rows],
        next_before_id=rows[-1].id if more else None,
    )


def get_release(project_id: int, release_id: int, db: Session) -> SignoffReleaseDecision:
    record = db.get(SignoffReleaseDecision, release_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(404, 'signoff release decision not found')
    return record


@router.get('/{release_id}', response_model=SignoffReleaseDecisionOut)
def read_release_decision(project_id: int, release_id: int, db: Session = Depends(get_db)):
    require_project(db, project_id)
    record = db.scalar(select(SignoffReleaseDecision).where(
        SignoffReleaseDecision.id == release_id,
        SignoffReleaseDecision.project_id == project_id,
    ).options(defer(SignoffReleaseDecision.package_bytes), defer(SignoffReleaseDecision.manifest)))
    if record is None:
        raise HTTPException(404, 'signoff release decision not found')
    return release_out(record)


@router.get('/{release_id}/package')
def download_release_package(project_id: int, release_id: int, db: Session = Depends(get_db)):
    require_project(db, project_id)
    record = get_release(project_id, release_id, db)
    if hashlib.sha256(record.package_bytes).hexdigest() != record.package_sha256:
        raise HTTPException(409, '보관된 사인오프 패키지 무결성 검증에 실패했습니다.')
    if not record.decision_sha256 or decision_digest(record) != record.decision_sha256:
        raise HTTPException(409, '보관된 사인오프 결정 무결성 검증에 실패했습니다.')
    return Response(record.package_bytes, media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="project-{project_id}-{record.stage.value}-decision-{record.id}.zip"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Signoff-Manifest-SHA256': record.manifest_sha256,
        'X-Signoff-Package-SHA256': record.package_sha256,
        'X-Signoff-Decision-SHA256': record.decision_sha256,
    })
