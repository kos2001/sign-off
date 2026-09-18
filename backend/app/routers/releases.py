import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from ..auth import require_project
from ..db import get_db
from ..models import SignoffReleaseDecision, Stage
from ..schemas import (
    SignoffReleaseDecisionCreate,
    SignoffReleaseDecisionOut,
    SignoffReleaseDecisionPage,
    SignoffReleaseReviewOut,
)
from .runs import export_gate, export_signoff_package

router = APIRouter(prefix='/projects/{project_id}/signoff-releases', tags=['signoff-releases'])


def gate_digest(gate: dict) -> str:
    canonical = json.dumps(jsonable_encoder(gate), ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def evidence_digest(bundle: dict) -> str:
    state = jsonable_encoder({'gate': bundle['gate'], 'runs': bundle['runs']})
    # The ZIP-only path points at a file whose identity is already represented
    # by source_sha256. Exclude it so the archived manifest and lightweight
    # current-state export share one deterministic evidence contract.
    for run in state['runs']:
        evidence = run.get('evidence')
        if isinstance(evidence, dict):
            evidence.pop('file', None)
    canonical = json.dumps(state,
                           ensure_ascii=False, allow_nan=False, sort_keys=True,
                           separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


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
    # Version 2 decisions bind the displayed gate snapshot directly. Records
    # created before this field existed retain their original digest contract.
    if record.gate_snapshot_sha256 is not None:
        payload['gate_snapshot_sha256'] = record.gate_snapshot_sha256
    if record.evidence_snapshot_sha256 is not None:
        payload['evidence_snapshot_sha256'] = record.evidence_snapshot_sha256
    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def release_out(record: SignoffReleaseDecision, *, current_evidence_sha256: str,
                latest_decision_id: int, verify_evidence_snapshot: bool = True) -> SignoffReleaseDecisionOut:
    if not record.decision_sha256 or decision_digest(record) != record.decision_sha256:
        raise HTTPException(409, '보관된 사인오프 결정 무결성 검증에 실패했습니다.')
    gate = record.gate_snapshot or record.manifest['gate']
    if record.gate_snapshot_sha256 is not None and gate_digest(gate) != record.gate_snapshot_sha256:
        raise HTTPException(409, '보관된 게이트 스냅샷 무결성 검증에 실패했습니다.')
    if (verify_evidence_snapshot and record.evidence_snapshot_sha256 is not None
            and evidence_digest(record.manifest) != record.evidence_snapshot_sha256):
        raise HTTPException(409, '보관된 근거 스냅샷 무결성 검증에 실패했습니다.')
    lifecycle = ('superseded_by_decision' if record.id != latest_decision_id else
                 'legacy_unbound' if record.evidence_snapshot_sha256 is None else
                 'current' if record.evidence_snapshot_sha256 == current_evidence_sha256 else
                 'evidence_changed')
    return SignoffReleaseDecisionOut(
        id=record.id, project_id=record.project_id, stage=record.stage,
        decision=record.decision, reason=record.reason,
        design_revision=record.design_revision, decided_by=record.decided_by,
        decided_by_user_id=record.decided_by_user_id,
        manifest_sha256=record.manifest_sha256,
        package_sha256=record.package_sha256, decision_sha256=record.decision_sha256,
        gate_snapshot_sha256=record.gate_snapshot_sha256,
        evidence_snapshot_sha256=record.evidence_snapshot_sha256, lifecycle_status=lifecycle,
        byte_length=record.byte_length,
        created_at=record.created_at, gate=gate,
    )


def current_evidence_sha256(project_id: int, stage, db: Session) -> str:
    bundle = json.loads(bytes(export_gate(project_id, stage, db).body))
    return evidence_digest(bundle)


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
    if payload.decision == 'approved':
        target = gate.get('target_revision', {})
        target_revision = target.get('design_revision')
        common_revision = gate.get('revision_check', {}).get('common_revision')
        if not target_revision:
            raise HTTPException(409, '승인 전에 이 스테이지의 릴리스 후보 리비전을 고정하세요.')
        if common_revision != target_revision:
            raise HTTPException(409, '게이트 근거 리비전이 고정된 릴리스 후보와 일치하지 않습니다.')
        snapshot_sha256 = evidence_digest(manifest)
        if payload.expected_evidence_sha256 is None:
            raise HTTPException(409, '승인 전에 현재 근거 스냅샷을 검토하세요.')
        if payload.expected_evidence_sha256 != snapshot_sha256:
            raise HTTPException(409, '검토 후 사인오프 근거가 변경되었습니다. 현재 근거를 다시 검토하세요.')

    user = db.info.get('user')
    record = SignoffReleaseDecision(
        project_id=project_id, stage=payload.stage, decision=payload.decision,
        reason=payload.reason, design_revision=gate['revision_check']['common_revision'],
        decided_by=user.username if user else 'local-operator',
        decided_by_user_id=user.id if user else None,
        gate_snapshot=gate, gate_snapshot_sha256=gate_digest(gate),
        evidence_snapshot_sha256=evidence_digest(manifest), manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        package_sha256=hashlib.sha256(content).hexdigest(),
        package_bytes=content, byte_length=len(content), created_at=datetime.now(timezone.utc),
    )
    record.decision_sha256 = decision_digest(record)
    db.add(record)
    db.commit()
    db.refresh(record)
    return release_out(record, current_evidence_sha256=record.evidence_snapshot_sha256,
                       latest_decision_id=record.id)


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
    latest = dict(db.execute(select(SignoffReleaseDecision.stage, func.max(SignoffReleaseDecision.id))
                             .where(SignoffReleaseDecision.project_id == project_id)
                             .group_by(SignoffReleaseDecision.stage)).all())
    current = {stage: current_evidence_sha256(project_id, stage, db) for stage in {row.stage for row in rows}}
    return SignoffReleaseDecisionPage(
        items=[release_out(row, current_evidence_sha256=current[row.stage],
                           latest_decision_id=latest[row.stage], verify_evidence_snapshot=False) for row in rows],
        next_before_id=rows[-1].id if more else None,
    )


@router.get('/review', response_model=SignoffReleaseReviewOut)
def review_release_evidence(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    require_project(db, project_id, 'approver')
    response = export_gate(project_id, stage, db)
    bundle = json.loads(bytes(response.body))
    return SignoffReleaseReviewOut(
        stage=stage,
        evidence_snapshot_sha256=evidence_digest(bundle),
        captured_at=datetime.now(timezone.utc),
        gate=bundle['gate'],
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
    latest_id = db.scalar(select(func.max(SignoffReleaseDecision.id)).where(
        SignoffReleaseDecision.project_id == project_id,
        SignoffReleaseDecision.stage == record.stage,
    ))
    return release_out(record, current_evidence_sha256=current_evidence_sha256(project_id, record.stage, db),
                       latest_decision_id=latest_id)


@router.get('/{release_id}/package')
def download_release_package(project_id: int, release_id: int, db: Session = Depends(get_db)):
    require_project(db, project_id)
    record = get_release(project_id, release_id, db)
    if hashlib.sha256(record.package_bytes).hexdigest() != record.package_sha256:
        raise HTTPException(409, '보관된 사인오프 패키지 무결성 검증에 실패했습니다.')
    if not record.decision_sha256 or decision_digest(record) != record.decision_sha256:
        raise HTTPException(409, '보관된 사인오프 결정 무결성 검증에 실패했습니다.')
    gate = record.gate_snapshot or record.manifest['gate']
    if record.gate_snapshot_sha256 is not None and gate_digest(gate) != record.gate_snapshot_sha256:
        raise HTTPException(409, '보관된 게이트 스냅샷 무결성 검증에 실패했습니다.')
    if (record.evidence_snapshot_sha256 is not None
            and evidence_digest(record.manifest) != record.evidence_snapshot_sha256):
        raise HTTPException(409, '보관된 근거 스냅샷 무결성 검증에 실패했습니다.')
    return Response(record.package_bytes, media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="project-{project_id}-{record.stage.value}-decision-{record.id}.zip"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Signoff-Manifest-SHA256': record.manifest_sha256,
        'X-Signoff-Package-SHA256': record.package_sha256,
        'X-Signoff-Decision-SHA256': record.decision_sha256,
    })
