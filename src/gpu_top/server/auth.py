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


def _cookie_secure(request: Request) -> bool:
    """Whether to set the Secure flag on the session cookie.

    'auto' trusts request.url.scheme (correct once uvicorn honors the proxy's
    X-Forwarded-Proto, i.e. server.behind_proxy = true); 'always'/'never' pin it
    for setups where scheme detection can't be trusted."""
    mode = request.app.state.config.cookie_secure
    if mode == "always":
        return True
    if mode == "never":
        return False
    return request.url.scheme == "https"


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
    import ssl

    import ldap3
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    # tls_verify=False mirrors OpenLDAP's `TLS_REQCERT allow` (self-signed or
    # unvalidated certs); applies to both ldaps:// and STARTTLS connections.
    # ca_cert_file, when set, validates against a specific CA bundle instead of
    # the system trust store.
    tls = ldap3.Tls(
        validate=ssl.CERT_REQUIRED if cfg.tls_verify else ssl.CERT_NONE,
        ca_certs_file=cfg.ca_cert_file or None)
    server = ldap3.Server(cfg.uri, connect_timeout=5, tls=tls)
    # STARTTLS upgrades a plain ldap:// connection to TLS before any bind is
    # sent (the equivalent of pam_ldap's `ssl start_tls` / nixos useTLS).
    auto_bind = (ldap3.AUTO_BIND_TLS_BEFORE_BIND if cfg.starttls
                 else ldap3.AUTO_BIND_NO_TLS)
    try:
        with ldap3.Connection(
            server, user=cfg.service_dn, password=cfg.service_password,
            auto_bind=auto_bind, receive_timeout=5,
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
            auto_bind=auto_bind, receive_timeout=5,
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
        secure=_cookie_secure(request),
    )
    return {"user": user}


@router.post("/api/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE)


@router.get("/api/me")
def me(user: str = Depends(require_user)):
    return {"user": user}
