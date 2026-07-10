"""Web-UI authentication: LDAP search+bind, signed-cookie sessions.

Flow (auth.mode = "ldap"):
  1. bind to the directory as the configured service account
  2. search base_dn with user_filter for the login name (escaped -> no LDAP injection)
  3. exactly one match -> bind again as that DN with the user's password
  4. success -> set a signed, HttpOnly session cookie

auth.mode = "none" (dev only, requires GPU_TOP_DEV=1) accepts anyone as "dev".
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel

log = logging.getLogger("gpu_top.auth")
router = APIRouter()

COOKIE = "gpu_top_session"


class LoginRequest(BaseModel):
    username: str
    password: str


def _signer(request: Request) -> TimestampSigner:
    return TimestampSigner(request.app.state.config.session_secret)


def require_user(request: Request) -> str:
    """FastAPI dependency: return the logged-in username or raise 401."""
    raw = request.cookies.get(COOKIE)
    if raw:
        cfg = request.app.state.config
        try:
            user = _signer(request).unsign(raw, max_age=cfg.session_hours * 3600)
            return user.decode()
        except (BadSignature, SignatureExpired):
            pass
    raise HTTPException(status_code=401, detail="not logged in")


def _ldap_authenticate(cfg, username, password):
    """Blocking search+bind against the directory. Returns True on success."""
    import ldap3
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    server = ldap3.Server(cfg.uri, connect_timeout=5)
    try:
        with ldap3.Connection(
            server, user=cfg.service_dn, password=cfg.service_password,
            auto_bind=True, receive_timeout=5,
        ) as conn:
            conn.search(
                cfg.base_dn,
                cfg.user_filter.format(username=escape_filter_chars(username)),
                attributes=[],
            )
            if len(conn.entries) != 1:
                log.info("login %r: %d directory matches", username, len(conn.entries))
                return False
            user_dn = conn.entries[0].entry_dn
        with ldap3.Connection(
            server, user=user_dn, password=password,
            auto_bind=True, receive_timeout=5,
        ):
            return True
    except LDAPException as e:
        log.info("login %r failed: %s", username, e)
        return False


@router.post("/api/login")
async def login(body: LoginRequest, request: Request, response: Response):
    cfg = request.app.state.config
    username = body.username.strip()
    # An empty password performs an *unauthenticated* bind on many LDAP servers,
    # which "succeeds" without checking anything. Never let it reach the bind.
    if not username or not body.password:
        raise HTTPException(status_code=401, detail="invalid credentials")

    if cfg.auth_mode == "none":
        user = username or "dev"
    else:
        ok = await asyncio.to_thread(_ldap_authenticate, cfg.ldap, username, body.password)
        if not ok:
            raise HTTPException(status_code=401, detail="invalid credentials")
        user = username

    signed = TimestampSigner(cfg.session_secret).sign(user.encode()).decode()
    response.set_cookie(
        COOKIE, signed,
        max_age=int(cfg.session_hours * 3600),
        httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"user": user}


@router.post("/api/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE)


@router.get("/api/me")
def me(user: str = Depends(require_user)):
    return {"user": user}
