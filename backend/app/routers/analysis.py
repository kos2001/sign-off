import json
import hashlib
import logging
import math
import threading
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..auth import require_project
from ..models import Domain, Project, RunArtifact, RunEvidence, Severity, SignoffRun, Stage, Violation
from ..schemas import (
    GlitchPowerRequest,
    IrDropRequest,
    RtlSignoffRequest,
    StaBatchRequest,
    StaSignoffRequest,
    TimingSummaryRequest,
)
from ..services.glitch import estimate_glitch_power
from ..services.evidence import rtl_result_status
from ..services.irdrop import screen_ir_drop
from ..services.rtl.signoff import run_signoff, stream_signoff
from ..services.rtl.tools import strip_fences
from ..services.rtl.admission import acquire_slot, AdmittedStreamingResponse
from ..services.rtl.worker_client import container_mode, stream_worker, WorkerError
from ..services.sta_worker_client import run_sta, StaWorkerError
from .imports import slack_text
from ..services.timing import summarize_corners

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = logging.getLogger('uvicorn.error.signoff')

_RULE_SEVERITY = {"error": Severity.error, "warn": Severity.warning, "info": Severity.info}


def screening_result(function, **kwargs):
    def check(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ArithmeticError('non-finite result')
        if isinstance(value, dict):
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    try:
        result = function(**kwargs)
        check(result)
        return result
    except ArithmeticError:
        raise HTTPException(422, 'inputs exceed the supported numerical range') from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post('/ir-drop')
def ir_drop(payload: IrDropRequest):
    return screening_result(screen_ir_drop, **payload.model_dump())


@router.post('/glitch-power')
def glitch_power(payload: GlitchPowerRequest):
    return screening_result(estimate_glitch_power, **payload.model_dump())


def _record_rtl_run(db: Session, project_id: int, result: dict, code: str, design_revision: str | None = None) -> int:
    """File a ladder result as a signoff run + violations (drives the RTL gate)."""
    run = SignoffRun(
        project_id=project_id,
        domain=Domain.rtl,
        stage=Stage.rtl,
        tool="rtl-signoff-ladder",
        status=rtl_result_status(result),
        metrics={
            "verdict": result["verdict"],
            "score": result["score"],
            "grade": result["grade"],
            "module": result["module"],
            "stages": result["stages"],
        },
    )
    source = strip_fences(code)
    if source:
        source += "\n"  # Match the design.sv bytes written by both tool wrappers.
    run.evidence = RunEvidence(
        source="rtl_ladder", source_text=source,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        design_revision=design_revision, result=result,
    )
    db.add(run)
    db.flush()
    db.add_all(
        Violation(
            run_id=run.id,
            check_name=f"{r['code']}: {r['name']}",
            severity=_RULE_SEVERITY[r["severity"]],
            location=result["module"],
            description=r["detail"],
        )
        for r in result["rules"]
        if r["status"] == "violation"
    )
    db.commit()
    return run.id


@router.post("/rtl-signoff")
def rtl_signoff(payload: RtlSignoffRequest, db: Session = Depends(get_db)):
    """Run the RTL sign-off ladder (verilator lint -> design rules -> yosys
    synth -> verdict). With `project_id`, the result is recorded as a signoff
    run and failing checks are filed as violations, driving the RTL stage gate."""
    if payload.project_id is not None and db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    options = {'top_module': payload.top_module} if payload.top_module is not None else {}
    with acquire_slot():
        try:
            if container_mode():
                result = None
                for event in stream_worker(payload.code, payload.testbench, payload.testbench_top, **options):
                    if event['event'] == 'result':
                        result = event['result']
                if result is None:
                    raise WorkerError('RTL worker returned no result.')
            else:
                result = run_signoff(payload.code, payload.testbench, payload.testbench_top, **options).to_dict()
        except WorkerError as error:
            raise HTTPException(503, str(error)) from None

        run_id = None
        if payload.project_id is not None:
            run_id = _record_rtl_run(db, payload.project_id, result, payload.code, payload.design_revision)

    return {**result, "run_id": run_id}


@router.post("/rtl-signoff/stream")
def rtl_signoff_stream(payload: RtlSignoffRequest, db: Session = Depends(get_db)):
    """Streaming variant: NDJSON progress events as each ladder stage executes
    (stage_start / stage_done per stage, then a final `result` event)."""
    if payload.project_id is not None and db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    try:
        isolated = container_mode()
    except WorkerError as error:
        raise HTTPException(503, str(error)) from None
    options = {'top_module': payload.top_module} if payload.top_module is not None else {}
    cancel = threading.Event()
    def gen():
        events = stream_worker(payload.code, payload.testbench, payload.testbench_top, cancel=cancel, **options) if isolated else stream_signoff(payload.code, payload.testbench, payload.testbench_top, **options)
        try:
            with closing(events):
                for event in events:
                    if cancel.is_set():
                        return
                    if event["event"] == "result" and payload.project_id is not None:
                        session = SessionLocal()
                        try:
                            event["result"]["run_id"] = _record_rtl_run(
                                session, payload.project_id, event["result"], payload.code, payload.design_revision
                            )
                        finally:
                            session.close()
                    yield json.dumps(event) + "\n"
        except WorkerError as error:
            if not cancel.is_set():
                yield json.dumps({'event': 'error', 'detail': str(error)}) + '\n'

    return AdmittedStreamingResponse(gen(), acquire_slot(), on_close=cancel.set)


@router.post('/timing-summary')
def timing_summary(payload: TimingSummaryRequest):
    return screening_result(summarize_corners, **payload.model_dump())


@router.post('/sta-signoff', status_code=201)
def sta_signoff(payload: StaSignoffRequest, db: Session = Depends(get_db)):
    """Execute a fixed OpenSTA flow in an isolated container and capture its evidence."""
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, 'project not found')
    require_project(db, payload.project_id, 'editor')
    with acquire_slot():
        try:
            worker, result, image_id = run_sta(payload.netlist, payload.liberty, payload.sdc, payload.top_module, payload.spef)
        except StaWorkerError as error:
            raise HTTPException(503, str(error)) from None
    user = db.info.get('user')
    return _record_sta_run(db, payload, worker, result, image_id,
                           {'user_id': user.id, 'username': user.username} if user else None)


