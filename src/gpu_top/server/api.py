"""Browser-facing read API. Every route requires a logged-in session."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/api/servers")
def servers(request: Request):
    return request.app.state.db.list_servers()


@router.get("/api/current")
def current(request: Request):
    cfg = request.app.state.config
    return {"servers": request.app.state.db.current(stale_after=cfg.stale_after)}


@router.get("/api/history")
def history(
    request: Request,
    server: str,
    gpu: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24 * 31),
    points: int = Query(default=300, ge=2, le=2000),
):
    result = request.app.state.db.history(server, gpu, minutes, points)
    if result is None:
        raise HTTPException(status_code=404, detail=f"unknown server {server!r}")
    rows, since, until = result
    # since/until = the requested window, so the UI can position partial data
    # at the correct spot instead of stretching it to full width.
    return {"points": rows, "since": since, "until": until}
