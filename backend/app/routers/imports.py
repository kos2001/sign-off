import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Domain, ReportImport, RunEvidence, SignoffRun, Stage, Violation
from ..services.coverage_attestation import AttestationConfigurationError, verify_drc_attestation, verify_sta_attestation
from ..schemas import RunOut
from ..services.report_import import parse_commercial_sta, parse_opensta
from ..services.commercial_drc import parse_commercial_drc
from ..services.commercial_emir import parse_commercial_emir
from ..services.commercial_power import parse_commercial_power
from ..services.commercial_thermal import parse_commercial_thermal
from ..services.commercial_rtl import parse_commercial_rtl
from ..services.klayout_report import parse_klayout

router = APIRouter(tags=['report-imports'])


def slack_text(value: float) -> str:
    # Keep existing short descriptions where lossless, but never hide a change
    # between distinct captured floats behind the former 12-digit rounding.
    compact = format(value, '.12g')
    return compact if float(compact) == value else str(value)


class CoverageAttestationPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['signoff/coverage-attestation/v1']
    attestation_id: UUID
    key_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._-]+$')
    issued_at: datetime
    expires_at: datetime
    project_id: int = Field(strict=True, ge=1, le=2**63 - 1)
    stage: Stage
    domain: Domain
    design_revision: str = Field(min_length=1, max_length=160)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    tool: str = Field(min_length=1, max_length=80)
    tool_version: str = Field(min_length=1, max_length=80)
    scenario: str = Field(min_length=1, max_length=160)
    claims: dict[str, StrictBool] = Field(min_length=1, max_length=20)
    signature: str = Field(pattern=r'^[0-9a-f]{64}$')


class ReportImportPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    import_id: UUID
    stage: Stage
    filename: str = Field(min_length=1, max_length=160)
    tool_version: str = Field(min_length=1, max_length=80)
    design_revision: str = Field(min_length=1, max_length=160)
    scenario: str = Field(min_length=1, max_length=160)
    source_text: str = Field(min_length=1, max_length=2_000_000)


class CommercialStaImportPayload(ReportImportPayload):
    coverage_attestation: CoverageAttestationPayload | None = None


class CommercialDrcImportPayload(ReportImportPayload):
    coverage_attestation: CoverageAttestationPayload | None = None