def _record_sta_run(db, payload, worker, result, image_id, submitted_by):
    result['metadata'] = {'filename': 'server-generated-report.json', 'tool_version': f"OpenSTA {worker['opensta_commit'][:12]}",
                          'scenario': payload.scenario, 'top_module': payload.top_module,
                          'parasitics': 'spef' if payload.spef is not None else 'none'}
    result['execution'] = {'backend': 'container', 'image_id': image_id, 'opensta_commit': worker['opensta_commit'],
                           'agent_involved': False, 'log': worker['log'], 'inputs': worker['inputs']}
    result['input_artifacts'] = worker['inputs']
    result['submitted_by'] = submitted_by
    run = SignoffRun(project_id=payload.project_id, domain=Domain.sta, stage=payload.stage, tool='OpenSTA',
                     status=result['status'], metrics=result['metrics'])
    run.evidence = RunEvidence(source='opensta_execution', source_text=worker['report'],
                               source_sha256=result['source_sha256'], design_revision=payload.design_revision, result=result)
    run.artifacts = [RunArtifact(kind=key, content_text=getattr(payload, key), **metadata)
                     for key, metadata in worker['inputs'].items()]
    for path in result['paths']:
        if path['slack_ps'] is None or path['slack_ps'] < 0:
            run.violations.append(Violation(
                check_name=f"opensta/{path['path_type']}/{path['fingerprint'][:32]}",
                severity=Severity.warning if path['slack_ps'] is None else Severity.error,
                location=path['endpoint'],
                description=f"{payload.scenario} · {path['path_group']} · {path['startpoint']} → {path['endpoint']}\n" +
                            ('Unconstrained path' if path['slack_ps'] is None else f"Reported slack: {slack_text(path['slack_ps'])} ps")))
    db.add(run)
    db.commit()
    return {'run_id': run.id, **result}


