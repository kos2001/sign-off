import copy
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update, func, or_
from sqlalchemy.orm import Session, selectinload, joinedload

from ..db import get_db
from ..models import Domain, RunArtifact, RunEvidence, RunStatus, Severity, SignoffRun, Stage, Violation, ViolationStatus, Waiver, ViolationEvent
from ..schemas import (
    RunCreate,
    RunOut,
    RunPageOut,
    RunRevisionPage,
    RevisionCoverageOut,
    RunEvidenceOut,
    RunUpdate,
    ViolationCreate,
    ViolationOut,
    ViolationTransition,
    ViolationEventOut,
    WaiverCreate,
)
from ..services.stages import evaluate_gate, resolve_signoff_plan, resolve_target_revision
from ..services.sta_scenario_plans import resolve_sta_scenario_plan
from ..services.rtl.artifacts import NetlistArtifact, StructureArtifact, parse_structure, netlist_metadata_only
from .projects import get_project_or_404

router = APIRouter(tags=["signoff-runs"])
MAX_GATE_EXPORT_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_LEGACY_RUN_LIST = 1000


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
    rows = db.scalars(query.options(selectinload(SignoffRun.evidence).defer(RunEvidence.source_text))
                      .order_by(SignoffRun.id).limit(MAX_LEGACY_RUN_LIST + 1)).all()
    if len(rows) > MAX_LEGACY_RUN_LIST:
        raise HTTPException(413, f'run history exceeds the legacy list limit; use /projects/{project_id}/runs/page')
    return rows