def apply_sta_attestation(project_id, payload, result):
    try:
        verified = verify_sta_attestation(payload.coverage_attestation, project_id=project_id,
                                          payload=payload, result=result)
    except AttestationConfigurationError as error:
        raise HTTPException(503, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if verified:
        result['coverage_attestation'] = verified
        result['coverage'] = 'collector_attested_complete'
        result['coverage_note'] = 'Configured collector attests complete STA execution scope; source report and claims are preserved.'
        if result['metrics']['violating_paths'] == 0:
            result['status'] = 'passed'
    return result


def apply_drc_attestation(project_id, payload, result):
    try:
        verified = verify_drc_attestation(payload.coverage_attestation, project_id=project_id,
                                          payload=payload, result=result)
    except AttestationConfigurationError as error:
        raise HTTPException(503, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if verified:
        result['coverage_attestation'] = verified
        result['coverage'] = 'collector_attested_complete'
        result['coverage_note'] = 'Configured collector attests complete DRC execution scope; source report and claims are preserved.'
        if result['metrics']['blocking_multiplicity'] == 0:
            result['status'] = 'passed'
    return result


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
    return store_timing_report(project_id, payload, result, digest, 'OpenSTA', 'opensta_report',
                               'opensta', db)


def store_timing_report(project_id, payload, result, digest, tool, evidence_source, check_prefix, db):
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
    result['metadata']['report_format'] = result['parser']
    result['submitted_by'] = {'user_id': user.id, 'username': user.username} if user else None
    run = SignoffRun(project_id=project_id, domain='sta', stage=payload.stage, tool=tool,
                     status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source=evidence_source, source_text=payload.source_text,
                               source_sha256=result['source_sha256'],
                               design_revision=payload.design_revision, result=result)
    for path in result['paths']:
        if path['slack_ps'] is None or path['slack_ps'] < 0:
            run.violations.append(Violation(
                check_name=f"{check_prefix}/{path['path_type']}/{path['fingerprint'][:32]}",
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


@router.post('/projects/{project_id}/imports/commercial-power/preview')
def preview_commercial_power(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload, parse_commercial_power)
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    return result


@router.post('/projects/{project_id}/imports/commercial-power', response_model=RunOut, status_code=201)
def import_commercial_power(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload, parse_commercial_power)
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    digest = hashlib.sha256(json.dumps({'format': 'commercial-power', 'payload': payload.model_dump(mode='json')},
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def existing():
        receipt = db.scalar(select(ReportImport).where(ReportImport.project_id == project_id, ReportImport.import_key == str(payload.import_id)))
        if receipt:
            if receipt.payload_sha256 != digest:
                raise HTTPException(409, 'import identifier already used with different content')
            return db.get(SignoffRun, receipt.run_id)
    if run := existing(): return run
    user = db.info.get('user')
    result['metadata'] = {key: getattr(payload, key) for key in ['filename', 'tool_version', 'scenario']}
    result['metadata']['report_format'] = result['parser']
    result['submitted_by'] = {'user_id': user.id, 'username': user.username} if user else None
    run = SignoffRun(project_id=project_id, domain='glitch_power', stage=payload.stage, tool=result['tool'], status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='commercial_power_report', source_text=payload.source_text,
        source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    prefix = {'Synopsys PrimePower': 'primepower', 'Cadence Joules': 'joules', 'Ansys PowerArtist': 'powerartist'}[result['tool']]
    for item in [result['summary'], *result['items']]:
        if item['violated']:
            fingerprint = hashlib.sha256(item['path'].encode()).hexdigest()
            run.violations.append(Violation(check_name=f'{prefix}/glitch-share/{fingerprint[:32]}', severity='error',
                location=item['path'], description=f"Glitch share: {item['glitch_share']:.6g} · limit: {result['glitch_share_limit']:.6g}\nGlitch: {item['glitch_power_mw']:.6g} mW · total: {item['total_power_mw']:.6g} mW"))
    db.add(run)
    try:
        db.flush(); db.add(ReportImport(project_id=project_id, import_key=str(payload.import_id), payload_sha256=digest, run_id=run.id)); db.commit()
    except IntegrityError:
        db.rollback()
        if run := existing(): return run
        raise
    return run


@router.post('/projects/{project_id}/imports/commercial-thermal/preview')
def preview_commercial_thermal(project_id:int,payload:ReportImportPayload,db:Session=Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id,db);result=parse(payload,parse_commercial_thermal)
    if result['tool_version']!=payload.tool_version.strip():raise HTTPException(422,'tool_version must match the version captured in the report')
    return result

@router.post('/projects/{project_id}/imports/commercial-thermal',response_model=RunOut,status_code=201)
def import_commercial_thermal(project_id:int,payload:ReportImportPayload,db:Session=Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id,db);result=parse(payload,parse_commercial_thermal)
    if result['tool_version']!=payload.tool_version.strip():raise HTTPException(422,'tool_version must match the version captured in the report')
    digest=hashlib.sha256(json.dumps({'format':'commercial-thermal','payload':payload.model_dump(mode='json')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def existing():
        receipt=db.scalar(select(ReportImport).where(ReportImport.project_id==project_id,ReportImport.import_key==str(payload.import_id)))
        if receipt:
            if receipt.payload_sha256!=digest:raise HTTPException(409,'import identifier already used with different content')
            return db.get(SignoffRun,receipt.run_id)
    if run:=existing():return run
    user=db.info.get('user');result['metadata']={key:getattr(payload,key) for key in ['filename','tool_version','scenario']};result['metadata']['report_format']=result['parser'];result['submitted_by']={'user_id':user.id,'username':user.username}if user else None
    run=SignoffRun(project_id=project_id,domain='thermal',stage=payload.stage,tool=result['tool'],status=result['status'],metrics=result['metrics']);run.evidence=RunEvidence(source='commercial_thermal_report',source_text=payload.source_text,source_sha256=result['source_sha256'],design_revision=payload.design_revision,result=result)
    prefix={'Cadence Celsius':'celsius','Ansys Icepak':'icepak','Siemens Calibre 3DSTACK':'calibre3d'}[result['tool']]
    for item in result['items']:
        if item['violated']:run.violations.append(Violation(check_name=f"{prefix}/temperature/{item['fingerprint'][:32]}",severity=item['severity'],location=item['component'],description=f"Temperature: {item['temperature_c']:.6g} C · limit: {item['limit_c']:.6g} C\nLayer: {item['layer'] or 'not reported'} · position: ({item['x_um']}, {item['y_um']}, {item['z_um']}) um\n{item['message']}"))
    db.add(run)
    try:db.flush();db.add(ReportImport(project_id=project_id,import_key=str(payload.import_id),payload_sha256=digest,run_id=run.id));db.commit()
    except IntegrityError:
        db.rollback()
        if run:=existing():return run
        raise
    return run

@router.post('/projects/{project_id}/imports/commercial-rtl/preview')
def preview_commercial_rtl(project_id:int,payload:ReportImportPayload,db:Session=Depends(get_db)):
 from .projects import get_project_or_404
 get_project_or_404(project_id,db);result=parse(payload,parse_commercial_rtl)
 if result['tool_version']!=payload.tool_version.strip():raise HTTPException(422,'tool_version must match the version captured in the report')
 return result
@router.post('/projects/{project_id}/imports/commercial-rtl',response_model=RunOut,status_code=201)
def import_commercial_rtl(project_id:int,payload:ReportImportPayload,db:Session=Depends(get_db)):
 from .projects import get_project_or_404
 get_project_or_404(project_id,db);result=parse(payload,parse_commercial_rtl)
 if result['tool_version']!=payload.tool_version.strip():raise HTTPException(422,'tool_version must match the version captured in the report')
 digest=hashlib.sha256(json.dumps({'format':'commercial-rtl','payload':payload.model_dump(mode='json')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 def existing():
  receipt=db.scalar(select(ReportImport).where(ReportImport.project_id==project_id,ReportImport.import_key==str(payload.import_id)))
  if receipt:
   if receipt.payload_sha256!=digest:raise HTTPException(409,'import identifier already used with different content')
   return db.get(SignoffRun,receipt.run_id)
 if run:=existing():return run
 user=db.info.get('user');result['metadata']={k:getattr(payload,k)for k in['filename','tool_version','scenario']};result['metadata']['report_format']=result['parser'];result['submitted_by']={'user_id':user.id,'username':user.username}if user else None
 run=SignoffRun(project_id=project_id,domain='rtl',stage=payload.stage,tool=result['tool'],status=result['status'],metrics=result['metrics']);run.evidence=RunEvidence(source='commercial_rtl_report',source_text=payload.source_text,source_sha256=result['source_sha256'],design_revision=payload.design_revision,result=result);prefix='vcs'if result['tool']=='Synopsys VCS'else'xcelium'
 if result['compile_status']=='failed':run.violations.append(Violation(check_name=f'{prefix}/compile',severity='error',location=None,description='Commercial simulator compilation failed.\n'+result['compile_log_excerpt']))
 for item in result['items']:
  if item['status']=='failed':run.violations.append(Violation(check_name=f"{prefix}/test/{item['fingerprint'][:32]}",severity='error',location=item['name'],description=f"Test failed · seed {item['seed']} · failed assertions {item['assertions']['failed']}\n{item['log_excerpt']}"))
 db.add(run)
 try:db.flush();db.add(ReportImport(project_id=project_id,import_key=str(payload.import_id),payload_sha256=digest,run_id=run.id));db.commit()
 except IntegrityError:
  db.rollback()
  if run:=existing():return run
  raise
 return run


@router.post('/projects/{project_id}/imports/commercial-sta/preview')
def preview_commercial_sta(project_id: int, payload: CommercialStaImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = apply_sta_attestation(project_id, payload, parse(payload, parse_commercial_sta))
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    return result


@router.post('/projects/{project_id}/imports/commercial-sta', response_model=RunOut, status_code=201)
def import_commercial_sta(project_id: int, payload: CommercialStaImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    digest = hashlib.sha256(json.dumps({'format': 'commercial-sta',
        'payload': payload.model_dump(mode='json')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = db.scalar(select(ReportImport).where(
        ReportImport.project_id == project_id,
        ReportImport.import_key == str(payload.import_id),
    ))
    if receipt:
        if receipt.payload_sha256 != digest:
            raise HTTPException(409, 'import identifier already used with different content')
        return db.get(SignoffRun, receipt.run_id)
    result = apply_sta_attestation(project_id, payload, parse(payload, parse_commercial_sta))
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    prefix = 'primetime' if result['tool'] == 'Synopsys PrimeTime' else 'tempus'
    return store_timing_report(project_id, payload, result, digest, result['tool'],
                               'commercial_sta_report', prefix, db)


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
    return store_drc_report(project_id, payload, result, digest, 'KLayout DRC', 'klayout_report', 'klayout', db)


def store_drc_report(project_id, payload, result, digest, tool, evidence_source, check_prefix, db):
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
    result['metadata']['report_format'] = result['parser']
    run = SignoffRun(project_id=project_id, domain='pv', stage=payload.stage, tool=tool, status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source=evidence_source, source_text=payload.source_text, source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    for item in result['items']:
        run.violations.append(Violation(check_name=f"{check_prefix}/{item['fingerprint'][:32]}", severity=item.get('severity', 'error'), location=item['cell'] or None,
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


@router.post('/projects/{project_id}/imports/commercial-drc/preview')
def preview_commercial_drc(project_id: int, payload: CommercialDrcImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = apply_drc_attestation(project_id, payload, parse(payload, parse_commercial_drc))
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    return result


@router.post('/projects/{project_id}/imports/commercial-drc', response_model=RunOut, status_code=201)
def import_commercial_drc(project_id: int, payload: CommercialDrcImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    digest = hashlib.sha256(json.dumps({'format': 'commercial-drc',
        'payload': payload.model_dump(mode='json')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = db.scalar(select(ReportImport).where(
        ReportImport.project_id == project_id,
        ReportImport.import_key == str(payload.import_id),
    ))
    if receipt:
        if receipt.payload_sha256 != digest:
            raise HTTPException(409, 'import identifier already used with different content')
        return db.get(SignoffRun, receipt.run_id)
    result = apply_drc_attestation(project_id, payload, parse(payload, parse_commercial_drc))
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    return store_drc_report(project_id, payload, result, digest, result['tool'],
                            'commercial_drc_report', result['violation_prefix'], db)


@router.post('/projects/{project_id}/imports/commercial-emir/preview')
def preview_commercial_emir(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload, parse_commercial_emir)
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    return result


@router.post('/projects/{project_id}/imports/commercial-emir', response_model=RunOut, status_code=201)
def import_commercial_emir(project_id: int, payload: ReportImportPayload, db: Session = Depends(get_db)):
    from .projects import get_project_or_404
    get_project_or_404(project_id, db)
    result = parse(payload, parse_commercial_emir)
    if result['tool_version'] != payload.tool_version.strip():
        raise HTTPException(422, 'tool_version must match the version captured in the report')
    digest = hashlib.sha256(json.dumps({'format': 'commercial-emir',
        'payload': payload.model_dump(mode='json')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
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
    result['metadata']['report_format'] = result['parser']
    result['submitted_by'] = {'user_id': user.id, 'username': user.username} if user else None
    run = SignoffRun(project_id=project_id, domain='emir', stage=payload.stage, tool=result['tool'],
                     status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='commercial_emir_report', source_text=payload.source_text,
        source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    prefix = {'Ansys RedHawk-SC': 'redhawk', 'Cadence Voltus': 'voltus', 'Ansys Totem': 'totem'}[result['tool']]
    for item in result['items']:
        if item['violated']:
            run.violations.append(Violation(check_name=f"{prefix}/{item['fingerprint'][:32]}",
                severity=item['severity'], location=item['instance'] or item['net'] or f"({item['x_um']}, {item['y_um']}) um",
                description=f"{item['analysis']} · {item['metric']} · {item['check']}\nReported: {item['value']} {item['unit']} · limit: {item['limit']} {item['unit']}\nLayer: {item['layer'] or 'not reported'}\n{item['message']}"))
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
