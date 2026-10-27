"""FastAPI application factory for the TPAgent web UI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tpagent import __version__
from tpagent.tools.files import allow_outside_cwd

from .api import router as api_router
from .runtime import RuntimeRegistry
from .sessions import SessionStore
from .settings import Settings
from .ws import router as ws_router

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    allow_outside_cwd(settings.config.allow_outside_cwd)
    app = FastAPI(title="TPAgent Web", version=__version__, docs_url=None, redoc_url=None)
    store = SessionStore(settings)
    app.state.settings = settings
    app.state.store = store
    app.state.registry = RuntimeRegistry(store, settings)
    app.include_router(api_router)
    app.include_router(ws_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
