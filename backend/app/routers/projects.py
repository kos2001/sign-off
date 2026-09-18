from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.access import change_membership
from ..services.coverage_attestation import REQUIRED_CLAIMS
from ..services.stages import resolve_signoff_plan, resolve_target_revision
from ..services.sta_scenario_plans import resolve_sta_scenario_plan
from ..auth import auth_required
from ..auth import require_project
from ..models import (Project, ProjectLifecycleEvent, ProjectMember, ProjectSignoffPlanRevision,
                      ProjectStageTargetRevision,
                      RunStatus, SignoffRun, StaBatchExecution, Stage)
from ..schemas import (CollectorContextOut, ProjectCreate, ProjectLifecycleHistoryOut,
                       ProjectLifecycleUpdate, ProjectOut, ProjectSummaryOut, ProjectSummaryPageOut,
                       SignoffPlanHistoryOut, SignoffPlanOut,
                       SignoffPlanStageOut, SignoffPlanUpdate, TargetRevisionHistoryOut,
                       TargetRevisionOut, TargetRevisionsOut, TargetRevisionUpdate)

router = APIRouter(prefix="/projects", tags=["projects"])

IMPORT_PATHS = {
    'rtl': 'commercial-rtl', 'cdc': 'commercial-cdc', 'sta': 'commercial-sta',
    'emir': 'commercial-emir', 'pv': 'commercial-drc', 'lvs': 'commercial-lvs',
    'lec': 'commercial-lec', 'dft': 'commercial-dft',
    'low_power': 'commercial-low-power', 'glitch_power': 'commercial-power',
    'thermal': 'commercial-thermal',
}


def get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(Project).where(Project.name == payload.name))
    if exists:
        raise HTTPException(status_code=409, detail="project name already exists")
    project = Project(**payload.model_dump())
    db.add(project)
    db.flush()
    user = db.info.get("user")
    if user:
        change_membership(db, project.id, user, "owner", actor=user)
    db.commit()
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(include_archived: bool = False, db: Session = Depends(get_db)):
    query = select(Project)
    user = db.info.get("user")
    if auth_required() and user and not user.is_admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    if not include_archived:
        query = query.where(Project.archived_at.is_(None))
    return db.scalars(query.order_by(Project.id)).all()


@router.get('/summary', response_model=list[ProjectSummaryOut])
def project_summaries(db: Session = Depends(get_db)):
    query = select(Project)
    user = db.info.get('user')
    if auth_required() and user and not user.is_admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    query = query.where(Project.archived_at.is_(None))
    projects = db.scalars(query.order_by(Project.id)).all()
    ids = [project.id for project in projects]
    counts = {project_id: {status.value: 0 for status in RunStatus} for project_id in ids}
    if ids:
        for project_id, status, count in db.execute(select(
            SignoffRun.project_id, SignoffRun.status, func.count(),
        ).where(SignoffRun.project_id.in_(ids)).group_by(SignoffRun.project_id, SignoffRun.status)):
            counts[project_id][status.value] = count
    return [{
        'id': project.id, 'name': project.name, 'process_node': project.process_node,
        'foundry': project.foundry, 'created_at': project.created_at,
        'lifecycle_version': project.lifecycle_version, 'archived_at': project.archived_at,
        'archived_by': project.archived_by, 'archived_by_user_id': project.archived_by_user_id,
        'total_runs': sum(counts[project.id].values()), 'status_counts': counts[project.id],
    } for project in projects]


