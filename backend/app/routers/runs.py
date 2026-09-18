import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update, func, or_
from sqlalchemy.orm import Session, selectinload, joinedload

from ..db import get_db
from ..models import Domain, RunArtifact, RunEvidence, Severity, SignoffRun, Stage, Violation, ViolationStatus, Waiver, ViolationEvent
from ..schemas import (
    RunCreate,
    RunOut,
    RunEvidenceOut,
    RunUpdate,
    ViolationCreate,
    ViolationOut,
    ViolationTransition,
    ViolationEventOut,
    WaiverCreate,
)
from ..services.stages import evaluate_gate
from ..services.rtl.artifacts import NetlistArtifact, StructureArtifact, parse_structure, netlist_metadata_only
from .projects import get_project_or_404

router = APIRouter(tags=["signoff-runs"])
MAX_GATE_EXPORT_BYTES = 8 * 1024 * 1024


def get_run_or_404(run_id: int, db: Session) -> SignoffRun:
    run = db.get(SignoffRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=201)
def create_run(project_id: int, payload: RunCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    run = SignoffRun(project_id=project_id, **payload.model_dump())
    run.evidence = RunEvidence(source="manual")
    db.add(run)
    db.commit()
    return run


@router.get("/projects/{project_id}/runs", response_model=list[RunOut])
def list_runs(
    project_id: int,
    domain: Domain | None = None,
    stage: Stage | None = None,
    db: Session = Depends(get_db),
):
    get_project_or_404(project_id, db)
    query = select(SignoffRun).where(SignoffRun.project_id == project_id)
    if domain is not None:
        query = query.where(SignoffRun.domain == domain)
    if stage is not None:
        query = query.where(SignoffRun.stage == stage)
    return db.scalars(query.options(selectinload(SignoffRun.evidence)).order_by(SignoffRun.id)).all()


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    return get_run_or_404(run_id, db)


@router.patch("/runs/{run_id}", response_model=RunOut)
def update_run(run_id: int, payload: RunUpdate, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    if run.result_locked:
        raise HTTPException(status_code=409, detail="captured analysis result is read-only; rerun the analysis")
    run.status = payload.status
    if payload.metrics is not None:
        run.metrics = payload.metrics
    db.commit()
    return run


@router.get("/runs/{run_id}/evidence", response_model=RunEvidenceOut)
def run_evidence(run_id: int, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    if run.evidence is None:
        raise HTTPException(status_code=404, detail="no captured evidence for this legacy run")
    evidence = run.evidence
    if evidence.source != 'opensta_execution':
        return evidence
    # Older records may have embedded input bodies. Routine metadata never
    # returns them; exact content is available through the artifact endpoint.
    result = copy.deepcopy(evidence.result)
    artifacts = result.get('input_artifacts')
    if isinstance(artifacts, dict):
        for value in artifacts.values():
            if isinstance(value, dict):
                value.pop('text', None)
    return RunEvidenceOut(run_id=evidence.run_id, source=evidence.source, source_text=evidence.source_text,
                          source_sha256=evidence.source_sha256, design_revision=evidence.design_revision,
                          result=result, created_at=evidence.created_at)


@router.get('/runs/{run_id}/evidence/artifacts/{kind}')
def export_run_artifact(run_id: int, kind: Literal['netlist', 'liberty', 'sdc', 'spef'], db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    if run.evidence_source != 'opensta_execution':
        raise HTTPException(409, '이 런에는 OpenSTA 실행 입력 아티팩트가 없습니다.')
    artifact = db.scalar(select(RunArtifact).where(RunArtifact.run_id == run.id, RunArtifact.kind == kind))
    if artifact is None:
        # Compatibility for runs created before input artifacts were split out.
        value = (run.evidence.result.get('input_artifacts', {}).get(kind, {}) if run.evidence else {})
        if not isinstance(value, dict) or not isinstance(value.get('text'), str):
            raise HTTPException(404, '입력 아티팩트를 찾을 수 없습니다.')
        content, digest, byte_length = value['text'], value.get('sha256'), value.get('byte_length')
    else:
        content, digest, byte_length = artifact.content_text, artifact.sha256, artifact.byte_length
    encoded = content.encode('utf-8')
    if hashlib.sha256(encoded).hexdigest() != digest or len(encoded) != byte_length:
        raise HTTPException(409, '저장된 입력 아티팩트의 무결성을 확인할 수 없습니다.')
    extension = {'netlist': 'v', 'liberty': 'lib', 'sdc': 'sdc', 'spef': 'spef'}[kind]
    return Response(encoded, media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="run-{run_id}-{kind}.{extension}"',
        'X-Artifact-SHA256': digest, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    })


@router.get('/runs/{run_id}/evidence/structure')
def run_structure(run_id: int, response: Response, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    evidence = run.evidence
    if evidence is None:
        raise HTTPException(404, 'no captured evidence for this legacy run')
    result = evidence.result
    if evidence.source != 'rtl_ladder' or not isinstance(result, dict) or result.get('structure') is None:
        raise HTTPException(409, '이 런에는 보존된 합성 구조가 없습니다.')
    try:
        if evidence.source_text is None or hashlib.sha256(evidence.source_text.encode()).hexdigest() != evidence.source_sha256:
            raise ValueError('source integrity mismatch')
        artifact = StructureArtifact.model_validate(result['structure'])
        design = parse_structure(artifact.text)
        synthesis = [stage for stage in result.get('stages', []) if stage.get('name') == 'synthesize']
        if len(synthesis) != 1 or synthesis[0].get('status') != 'pass' or result.get('structure_error') is not None or result.get('module') not in design['modules']:
            raise ValueError('structure does not match synthesis')
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, '합성 구조의 무결성 또는 실행 결과를 확인할 수 없습니다.')
    response.headers['Cache-Control'] = 'no-store'
    return {'run_id': run.id, 'project_id': run.project_id, 'top_module': result['module'],
            'source_sha256': evidence.source_sha256, 'structure_sha256': artifact.sha256,
            'design': design}


@router.get('/runs/{run_id}/evidence/netlist')
def export_netlist(run_id: int, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    evidence = run.evidence
    if evidence is None:
        raise HTTPException(404, 'no captured evidence for this legacy run')
    result = evidence.result
    if evidence.source != 'rtl_ladder' or not isinstance(result, dict) or result.get('netlist') is None:
        raise HTTPException(409, '이 런에는 보존된 합성 넷리스트가 없습니다.')
    try:
        if evidence.source_text is None or hashlib.sha256(evidence.source_text.encode('utf-8')).hexdigest() != evidence.source_sha256:
            raise ValueError('source integrity mismatch')
        artifact = NetlistArtifact.model_validate(result['netlist'])
        synthesis = [stage for stage in result.get('stages', []) if stage.get('name') == 'synthesize']
        if len(synthesis) != 1 or synthesis[0].get('status') != 'pass':
            raise ValueError('synthesis did not pass')
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, '넷리스트의 무결성 또는 합성 결과를 확인할 수 없습니다.')
    return Response(artifact.text.encode('utf-8'), media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="run-{run_id}-netlist.v"',
        'X-Artifact-SHA256': artifact.sha256, 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


@router.get('/runs/{run_id}/evidence/source')
def export_evidence_source(run_id: int, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    evidence = run.evidence
    if evidence is None:
        raise HTTPException(404, 'no captured evidence for this legacy run')
    extensions = {'opensta_report': 'json', 'opensta_execution': 'json', 'commercial_sta_report': 'json',
                  'commercial_drc_report': 'json', 'commercial_emir_report': 'json',
                  'rtl_ladder': 'sv', 'klayout_report': 'lyrdb'}
    if evidence.source not in extensions or evidence.source_text is None:
        raise HTTPException(409, '이 런에는 다운로드할 원본 입력이 없습니다.')
    content = evidence.source_text.encode('utf-8')
    digest = hashlib.sha256(content).hexdigest()
    if digest != evidence.source_sha256:
        raise HTTPException(409, '저장된 원본과 SHA-256이 일치하지 않습니다. 원본 근거를 확인하세요.')
    return Response(content, media_type='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="run-{run_id}-source.{extensions[evidence.source]}"',
        'X-Source-SHA256': digest,
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


@router.post(
    "/runs/{run_id}/violations", response_model=list[ViolationOut], status_code=201
)
def add_violations(
    run_id: int, payload: list[ViolationCreate], db: Session = Depends(get_db)
):
    run = get_run_or_404(run_id, db)
    if run.result_locked:
        raise HTTPException(status_code=409, detail="captured analysis findings are read-only; rerun the analysis")
    violations = [Violation(run_id=run.id, **v.model_dump()) for v in payload]
    db.add_all(violations)
    db.commit()
    return violations


@router.get("/runs/{run_id}/violations", response_model=list[ViolationOut])
def list_violations(
    run_id: int,
    status: ViolationStatus | None = None,
    db: Session = Depends(get_db),
):
    get_run_or_404(run_id, db)
    query = (
        select(Violation)
        .where(Violation.run_id == run_id)
        .options(selectinload(Violation.waiver))
    )
    if status is not None:
        query = query.where(Violation.status == status)
    return db.scalars(query.order_by(Violation.id)).all()


@router.get("/runs/{run_id}/violations/page")
def page_run_violations(
    run_id: int,
    q: str = Query(default="", max_length=200),
    status: ViolationStatus | None = None,
    severity: Severity | None = None,
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    get_run_or_404(run_id, db)
    filters = [Violation.run_id == run_id]
    if status is not None:
        filters.append(Violation.status == status)
    if severity is not None:
        filters.append(Violation.severity == severity)
    if q:
        filters.append(or_(
            Violation.check_name.icontains(q, autoescape=True),
            func.coalesce(Violation.location, "").icontains(q, autoescape=True),
            func.coalesce(Violation.description, "").icontains(q, autoescape=True),
        ))
    total = db.scalar(select(func.count()).select_from(Violation).where(*filters)) or 0
    items = db.scalars(
        select(Violation).where(*filters).options(selectinload(Violation.waiver))
        .order_by(Violation.id).offset(offset).limit(limit)
    ).all()
    status_counts = {item.value: 0 for item in ViolationStatus}
    severity_counts = {item.value: 0 for item in Severity}
    for value, count in db.execute(
        select(Violation.status, func.count()).where(Violation.run_id == run_id).group_by(Violation.status)
    ):
        status_counts[value.value] = count
    for value, count in db.execute(
        select(Violation.severity, func.count()).where(Violation.run_id == run_id).group_by(Violation.severity)
    ):
        severity_counts[value.value] = count
    return {
        "total": total,
        "run_total": sum(status_counts.values()),
        "offset": offset,
        "limit": limit,
        "status_counts": status_counts,
        "severity_counts": severity_counts,
        "items": [ViolationOut.model_validate(item) for item in items],
    }


def transition_violation(violation_id: int, payload: ViolationTransition, db: Session):
    violation = db.get(Violation, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="violation not found")
    user = db.info.get("user")
    actor = user.username if user else payload.actor
    actor_user_id = user.id if user else None
    allowed = {
        ViolationStatus.open: {ViolationStatus.fixed, ViolationStatus.waived},
        ViolationStatus.fixed: {ViolationStatus.open},
        ViolationStatus.waived: {ViolationStatus.open},
    }
    if payload.status not in allowed[payload.expected_status]:
        raise HTTPException(status_code=409, detail="invalid status transition")
    # The row version also detects open -> closed -> open (ABA) races.
    result = db.execute(
        update(Violation)
        .where(
            Violation.id == violation_id,
            Violation.status == payload.expected_status,
            Violation.version == payload.expected_version,
        )
        .values(status=payload.status, version=Violation.version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="violation changed; refresh and review again")
    if payload.status == ViolationStatus.waived:
        violation.waiver = Waiver(reason=payload.reason, approved_by=actor, approved_user_id=actor_user_id)
    elif violation.waiver is not None:
        # Preserve evidence from waivers created before event tracking existed.
        recorded = db.scalar(select(ViolationEvent.id).where(
            ViolationEvent.violation_id == violation_id,
            ViolationEvent.to_status == ViolationStatus.waived,
        ).limit(1))
        if recorded is None:
            db.add(ViolationEvent(
                violation_id=violation_id,
                from_status=ViolationStatus.open,
                to_status=ViolationStatus.waived,
                actor=violation.waiver.approved_by,
                actor_user_id=violation.waiver.approved_user_id,
                reason=violation.waiver.reason,
                created_at=violation.waiver.created_at,
            ))
        violation.waiver = None
    db.add(ViolationEvent(
        violation_id=violation_id,
        from_status=payload.expected_status,
        to_status=payload.status,
        actor=actor,
        actor_user_id=actor_user_id,
        reason=payload.reason,
    ))
    db.commit()
    db.refresh(violation)
    return violation


@router.patch("/violations/{violation_id}", response_model=ViolationOut)
def update_violation(
    violation_id: int, payload: ViolationTransition, db: Session = Depends(get_db)
):
    return transition_violation(violation_id, payload, db)


@router.get("/violations/{violation_id}", response_model=ViolationOut)
def get_violation(violation_id: int, db: Session = Depends(get_db)):
    violation = db.get(Violation, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="violation not found")
    return violation


@router.get("/violations/{violation_id}/history", response_model=list[ViolationEventOut])
def violation_history(violation_id: int, db: Session = Depends(get_db)):
    if db.get(Violation, violation_id) is None:
        raise HTTPException(status_code=404, detail="violation not found")
    return db.scalars(select(ViolationEvent).where(
        ViolationEvent.violation_id == violation_id
    ).order_by(ViolationEvent.id)).all()


@router.get('/violations/{violation_id}/history/export')
def export_violation_history(violation_id: int, db: Session = Depends(get_db)):
    from ..services.violation_history_export import export_history
    return export_history(db, violation_id)


@router.get('/violations/{violation_id}/history/page')
def violation_history_page(
    violation_id: int,
    q: str = Query(default='', max_length=200),
    to_status: ViolationStatus | None = None,
    before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
    snapshot_max_id: int | None = Query(default=None, ge=0, le=9223372036854775807),
    limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db),
):
    if db.get(Violation, violation_id) is None:
        raise HTTPException(404, 'violation not found')
    if before_id is not None and snapshot_max_id is None:
        raise HTTPException(422, 'snapshot_max_id is required when continuing history')
    scope = ViolationEvent.violation_id == violation_id
    if snapshot_max_id is None:
        snapshot_max_id = db.scalar(select(func.max(ViolationEvent.id)).where(scope)) or 0
    filters = [scope, ViolationEvent.id <= snapshot_max_id]
    if q.strip():
        filters.append(or_(ViolationEvent.actor.icontains(q.strip(), autoescape=True),
                           ViolationEvent.reason.icontains(q.strip(), autoescape=True)))
    if to_status is not None:
        filters.append(ViolationEvent.to_status == to_status)
    total = db.scalar(select(func.count(ViolationEvent.id)).where(*filters))
    if before_id is not None:
        filters.append(ViolationEvent.id < before_id)
    rows = db.scalars(select(ViolationEvent).where(*filters).order_by(ViolationEvent.id.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    items = rows[:limit]
    return {'items': [ViolationEventOut.model_validate(item) for item in items], 'total': total,
            'snapshot_max_id': snapshot_max_id, 'next_before_id': items[-1].id if more else None}


@router.post("/violations/{violation_id}/waiver", response_model=ViolationOut, status_code=201)
def waive_violation(
    violation_id: int, payload: WaiverCreate, db: Session = Depends(get_db)
):
    return transition_violation(violation_id, ViolationTransition(
        expected_status=ViolationStatus.open,
        expected_version=payload.expected_version,
        status=ViolationStatus.waived,
        actor=payload.approved_by,
        reason=payload.reason,
    ), db)


def gate_runs(project_id: int, stage: Stage, db: Session):
    # One statement captures the selected runs, evidence and violations together.
    # Do not read all historical source texts on every five-second gate poll.
    ranked = select(SignoffRun.id, func.row_number().over(
        partition_by=SignoffRun.domain,
        order_by=(SignoffRun.created_at.desc(), SignoffRun.id.desc()),
    ).label('position')).where(SignoffRun.project_id == project_id, SignoffRun.stage == stage).subquery()
    return list(db.scalars(
        select(SignoffRun)
        .where(SignoffRun.id.in_(select(ranked.c.id).where(ranked.c.position == 1)))
        .options(joinedload(SignoffRun.violations).joinedload(Violation.waiver),
                 joinedload(SignoffRun.evidence).defer(RunEvidence.source_text, raiseload=True))
        .execution_options(populate_existing=True)
    ).unique())


@router.get("/projects/{project_id}/signoff-status")
def signoff_status(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    return evaluate_gate(gate_runs(project_id, stage, db), stage)


@router.get('/projects/{project_id}/signoff-status/export')
def export_gate(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    runs = gate_runs(project_id, stage, db)
    gate = evaluate_gate(runs, stage)
    selected_ids = {domain.get('run_id') for domain in gate['domains']}
    selected = sorted((run for run in runs if run.id in selected_ids), key=lambda run: run.id)
    if sum(len(run.violations) for run in selected) > 10000:
        raise HTTPException(413, '게이트 근거의 위반이 10,000건을 초과합니다.')
    records = []
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    for run in selected:
        evidence = run.evidence
        records.append({
            'id': run.id, 'domain': run.domain.value, 'stage': run.stage.value, 'tool': run.tool,
            'status': run.status.value, 'created_at': utc(run.created_at), 'metrics': run.metrics,
            'evidence': None if evidence is None else {
                'source': evidence.source, 'source_sha256': evidence.source_sha256,
                'design_revision': evidence.design_revision, 'result': netlist_metadata_only(evidence.result),
            },
            'violations': [{
                'id': violation.id, 'check_name': violation.check_name, 'severity': violation.severity.value,
                'status': violation.status.value, 'version': violation.version,
                'location': violation.location, 'description': violation.description,
                'waiver': None if violation.waiver is None else {
                    'reason': violation.waiver.reason, 'approved_by': violation.waiver.approved_by,
                    'approved_user_id': violation.waiver.approved_user_id,
                    'created_at': utc(violation.waiver.created_at),
                },
            } for violation in sorted(run.violations, key=lambda violation: violation.id)],
        })
    bundle = {'format': 'signoff/stage-gate-export/v1', 'project_id': project_id,
              'exported_at': datetime.now(timezone.utc).isoformat(), 'gate': gate, 'runs': records,
              'scope_note': 'Current stage gate and selected latest runs captured together. Includes stored results and current violation/waiver states. Excludes raw source/netlist files, change history and AI opinions. Not an approval, tool authenticity proof or immutable audit record.'}
    content = json.dumps(jsonable_encoder(bundle), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(content) > MAX_GATE_EXPORT_BYTES:
        raise HTTPException(413, '게이트 근거 내보내기가 8 MiB를 초과합니다.')
    return Response(content, media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="project-{project_id}-{stage.value}-gate.json"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    })
