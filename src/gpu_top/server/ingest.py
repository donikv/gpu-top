"""Agent-facing ingest endpoint: POST /api/ingest with a bearer token.

The pydantic models below are the formal wire schema for agent pushes.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


class GpuReading(BaseModel):
    index: int
    name: str
    uuid: str = ""
    temp_c: float | None = None
    util_pct: float | None = None
    mem_util_pct: float | None = None
    mem_used_mib: float | None = None
    mem_total_mib: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    fan_pct: float | None = None


class ProcessReading(BaseModel):
    pid: int
    name: str = ""
    gpu_index: int = -1
    mem_mib: float | None = None
    user: str = ""
    container: str = ""
    owner: str = ""


class Sample(BaseModel):
    ts: float
    gpus: list[GpuReading]
    processes: list[ProcessReading] = Field(default_factory=list)


class IngestPayload(BaseModel):
    server: str = Field(min_length=1, max_length=100)
    agent_version: str = ""
    samples: list[Sample] = Field(max_length=1000)


def require_agent_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    if creds is not None:
        # compare against every configured token in constant time
        supplied = creds.credentials
        for token in request.app.state.config.agent_tokens:
            if secrets.compare_digest(supplied, token):
                return
    raise HTTPException(status_code=401, detail="invalid or missing agent token")


@router.post("/api/ingest", dependencies=[Depends(require_agent_token)])
def ingest(payload: IngestPayload, request: Request):
    accepted = request.app.state.db.ingest(
        server_name=payload.server,
        agent_version=payload.agent_version,
        samples=[s.model_dump() for s in payload.samples],
        received_at=time.time(),
    )
    return {"accepted": accepted}