@router.get('/summary/page', response_model=ProjectSummaryPageOut)
def project_summary_page(q: str | None = Query(None, min_length=1, max_length=120),
                         sort: Literal['newest', 'oldest', 'name'] = 'newest',
                         lifecycle: Literal['active', 'archived', 'all'] = 'active',
                         offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100),
                         db: Session = Depends(get_db)):
    query = select(Project)
    user = db.info.get('user')
    if auth_required() and user and not user.is_admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    if lifecycle == 'active':
        query = query.where(Project.archived_at.is_(None))
    elif lifecycle == 'archived':
        query = query.where(Project.archived_at.is_not(None))
    if q is not None:
        search = q.strip()
        if not search:
            raise HTTPException(422, detail='q must contain non-whitespace characters')
        needle = search.casefold()
        query = query.where(
            func.lower(Project.name).contains(needle, autoescape=True)
            | func.lower(Project.process_node).contains(needle, autoescape=True)
            | func.lower(Project.foundry).contains(needle, autoescape=True)
        )

    project_ids = query.with_only_columns(Project.id).order_by(None).subquery()
    total = db.scalar(select(func.count()).select_from(project_ids)) or 0
    foundry_count = db.scalar(select(func.count(func.distinct(Project.foundry)))
                              .where(Project.id.in_(select(project_ids.c.id)))) or 0
    latest_process_node = db.scalar(select(Project.process_node)
                                    .where(Project.id.in_(select(project_ids.c.id)))
                                    .order_by(Project.created_at.desc(), Project.id.desc()).limit(1))
    aggregate = {status.value: 0 for status in RunStatus}
    for status, count in db.execute(select(SignoffRun.status, func.count())
                                    .where(SignoffRun.project_id.in_(select(project_ids.c.id)))
                                    .group_by(SignoffRun.status)):
        aggregate[status.value] = count

    ordering = {
        'newest': (Project.created_at.desc(), Project.id.desc()),
        'oldest': (Project.created_at.asc(), Project.id.asc()),
        'name': (func.lower(Project.name).asc(), Project.id.asc()),
    }[sort]
    projects = db.scalars(query.order_by(*ordering).offset(offset).limit(limit)).all()
    ids = [project.id for project in projects]
    counts = {project_id: {status.value: 0 for status in RunStatus} for project_id in ids}
    if ids:
        for project_id, status, count in db.execute(select(
            SignoffRun.project_id, SignoffRun.status, func.count(),
        ).where(SignoffRun.project_id.in_(ids)).group_by(SignoffRun.project_id, SignoffRun.status)):
            counts[project_id][status.value] = count
    return {
        'items': [{
            'id': project.id, 'name': project.name, 'process_node': project.process_node,
            'foundry': project.foundry, 'created_at': project.created_at,
            'lifecycle_version': project.lifecycle_version, 'archived_at': project.archived_at,
            'archived_by': project.archived_by, 'archived_by_user_id': project.archived_by_user_id,
            'total_runs': sum(counts[project.id].values()), 'status_counts': counts[project.id],
        } for project in projects],
        'total': total, 'offset': offset, 'limit': limit, 'foundry_count': foundry_count,
        'latest_process_node': latest_process_node, 'status_counts': aggregate,
    }


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return get_project_or_404(project_id, db)