@router.get('/projects/{project_id}/runs/page', response_model=RunPageOut)
def run_page(project_id: int, domain: Domain | None = None, stage: Stage | None = None,
             status: RunStatus | None = None, q: str | None = Query(None, min_length=1, max_length=80),
             revision: str | None = Query(None, min_length=1, max_length=160),
             revision_scope: Literal['all', 'labeled', 'unlabeled'] = 'all',
             before_id: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=100),
             db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filters = [SignoffRun.project_id == project_id]
    if domain is not None:
        filters.append(SignoffRun.domain == domain)
    if stage is not None:
        filters.append(SignoffRun.stage == stage)
    if status is not None:
        filters.append(SignoffRun.status == status)
    if q is not None:
        query = q.strip()
        if not query:
            raise HTTPException(422, 'q must not be blank')
        filters.append(func.lower(SignoffRun.tool).contains(query.casefold(), autoescape=True))
    if revision is not None:
        selected_revision = revision.strip()
        if not selected_revision:
            raise HTTPException(422, 'revision must not be blank')
        if revision_scope == 'unlabeled':
            raise HTTPException(422, 'revision cannot be combined with unlabeled scope')
        filters.append(SignoffRun.evidence.has(RunEvidence.design_revision == selected_revision))
    elif revision_scope == 'labeled':
        filters.append(SignoffRun.evidence.has(
            RunEvidence.design_revision.is_not(None) & (RunEvidence.design_revision != '')))
    elif revision_scope == 'unlabeled':
        filters.append(~SignoffRun.evidence.has(
            RunEvidence.design_revision.is_not(None) & (RunEvidence.design_revision != '')))
    page_filters = [*filters]
    if before_id is not None:
        page_filters.append(SignoffRun.id < before_id)
    rows = db.scalars(select(SignoffRun).where(*page_filters)
                      .options(selectinload(SignoffRun.evidence).defer(RunEvidence.source_text))
                      .order_by(SignoffRun.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    counts = {status.value: 0 for status in RunStatus}
    for status, count in db.execute(select(SignoffRun.status, func.count()).where(*filters)
                                    .group_by(SignoffRun.status)):
        counts[status.value] = count
    total = sum(counts.values())
    return {'items': items, 'total': total, 'status_counts': counts,
            'next_before_id': items[-1].id if len(rows) > limit else None}


@router.get('/projects/{project_id}/run-revisions', response_model=RunRevisionPage)
def run_revisions(project_id: int, q: str | None = Query(None, min_length=1, max_length=160),
                  offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100),
                  db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filters = [SignoffRun.project_id == project_id, RunEvidence.design_revision.is_not(None),
               RunEvidence.design_revision != '']
    if q is not None:
        search = q.strip()
        if not search:
            raise HTTPException(422, 'q must not be blank')
        filters.append(func.lower(RunEvidence.design_revision).contains(search.casefold(), autoescape=True))
    grouped = (select(RunEvidence.design_revision.label('design_revision'),
                      func.count(SignoffRun.id).label('run_count'),
                      func.max(SignoffRun.id).label('latest_run_id'))
               .join(SignoffRun, SignoffRun.id == RunEvidence.run_id).where(*filters)
               .group_by(RunEvidence.design_revision))
    total = db.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    rows = db.execute(grouped.order_by(func.max(SignoffRun.id).desc())
                      .offset(offset).limit(limit)).all()
    unlabeled = db.scalar(select(func.count(SignoffRun.id)).outerjoin(
        RunEvidence, RunEvidence.run_id == SignoffRun.id).where(
            SignoffRun.project_id == project_id,
            (RunEvidence.design_revision.is_(None)) | (RunEvidence.design_revision == ''))) or 0
    return {'items': [dict(row._mapping) for row in rows], 'total': total, 'offset': offset,
            'limit': limit, 'unlabeled_runs': unlabeled}


@router.get('/projects/{project_id}/revision-coverage', response_model=RevisionCoverageOut)
def revision_coverage(project_id: int,
                      revision: str = Query(..., min_length=1, max_length=160),
                      db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    selected_revision = revision.strip()
    if not selected_revision:
        raise HTTPException(422, 'revision must not be blank')
    grouped = db.execute(select(
        SignoffRun.stage, SignoffRun.domain, func.count(SignoffRun.id), func.max(SignoffRun.id),
    ).join(RunEvidence, RunEvidence.run_id == SignoffRun.id).where(
        SignoffRun.project_id == project_id, RunEvidence.design_revision == selected_revision,
    ).group_by(SignoffRun.stage, SignoffRun.domain)).all()
    latest_ids = [latest_id for _, _, _, latest_id in grouped]
    latest_runs = {
        run.id: run for run in db.execute(select(SignoffRun).where(SignoffRun.id.in_(latest_ids))
                                          .options(joinedload(SignoffRun.violations)
                                                   .joinedload(Violation.waiver),
                                                   joinedload(SignoffRun.evidence)
                                                   .defer(RunEvidence.source_text, raiseload=True))
                                          .execution_options(populate_existing=True)).unique().scalars().all()
    } if latest_ids else {}
    observed = {(stage, domain): (count, latest_runs[latest_id])
                for stage, domain, count, latest_id in grouped}
    stages = []
    required_cells = covered_required_cells = 0
    for stage in Stage:
        plan = resolve_signoff_plan(db, project_id, stage)
        required_list = [Domain(value) for value in plan['required_domains']]
        required = set(required_list)
        stage_runs = [run for (run_stage, _), (_, run) in observed.items() if run_stage == stage]
        gate = evaluate_gate(stage_runs, stage, plan,
                             resolve_sta_scenario_plan(db, project_id, stage)['version'])
        gate_domains = {Domain(item['domain']): item for item in gate['domains']}
        required_cells += len(required)
        cells = []
        displayed_domains = [*required_list, *(domain for domain in Domain
                                                if domain not in required and (stage, domain) in observed)]
        for domain in displayed_domains:
            entry = observed.get((stage, domain))
            if domain in required and entry is not None:
                covered_required_cells += 1
            cells.append({'domain': domain, 'required': domain in required,
                          'run_count': entry[0] if entry else 0,
                          'latest_run': entry[1] if entry else None,
                          'gate_ready': gate_domains.get(domain, {}).get('ready', False),
                          'gate_reason': gate_domains.get(domain, {}).get('reason')})
        stages.append({'stage': stage, 'plan_version': plan['version'],
                       'plan_source': plan['source'],
                       'required_domains': required_list,
                       'covered_required_domains': sum(
                           domain in required and (stage, domain) in observed for domain in required),
                       'ready': gate['ready'],
                       'revision_status': gate['revision_check']['status'],
                       'cells': cells})
    return {'project_id': project_id, 'design_revision': selected_revision,
            'total_runs': sum(count for _, _, count, _ in grouped),
            'required_cells': required_cells, 'covered_required_cells': covered_required_cells,
            'stages': stages}


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
                  'commercial_drc_report': 'json', 'commercial_emir_report': 'json', 'commercial_power_report': 'json', 'commercial_thermal_report': 'json', 'commercial_rtl_report': 'json',
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
    waiver_expiry = None
    waiver_revision = None
    if payload.status == ViolationStatus.waived:
        now = datetime.now(timezone.utc)
        waiver_expiry = payload.waiver_expires_at or now + timedelta(days=90)
        if waiver_expiry.tzinfo is None:
            raise HTTPException(422, "waiver expiry must include a timezone")
        waiver_expiry = waiver_expiry.astimezone(timezone.utc)
        if waiver_expiry <= now or waiver_expiry > now + timedelta(days=365):
            raise HTTPException(422, "waiver expiry must be in the future and no more than 365 days away")
        waiver_revision = violation.run.evidence.design_revision if violation.run.evidence else None
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
        violation.waiver = Waiver(reason=payload.reason, approved_by=actor,
                                  approved_user_id=actor_user_id,
                                  design_revision=waiver_revision, expires_at=waiver_expiry)
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
                waiver_design_revision=violation.waiver.design_revision,
                waiver_expires_at=violation.waiver.expires_at,
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
        waiver_design_revision=waiver_revision,
        waiver_expires_at=waiver_expiry,
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
        waiver_expires_at=payload.expires_at,
    ), db)


def gate_runs(project_id: int, stage: Stage, db: Session, revision: str | None = None):
    # One statement captures the selected runs, evidence and violations together.
    # Do not read all historical source texts on every five-second gate poll.
    ranked_query = select(SignoffRun.id, func.row_number().over(
        partition_by=SignoffRun.domain,
        order_by=(SignoffRun.created_at.desc(), SignoffRun.id.desc()),
    ).label('position')).where(SignoffRun.project_id == project_id, SignoffRun.stage == stage)
    if revision is not None:
        ranked_query = ranked_query.join(RunEvidence, RunEvidence.run_id == SignoffRun.id).where(
            RunEvidence.design_revision == revision)
    ranked = ranked_query.subquery()
    return list(db.scalars(
        select(SignoffRun)
        .where(SignoffRun.id.in_(select(ranked.c.id).where(ranked.c.position == 1)))
        .options(joinedload(SignoffRun.violations).joinedload(Violation.waiver),
                 joinedload(SignoffRun.evidence).defer(RunEvidence.source_text, raiseload=True))
        .execution_options(populate_existing=True)
    ).unique())


def current_gate(project_id: int, stage: Stage, db: Session):
    target = resolve_target_revision(db, project_id, stage)
    runs = gate_runs(project_id, stage, db, target['design_revision'])
    gate = evaluate_gate(runs, stage, resolve_signoff_plan(db, project_id, stage),
                         resolve_sta_scenario_plan(db, project_id, stage)['version'])
    gate['target_revision'] = target
    return runs, gate


@router.get("/projects/{project_id}/signoff-status")
def signoff_status(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    return current_gate(project_id, stage, db)[1]


@router.get('/projects/{project_id}/signoff-status/export')
def export_gate(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    runs, gate = current_gate(project_id, stage, db)
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
                    'design_revision': violation.waiver.design_revision,
                    'expires_at': utc(violation.waiver.expires_at) if violation.waiver.expires_at else None,
                    'active': violation.waiver.active,
                    'inactive_reason': violation.waiver.inactive_reason,
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


@router.get('/projects/{project_id}/signoff-package')
def export_signoff_package(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    """Export the current gate snapshot with every selected run's verified source.

    The manifest identifies the exact latest runs selected by the gate. A package
    is refused if a selected source is absent or no longer matches its stored
    digest, so a downloaded archive never presents unverified bytes as evidence.
    """
    get_project_or_404(project_id, db)
    selected, gate = current_gate(project_id, stage, db)
    selected_ids = {item.get('run_id') for item in gate['domains'] if item.get('run_id') is not None}
    runs = sorted((run for run in selected if run.id in selected_ids), key=lambda run: run.id)
    if sum(len(run.violations) for run in runs) > 10000:
        raise HTTPException(413, '게이트 근거의 위반이 10,000건을 초과합니다.')

    # gate_runs intentionally defers large source text during polling. Fetch only
    # the selected sources for this explicit download.
    evidence_by_run = {
        evidence.run_id: evidence for evidence in db.scalars(
            select(RunEvidence).where(RunEvidence.run_id.in_(selected_ids))
        ).all()
    } if selected_ids else {}
    source_files: list[tuple[str, bytes]] = []
    run_records = []
    for run in runs:
        evidence = evidence_by_run.get(run.id)
        if evidence is None or evidence.source_text is None or not evidence.source_sha256:
            raise HTTPException(409, f'런 #{run.id}의 원본 근거 또는 SHA-256이 없습니다.')
        source = evidence.source_text.encode('utf-8')
        digest = hashlib.sha256(source).hexdigest()
        if digest != evidence.source_sha256:
            raise HTTPException(409, f'런 #{run.id}의 원본 근거 무결성 검증에 실패했습니다.')
        path = f'evidence/run-{run.id}-source.txt'
        source_files.append((path, source))
        if sum(len(content) for _, content in source_files) > MAX_EVIDENCE_PACKAGE_BYTES:
            raise HTTPException(413, '사인오프 근거 원본 합계가 32 MiB를 초과합니다.')
        run_records.append({
            'id': run.id, 'domain': run.domain.value, 'stage': run.stage.value,
            'tool': run.tool, 'status': run.status.value,
            'created_at': (run.created_at.replace(tzinfo=timezone.utc) if run.created_at.tzinfo is None else run.created_at.astimezone(timezone.utc)),
            'metrics': run.metrics, 'evidence': {
                'source': evidence.source, 'design_revision': evidence.design_revision,
                'source_sha256': digest, 'file': path,
                'result': netlist_metadata_only(evidence.result),
            },
            'violations': [{
                'id': violation.id, 'check_name': violation.check_name,
                'severity': violation.severity.value, 'status': violation.status.value,
                'version': violation.version, 'location': violation.location,
                'description': violation.description,
                'waiver': None if violation.waiver is None else {
                    'reason': violation.waiver.reason,
                    'approved_by': violation.waiver.approved_by,
                    'approved_user_id': violation.waiver.approved_user_id,
                    'design_revision': violation.waiver.design_revision,
                    'expires_at': ((violation.waiver.expires_at.replace(tzinfo=timezone.utc)
                                    if violation.waiver.expires_at.tzinfo is None else violation.waiver.expires_at.astimezone(timezone.utc))
                                   if violation.waiver.expires_at else None),
                    'active': violation.waiver.active,
                    'inactive_reason': violation.waiver.inactive_reason,
                    'created_at': (violation.waiver.created_at.replace(tzinfo=timezone.utc) if violation.waiver.created_at.tzinfo is None else violation.waiver.created_at.astimezone(timezone.utc)),
                },
            } for violation in sorted(run.violations, key=lambda item: item.id)],
        })

    exported_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        'format': 'signoff/evidence-package/v1', 'project_id': project_id,
        'stage': stage.value, 'exported_at': exported_at, 'gate': gate,
        'runs': run_records,
        'files': [{'path': path, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)} for path, content in source_files],
        'scope_note': 'Exact current gate selection with SHA-256 verified stored source reports and current violation/waiver states. Revision labels are declarations; this package is not a tool-vendor signature or human approval.',
    }
    manifest_bytes = json.dumps(jsonable_encoder(manifest), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('manifest.json', manifest_bytes)
        for path, content in source_files:
            archive.writestr(path, content)
    content = output.getvalue()
    if len(content) > MAX_EVIDENCE_PACKAGE_BYTES:
        raise HTTPException(413, '사인오프 근거 패키지가 32 MiB를 초과합니다.')
    return Response(content, media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="project-{project_id}-{stage.value}-evidence.zip"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Signoff-Manifest-SHA256': manifest_sha256,
    })