@router.post('/sta-signoff/stream')
def sta_signoff_stream(payload: StaSignoffRequest, db: Session = Depends(get_db)):
    """Stream OpenSTA lifecycle events and cancel the worker on disconnect."""
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, 'project not found')
    require_project(db, payload.project_id, 'editor')
    user = db.info.get('user')
    submitted_by = {'user_id': user.id, 'username': user.username} if user else None
    cancel = threading.Event()

    def gen():
        yield json.dumps({'event': 'stage_start', 'stage': 'opensta'}) + '\n'
        try:
            worker, result, image_id = run_sta(payload.netlist, payload.liberty, payload.sdc,
                                                payload.top_module, payload.spef, cancel=cancel)
            if cancel.is_set():
                return
            yield json.dumps({'event': 'stage_done', 'stage': 'opensta', 'status': 'pass',
                              'detail': f"OpenSTA reported {result['metrics']['reported_paths']} paths."}) + '\n'
            yield json.dumps({'event': 'stage_start', 'stage': 'persist'}) + '\n'
            session = SessionLocal()
            try:
                recorded = _record_sta_run(session, payload, worker, result, image_id, submitted_by)
            finally:
                session.close()
            if not cancel.is_set():
                yield json.dumps({'event': 'stage_done', 'stage': 'persist', 'status': 'pass',
                                  'detail': f"Recorded run #{recorded['run_id']}."}) + '\n'
                yield json.dumps({'event': 'result', 'result': recorded}) + '\n'
        except StaWorkerError as error:
            if not cancel.is_set():
                yield json.dumps({'event': 'error', 'detail': str(error)}) + '\n'
        except Exception:
            if not cancel.is_set():
                yield json.dumps({'event': 'error', 'detail': 'STA result could not be recorded.'}) + '\n'

    return AdmittedStreamingResponse(gen(), acquire_slot(), on_close=cancel.set)


@router.post('/sta-signoff/batch/stream')
def sta_signoff_batch_stream(payload: StaBatchRequest, db: Session = Depends(get_db)):
    """Run bounded MCMM-style scenarios sequentially, preserving each as an independent run."""
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, 'project not found')
    require_project(db, payload.project_id, 'editor')
    user = db.info.get('user')
    submitted_by = {'user_id': user.id, 'username': user.username} if user else None
    cancel = threading.Event()

    def gen():
        completed, failed = [], []
        yield json.dumps({'event': 'batch_start', 'total': len(payload.scenarios)}) + '\n'
        for index, scenario in enumerate(payload.scenarios):
            if cancel.is_set():
                return
            name = scenario.scenario.strip()
            yield json.dumps({'event': 'scenario_start', 'index': index, 'scenario': name}) + '\n'
            single = StaSignoffRequest(
                project_id=payload.project_id, stage=payload.stage, top_module=payload.top_module,
                design_revision=payload.design_revision, scenario=name, netlist=payload.netlist,
                liberty=scenario.liberty, sdc=scenario.sdc, spef=scenario.spef,
            )
            try:
                worker, result, image_id = run_sta(single.netlist, single.liberty, single.sdc,
                                                    single.top_module, single.spef, cancel=cancel)
                if cancel.is_set():
                    return
                session = SessionLocal()
                try:
                    recorded = _record_sta_run(session, single, worker, result, image_id, submitted_by)
                finally:
                    session.close()
                completed.append({'scenario': name, 'run_id': recorded['run_id'],
                                  'status': recorded['status']})
                yield json.dumps({'event': 'scenario_done', 'index': index, 'scenario': name,
                                  'result': recorded}) + '\n'
            except StaWorkerError as error:
                if cancel.is_set():
                    return
                failed.append({'scenario': name, 'detail': str(error)})
                yield json.dumps({'event': 'scenario_error', 'index': index, 'scenario': name,
                                  'detail': str(error)}) + '\n'
            except Exception as error:
                logger.error('sta_batch_persist_failed project_id=%s scenario_index=%s failure=%s',
                             payload.project_id, index, type(error).__name__)
                failed.append({'scenario': name, 'detail': 'STA result could not be recorded.'})
                yield json.dumps({'event': 'scenario_error', 'index': index, 'scenario': name,
                                  'detail': 'STA result could not be recorded.'}) + '\n'
        if not cancel.is_set():
            yield json.dumps({'event': 'batch_done', 'total': len(payload.scenarios),
                              'completed': completed, 'failed': failed}) + '\n'

    return AdmittedStreamingResponse(gen(), acquire_slot(), on_close=cancel.set)
