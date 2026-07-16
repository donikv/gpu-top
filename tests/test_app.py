"""Tests for cookie Secure flag, proxy config, and the SPA fallback."""
from gpu_top.config import ServerConfig
from gpu_top.server import app as appmod
from fastapi.testclient import TestClient


def make_client(tmp_path, **cfg_kwargs):
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text("INDEX")
    (tmp_path / "robots.txt").write_text("ROBOTS")
    appmod.STATIC_DIR = tmp_path
    cfg = ServerConfig(
        db_path=str(tmp_path / "t.db"), session_secret="s",
        agent_tokens=["t"], auth_mode="none", **cfg_kwargs,
    )
    # TestClient as a context manager runs the lifespan (sets app.state.*).
    return TestClient(appmod.create_app(cfg))


def login_cookie(client):
    r = client.post("/api/login", json={"username": "dev", "password": "x"})
    return r.headers.get("set-cookie", "")


def test_cookie_secure_always(tmp_path):
    with make_client(tmp_path, cookie_secure="always") as c:
        assert "Secure" in login_cookie(c)      # even though TestClient is http


def test_cookie_secure_never(tmp_path):
    with make_client(tmp_path, cookie_secure="never") as c:
        assert "Secure" not in login_cookie(c)


def test_cookie_secure_auto_is_insecure_over_http(tmp_path):
    with make_client(tmp_path, cookie_secure="auto") as c:
        assert "Secure" not in login_cookie(c)   # http request -> no Secure


def test_cookie_flags_present(tmp_path):
    with make_client(tmp_path) as c:
        cookie = login_cookie(c).lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie


def test_unknown_api_path_returns_404_json(tmp_path):
    with make_client(tmp_path) as c:
        r = c.get("/api/does-not-exist")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


def test_spa_serves_index_for_client_routes(tmp_path):
    with make_client(tmp_path) as c:
        assert c.get("/some/client/route").text == "INDEX"


def test_spa_serves_real_static_file(tmp_path):
    with make_client(tmp_path) as c:
        assert c.get("/robots.txt").text == "ROBOTS"
