from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.access import change_membership
from ..services.coverage_attestation import REQUIRED_CLAIMS
from ..services.stages import resolve_signoff_plan
from ..services.sta_scenario_plans import resolve_sta_scenario_plan
from ..auth import auth_required
from ..auth import require_project
from ..models import Project, ProjectMember, ProjectSignoffPlanRevision, Stage
from ..schemas import (CollectorContextOut, ProjectCreate, ProjectOut,
                       SignoffPlanHistoryOut, SignoffPlanOut,
                       SignoffPlanStageOut, SignoffPlanUpdate)

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
def list_projects(db: Session = Depends(get_db)):
    query = select(Project)
    user = db.info.get("user")
    if auth_required() and user and not user.is_admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return db.scalars(query.order_by(Project.id)).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return get_project_or_404(project_id, db)


@router.get('/{project_id}/collector-context/{stage}', response_model=CollectorContextOut)
def collector_context(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    """Return the current machine-readable contract for a project-stage collector."""
    get_project_or_404(project_id, db)
    plan = resolve_signoff_plan(db, project_id, stage)
    return {
        'format': 'signoff/collector-context/v1', 'project_id': project_id, 'stage': stage,
        'signoff_plan': plan,
        'sta_scenario_plan': resolve_sta_scenario_plan(db, project_id, stage),
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
