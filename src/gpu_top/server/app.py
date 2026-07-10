"""FastAPI application factory: wires config, database, routers and the SPA."""
import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import api, auth, ingest
from .db import Database

log = logging.getLogger("gpu_top.server")
STATIC_DIR = Path(__file__).parent / "static"


def create_app(config) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.db = Database(config.db_path)

        async def prune_loop():
            while True:
                try:
                    removed = app.state.db.prune(config.retention_days)
                    if removed:
                        log.info("pruned %d samples older than %g days",
                                 removed, config.retention_days)
                except Exception:
                    log.exception("retention pruning failed")
                await asyncio.sleep(3600)

        task = asyncio.create_task(prune_loop())
        yield
        task.cancel()
        app.state.db.close()

    app = FastAPI(title="gpu-top server", lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(ingest.router)
    app.include_router(api.router)

    index = STATIC_DIR / "index.html"
    if index.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        # SPA fallback: any non-API path serves index.html so client-side
        # routes and hard refreshes work.
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = STATIC_DIR / path
            if path and ".." not in path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)
    else:
        @app.get("/", include_in_schema=False)
        def no_ui():
            return {"detail": "web UI not built; run `npm run build` in web/ "
                              "and copy dist/ to gpu_top/server/static/"}

    return app
