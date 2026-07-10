"""TOML config loading for the agent and the server.

Secrets can be supplied via environment variables instead of the file:
  GPU_TOP_AGENT_TOKEN      -> [agent].token
  GPU_TOP_SERVICE_PASSWORD -> [auth.ldap].service_password
  GPU_TOP_SESSION_SECRET   -> [server].session_secret
"""
import os
import tomllib
from dataclasses import dataclass, field


class ConfigError(SystemExit):
    """Bad or missing config: exit with a readable message, no traceback."""

    def __init__(self, msg):
        super().__init__(f"gpu-top config error: {msg}")


def _load_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}")


def _require(section, key, where):
    if key not in section:
        raise ConfigError(f"missing required key '{key}' in [{where}]")
    return section[key]


@dataclass
class AgentConfig:
    server_name: str
    url: str
    token: str
    interval: float = 5.0


def load_agent_config(path):
    data = _load_toml(path)
    agent = data.get("agent")
    if not isinstance(agent, dict):
        raise ConfigError(f"{path} must contain an [agent] section")
    token = os.environ.get("GPU_TOP_AGENT_TOKEN") or agent.get("token")
    if not token:
        raise ConfigError("set [agent].token or the GPU_TOP_AGENT_TOKEN env var")
    return AgentConfig(
        server_name=_require(agent, "server_name", "agent"),
        url=str(_require(agent, "url", "agent")).rstrip("/"),
        token=token,
        interval=float(agent.get("interval", 5.0)),
    )


@dataclass
class LdapConfig:
    uri: str
    service_dn: str
    service_password: str
    base_dn: str
    user_filter: str = "(uid={username})"
    starttls: bool = False       # upgrade a ldap:// connection to TLS before binding
    tls_verify: bool = True      # False = accept any certificate (TLS_REQCERT allow)


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "gpu-top.db"
    retention_days: float = 7.0
    session_secret: str = ""
    session_hours: float = 12.0
    stale_after: float = 30.0
    agent_tokens: list = field(default_factory=list)
    auth_mode: str = "ldap"          # "ldap" | "none" (dev only)
    ldap: LdapConfig | None = None


def load_server_config(path):
    data = _load_toml(path)
    srv = data.get("server", {})
    auth = data.get("auth", {})
    mode = auth.get("mode", "ldap")
    if mode not in ("ldap", "none"):
        raise ConfigError(f"[auth].mode must be 'ldap' or 'none', got {mode!r}")
    if mode == "none" and os.environ.get("GPU_TOP_DEV") != "1":
        raise ConfigError(
            "auth.mode='none' disables login entirely; it is for local development "
            "only. Set GPU_TOP_DEV=1 in the environment if you really want this.")

    session_secret = os.environ.get("GPU_TOP_SESSION_SECRET") or srv.get("session_secret")
    if not session_secret:
        raise ConfigError(
            "set [server].session_secret (generate one with: "
            "python -c 'import secrets; print(secrets.token_hex(32))') "
            "or the GPU_TOP_SESSION_SECRET env var")

    tokens = data.get("agents", {}).get("tokens", [])
    if not tokens:
        raise ConfigError("set at least one token in [agents].tokens")

    ldap = None
    if mode == "ldap":
        lc = auth.get("ldap")
        if not isinstance(lc, dict):
            raise ConfigError("auth.mode='ldap' requires an [auth.ldap] section")
        password = os.environ.get("GPU_TOP_SERVICE_PASSWORD") or lc.get("service_password")
        if not password:
            raise ConfigError(
                "set [auth.ldap].service_password or the GPU_TOP_SERVICE_PASSWORD env var")
        ldap = LdapConfig(
            uri=_require(lc, "uri", "auth.ldap"),
            service_dn=_require(lc, "service_dn", "auth.ldap"),
            service_password=password,
            base_dn=_require(lc, "base_dn", "auth.ldap"),
            user_filter=lc.get("user_filter", "(uid={username})"),
            starttls=bool(lc.get("starttls", False)),
            tls_verify=bool(lc.get("tls_verify", True)),
        )

    return ServerConfig(
        host=srv.get("host", "0.0.0.0"),
        port=int(srv.get("port", 8000)),
        db_path=srv.get("db_path", "gpu-top.db"),
        retention_days=float(srv.get("retention_days", 7.0)),
        session_secret=session_secret,
        session_hours=float(srv.get("session_hours", 12.0)),
        stale_after=float(srv.get("stale_after", 30.0)),
        agent_tokens=list(tokens),
        auth_mode=mode,
        ldap=ldap,
    )
