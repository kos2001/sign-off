import hmac
import logging
import time
import uuid

from fastapi import FastAPI, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from .auth import authorize, auth_required

from .db import Base, engine, SessionLocal
from .migrations import initialize_schema
from .metrics import Metrics, configured_token
from .request_limits import RequestBodyError, cache_limited_body, configured_request_limit
from .worker_maintenance import worker_lifespan
from .worker_readiness import WorkerReadiness
from .services.rtl.worker_client import WorkerError
from .services.rtl.admission import capacity
from .services.sta_admission import capacity as sta_capacity
from .services.coverage_attestation import validate_optional_configuration
from .review_capacity import capacity as review_capacity
from .routers import cdc, collectors, dft, lec, low_power, lvs, markers, power_integrity, regressions, releases, run_reviews, auth, agents, analysis, comparison, imports, projects, runs, sta_batches, sta_matrix, timing_paths, violations

logger = logging.getLogger('uvicorn.error.signoff')


def create_app() -> FastAPI:
    auth_required()  # Reject misspelled auth modes instead of silently disabling protection.
    configured_token()  # Reject weak scrape credentials before opening the service.
    request_limit = configured_request_limit()
    capacity()
    sta_capacity()
    review_capacity()
    validate_optional_configuration()
    initialize_schema(engine)
    app = FastAPI(
        lifespan=worker_lifespan,
        title="Sign-off Hub API",
        version="0.1.0",
        description=(
            "Backend for managing chip-design sign-off: per-domain signoff runs "
            "(RTL / STA / EM-IR / DRC / LVS / LEC / CDC-RDC / DFT / low power / glitch power / thermal), violation and waiver "
            "tracking, shift-left stage gates, and fast pre-signoff analysis "
            "endpoints (IR-drop screening, vectorless glitch power, MMMC timing "
            "summary)."
        ),
    )
    app.state.metrics = Metrics()
    app.include_router(projects.router, dependencies=[Depends(authorize)])
    app.include_router(collectors.router, dependencies=[Depends(authorize)])
    app.state.worker_readiness = WorkerReadiness()
    app.include_router(runs.router, dependencies=[Depends(authorize)])
    app.include_router(releases.router, dependencies=[Depends(authorize)])
    app.include_router(violations.router, dependencies=[Depends(authorize)])
    app.include_router(comparison.router, dependencies=[Depends(authorize)])
    app.include_router(sta_matrix.router, dependencies=[Depends(authorize)])
    app.include_router(sta_batches.router, dependencies=[Depends(authorize)])
    app.include_router(imports.router, dependencies=[Depends(authorize)])
    app.include_router(timing_paths.router, dependencies=[Depends(authorize)])
    app.include_router(markers.router, dependencies=[Depends(authorize)])
    app.include_router(power_integrity.router, dependencies=[Depends(authorize)])
    app.include_router(regressions.router, dependencies=[Depends(authorize)])
    app.include_router(lvs.router, dependencies=[Depends(authorize)])
    app.include_router(lec.router, dependencies=[Depends(authorize)])
    app.include_router(cdc.router, dependencies=[Depends(authorize)])
    app.include_router(dft.router, dependencies=[Depends(authorize)])
    app.include_router(low_power.router, dependencies=[Depends(authorize)])
    app.include_router(analysis.router, dependencies=[Depends(authorize)])
    app.include_router(run_reviews.router, dependencies=[Depends(authorize)])
    app.include_router(agents.router, dependencies=[Depends(authorize)])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith(('/auth/', '/analysis/')):
            return JSONResponse(status_code=422, content={"detail": [
                {key: item[key] for key in ['loc', 'msg', 'type']} for item in error.errors()
            ]})
        return await request_validation_exception_handler(request, error)

    @app.middleware("http")
    async def private_responses(request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        app.state.metrics.start_request()
        try:
            try:
                await cache_limited_body(request, request_limit)
            except RequestBodyError as error:
                response = JSONResponse(
                    status_code=error.status_code, content={'detail': error.detail},
                    headers={'Cache-Control': 'no-store'},
                )
            else:
                response = await call_next(request)
        except Exception as error:
            logger.error('request_failed request_id=%s failure=%s', request_id, type(error).__name__)
            response = JSONResponse(status_code=500, content={'detail': 'internal server error', 'request_id': request_id})
        response.headers['X-Request-ID'] = request_id
        if auth_required():
            response.headers["Cache-Control"] = "no-store"
        if response.status_code >= 500:
            response.headers['Cache-Control'] = 'no-store'
        route = getattr(request.scope.get('route'), 'path', 'unmatched')
        elapsed = time.monotonic() - started
        app.state.metrics.finish_request(request.method[:16], route, response.status_code, elapsed)
        logger.info('response_headers request_id=%s method=%s route=%s status=%s elapsed_ms=%.2f',
                    request_id, request.method[:16], route, response.status_code, elapsed * 1000)
        return response

    app.include_router(auth.router)
    app.include_router(auth.members_router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    @app.get('/ready', tags=['meta'])
    def readiness(request: Request):
        component = 'database'
        try:
            with SessionLocal() as db:
                # Resolve every required column, without fetching design data or
                # large report payloads. Metadata tracks future model additions.
                for table in Base.metadata.sorted_tables:
                    db.execute(select(table).limit(0)).close()
            component = 'rtl_worker'
            if not app.state.worker_readiness.ready():
                raise WorkerError('RTL worker prerequisite is unavailable.')
        except Exception as error:
            app.state.metrics.readiness('not_ready', component)
            logger.warning('readiness_failed request_id=%s component=%s failure=%s',
                           request.state.request_id, component, type(error).__name__)
            return JSONResponse(status_code=503, content={'status': 'not_ready'}, headers={'Cache-Control': 'no-store', 'Retry-After': '5'})
        app.state.metrics.readiness('ready', 'all')
        return JSONResponse(content={'status': 'ready'}, headers={'Cache-Control': 'no-store'})

    @app.get('/metrics', tags=['meta'])
    def metrics(request: Request):
        token = configured_token()
        if token is None:
            return JSONResponse(status_code=404, content={'detail': 'not found'})
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied, f'Bearer {token}'):
            return JSONResponse(
                status_code=401,
                content={'detail': 'metrics authentication required'},
                headers={'Cache-Control': 'no-store', 'WWW-Authenticate': 'Bearer'},
            )
        return Response(
            app.state.metrics.render(),
            media_type='text/plain; version=0.0.4',
            headers={'Cache-Control': 'no-store'},
        )

    return app


app = create_app()
