from fastapi import FastAPI

from .db import Base, engine
from .routers import agents, analysis, projects, runs


def create_app() -> FastAPI:
    Base.metadata.create_all(engine)
    app = FastAPI(
        title="Sign-off Hub API",
        version="0.1.0",
        description=(
            "Backend for managing chip-design sign-off: per-domain signoff runs "
            "(STA / EM-IR / PV / glitch power / thermal), violation and waiver "
            "tracking, shift-left stage gates, and fast pre-signoff analysis "
            "endpoints (IR-drop screening, vectorless glitch power, MMMC timing "
            "summary)."
        ),
    )
    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(analysis.router)
    app.include_router(agents.router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