@router.put('/{project_id}/lifecycle', response_model=ProjectOut)
def update_project_lifecycle(project_id: int, payload: ProjectLifecycleUpdate,
                             db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    require_project(db, project_id, 'owner')
    currently_archived = project.archived_at is not None
    if payload.archived == currently_archived:
        raise HTTPException(409, detail='project lifecycle already has the requested state')
    if payload.archived:
        active_run = db.scalar(select(SignoffRun.id).where(
            SignoffRun.project_id == project_id, SignoffRun.status == RunStatus.running).limit(1))
        active_batch = db.scalar(select(StaBatchExecution.id).where(
            StaBatchExecution.project_id == project_id,
            StaBatchExecution.status.in_(('queued', 'running'))).limit(1))
        if active_run is not None or active_batch is not None:
            raise HTTPException(409, detail='finish or cancel active runs and STA batches before archiving')
    user = db.info.get('user')
    actor = user.username if user else 'local operator'
    changed_at = datetime.now(timezone.utc)
    changed = db.execute(update(Project).where(
        Project.id == project_id, Project.lifecycle_version == payload.expected_version,
        Project.archived_at.is_not(None) if currently_archived else Project.archived_at.is_(None),
    ).values(
        lifecycle_version=payload.expected_version + 1,
        archived_at=changed_at if payload.archived else None,
        archived_by=actor if payload.archived else None,
        archived_by_user_id=user.id if payload.archived and user else None,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, detail='project lifecycle changed; reload and retry')
    db.add(ProjectLifecycleEvent(
        project_id=project_id, version=payload.expected_version + 1,
        before_state='archived' if currently_archived else 'active',
        after_state='archived' if payload.archived else 'active', reason=payload.reason,
        actor=actor, actor_user_id=user.id if user else None,
    ))
    db.commit()
    db.expire_all()
    return get_project_or_404(project_id, db)


@router.get('/{project_id}/lifecycle/history', response_model=ProjectLifecycleHistoryOut)
def project_lifecycle_history(project_id: int, before_id: int | None = Query(None, ge=1),
                              limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    require_project(db, project_id, 'owner')
    filters = [ProjectLifecycleEvent.project_id == project_id]
    if before_id is not None:
        filters.append(ProjectLifecycleEvent.id < before_id)
    rows = db.scalars(select(ProjectLifecycleEvent).where(*filters)
                      .order_by(ProjectLifecycleEvent.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {'items': items, 'next_before_id': items[-1].id if len(rows) > limit else None}


@router.get('/{project_id}/collector-context/{stage}', response_model=CollectorContextOut)
def collector_context(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    """Return the current machine-readable contract for a project-stage collector."""
    get_project_or_404(project_id, db)
    plan = resolve_signoff_plan(db, project_id, stage)
    return {
        'format': 'signoff/collector-context/v1', 'project_id': project_id, 'stage': stage,
        'signoff_plan': plan,
        'sta_scenario_plan': resolve_sta_scenario_plan(db, project_id, stage),
        'target_revision': resolve_target_revision(db, project_id, stage),
        'domains': [{
            'domain': domain, 'import_path': f'/projects/{project_id}/imports/{IMPORT_PATHS[domain]}',
            'required_claims': sorted(REQUIRED_CLAIMS[domain]),
        } for domain in plan['required_domains']],
    }


@router.get("/{project_id}/signoff-plan", response_model=SignoffPlanOut)
def get_signoff_plan(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    return {"project_id": project_id, "stages": [
        SignoffPlanStageOut.model_validate(resolve_signoff_plan(db, project_id, stage))
        for stage in Stage
    ]}


@router.get('/{project_id}/target-revisions', response_model=TargetRevisionsOut)
def get_target_revisions(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    return {'project_id': project_id,
            'stages': [resolve_target_revision(db, project_id, stage) for stage in Stage]}


@router.get('/{project_id}/target-revisions/history', response_model=TargetRevisionHistoryOut)
def target_revision_history(project_id: int, stage: Stage | None = None,
                            before_id: int | None = Query(None, ge=1),
                            limit: int = Query(25, ge=1, le=100),
                            db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filters = [ProjectStageTargetRevision.project_id == project_id]
    if stage is not None:
        filters.append(ProjectStageTargetRevision.stage == stage)
    if before_id is not None:
        filters.append(ProjectStageTargetRevision.id < before_id)
    rows = db.scalars(select(ProjectStageTargetRevision).where(*filters)
                      .order_by(ProjectStageTargetRevision.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {'items': items, 'next_before_id': items[-1].id if len(rows) > limit else None}


@router.put('/{project_id}/target-revisions/{stage}', response_model=TargetRevisionOut)
def update_target_revision(project_id: int, stage: Stage, payload: TargetRevisionUpdate,
                           db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    require_project(db, project_id, 'approver')
    current = resolve_target_revision(db, project_id, stage)
    if payload.expected_version != current['version']:
        raise HTTPException(409, detail={'message': 'target revision changed; reload and retry',
                                         'current': jsonable_encoder(current)})
    user = db.info.get('user')
    revision = ProjectStageTargetRevision(
        project_id=project_id, stage=stage, version=current['version'] + 1,
        design_revision=payload.design_revision, reason=payload.reason,
        updated_by=user.username if user else 'local operator',
        updated_by_user_id=user.id if user else None,
    )
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        latest = resolve_target_revision(db, project_id, stage)
        raise HTTPException(409, detail={'message': 'target revision changed; reload and retry',
                                         'current': jsonable_encoder(latest)}) from None
    return resolve_target_revision(db, project_id, stage)


@router.get("/{project_id}/signoff-plan/history", response_model=SignoffPlanHistoryOut)
def get_signoff_plan_history(project_id: int, stage: Stage | None = None,
                             before_id: int | None = Query(None, ge=1),
                             limit: int = Query(25, ge=1, le=100),
                             db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filters = [ProjectSignoffPlanRevision.project_id == project_id]
    if stage is not None:
        filters.append(ProjectSignoffPlanRevision.stage == stage)
    if before_id is not None:
        filters.append(ProjectSignoffPlanRevision.id < before_id)
    rows = db.scalars(select(ProjectSignoffPlanRevision).where(*filters)
                      .order_by(ProjectSignoffPlanRevision.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {"items": [{
        "id": item.id, "stage": item.stage, "version": item.version, "source": "custom",
        "required_domains": item.required_domains, "reason": item.reason,
        "updated_by": item.updated_by, "updated_by_user_id": item.updated_by_user_id,
        "created_at": item.created_at,
    } for item in items], "next_before_id": items[-1].id if len(rows) > limit else None}


@router.put("/{project_id}/signoff-plan/{stage}", response_model=SignoffPlanStageOut)
def update_signoff_plan(project_id: int, stage: Stage, payload: SignoffPlanUpdate,
                        db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    require_project(db, project_id, "approver")
    current = resolve_signoff_plan(db, project_id, stage)
    if payload.expected_version != current["version"]:
        raise HTTPException(409, detail={"message": "sign-off plan changed; reload and retry",
                                         "current": jsonable_encoder(current)})
    user = db.info.get("user")
    revision = ProjectSignoffPlanRevision(
        project_id=project_id, stage=stage, version=current["version"] + 1,
        required_domains=[domain.value for domain in payload.required_domains],
        reason=payload.reason.strip(), updated_by=user.username if user else "local operator",
        updated_by_user_id=user.id if user else None,
    )
    db.add(revision)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        latest = resolve_signoff_plan(db, project_id, stage)
        raise HTTPException(409, detail={"message": "sign-off plan changed; reload and retry",
                                         "current": jsonable_encoder(latest)}) from None
    return SignoffPlanStageOut.model_validate(resolve_signoff_plan(db, project_id, stage))
