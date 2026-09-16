import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ReportImport, RunEvidence, SignoffRun, Stage, Violation
from ..schemas import RunOut
from ..services.report_import import parse_opensta
from ..services.klayout_report import parse_klayout

router = APIRouter(tags=['report-imports'])


def slack_text(value: float) -> str:
    # Keep existing short descriptions where lossless, but never hide a change
    # between distinct captured floats behind the former 12-digit rounding.
    compact = format(value, '.12g')
    return compact if float(compact) == value else str(value)


class ReportImportPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    import_id: UUID
    stage: Stage
    filename: str = Field(min_length=1, max_length=160)
    tool_version: str = Field(min_length=1, max_length=80)
    design_revision: str = Field(min_length=1, max_length=160)
    scenario: str = Field(min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=2_000_000)


def parse(payload, parser=parse_opensta):
    for field in ['filename', 'tool_version', 'design_revision', 'scenario']:
        if not getattr(payload, field).strip():
            raise HTTPException(422, f'{field} must not be blank')
    try:
        return parser(payload.source_text)
    except (ValueError, UnicodeError) as error:
        raise HTTPException(422, str(error)) from None


@router.post('/projects/{project_id}/imports/opensta/preview')
def preview(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    return parse(payload)


@router.post('/projects/{project_id}/imports/opensta', response_model=RunOut, status_code=201)
def import_report(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload)
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode='json'), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def existing():
        receipt = db.scalar(select(ReportImport).where(ReportImport.project_id == project_id, ReportImport.import_key == str(payload.import_id)))
        if receipt:
            if receipt.payload_sha256 != digest:
                raise HTTPException(409, 'import identifier already used with different content')
            return db.get(SignoffRun, receipt.run_id)
    if run := existing():
        return run
    user = db.info.get('user')
    result['metadata'] = {key: getattr(payload, key) for key in ['filename', 'tool_version', 'scenario']}
    result['submitted_by'] = {'user_id': user.id, 'username': user.username} if user else None
    run = SignoffRun(project_id=project_id, domain='sta', stage=payload.stage, tool='OpenSTA', status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='opensta_report', source_text=payload.source_text, source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    for path in result['paths']:
        if path['slack_ps'] is None or path['slack_ps'] < 0:
            run.violations.append(Violation(
                check_name=f"opensta/{path['path_type']}/{path['fingerprint'][:32]}",
                severity='warning' if path['slack_ps'] is None else 'error', location=path['endpoint'],
                description=f"{payload.scenario} · {path['path_group']} · {path['startpoint']} → {path['endpoint']}\n" + ('Unconstrained path' if path['slack_ps'] is None else f"Reported slack: {slack_text(path['slack_ps'])} ps")))
    db.add(run)
    try:
        db.flush()
        db.add(ReportImport(project_id=project_id, import_key=str(payload.import_id), payload_sha256=digest, run_id=run.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        if run := existing():
            return run
        raise
    return run


@router.post('/projects/{project_id}/imports/klayout/preview')
def preview_klayout(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    return parse(payload, parse_klayout)


@router.post('/projects/{project_id}/imports/klayout', response_model=RunOut, status_code=201)
def import_klayout(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload, parse_klayout)
    digest = hashlib.sha256(json.dumps({'format': 'klayout', 'payload': payload.model_dump(mode='json')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def existing():
        receipt = db.scalar(select(ReportImport).where(ReportImport.project_id == project_id, ReportImport.import_key == str(payload.import_id)))
        if receipt:
            if receipt.payload_sha256 != digest:
                raise HTTPException(409, 'import identifier already used with different content')
            return db.get(SignoffRun, receipt.run_id)
    if run := existing():
        return run
    user = db.info.get('user')
    result['metadata'] = {key: getattr(payload, key) for key in ['filename', 'tool_version', 'scenario']}
    result['submitted_by'] = {'user_id': user.id, 'username': user.username} if user else None
    run = SignoffRun(project_id=project_id, domain='pv', stage=payload.stage, tool='KLayout DRC', status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='klayout_report', source_text=payload.source_text, source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    for item in result['items']:
        run.violations.append(Violation(check_name=f"klayout/{item['fingerprint'][:32]}", severity='error', location=item['cell'] or None,
            description=f"Category: {item['category']}\nReported multiplicity: {item['multiplicity']}\n" + '\n'.join(item['values']) + f"\nSource tags (not approvals): {item['tags']}\nComment: {item['comment']}"))
    db.add(run)
    try:
        db.flush()
        db.add(ReportImport(project_id=project_id, import_key=str(payload.import_id), payload_sha256=digest, run_id=run.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        if run := existing():
            return run
        raise
    return run
