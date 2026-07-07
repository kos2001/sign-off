from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Domain, SignoffRun, Stage, Violation, ViolationStatus, Waiver
from ..schemas import (
    RunCreate,
    RunOut,
    RunUpdate,
    ViolationCreate,
    ViolationOut,
    WaiverCreate,
)
from ..services.stages import evaluate_gate
from .projects import get_project_or_404

router = APIRouter(tags=["signoff-runs"])


def get_run_or_404(run_id: int, db: Session) -> SignoffRun:
    run = db.get(SignoffRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=201)
def create_run(project_id: int, payload: RunCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    run = SignoffRun(project_id=project_id, **payload.model_dump())
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
    return db.scalars(query.order_by(SignoffRun.id)).all()


@router.patch("/runs/{run_id}", response_model=RunOut)
def update_run(run_id: int, payload: RunUpdate, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    run.status = payload.status
    if payload.metrics is not None:
        run.metrics = payload.metrics
    db.commit()
    return run


@router.post(
    "/runs/{run_id}/violations", response_model=list[ViolationOut], status_code=201
)
def add_violations(
    run_id: int, payload: list[ViolationCreate], db: Session = Depends(get_db)
):
    run = get_run_or_404(run_id, db)
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


@router.post("/violations/{violation_id}/waiver", response_model=ViolationOut, status_code=201)
def waive_violation(
    violation_id: int, payload: WaiverCreate, db: Session = Depends(get_db)
):
    violation = db.get(Violation, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="violation not found")
    if violation.waiver is not None:
        raise HTTPException(status_code=409, detail="violation already waived")
    violation.waiver = Waiver(**payload.model_dump())
    violation.status = ViolationStatus.waived
    db.commit()
    return violation


@router.get("/projects/{project_id}/signoff-status")
def signoff_status(project_id: int, stage: Stage, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    runs = db.scalars(
        select(SignoffRun)
        .where(SignoffRun.project_id == project_id)
        .options(selectinload(SignoffRun.violations))
    ).all()
    return evaluate_gate(runs, stage)
