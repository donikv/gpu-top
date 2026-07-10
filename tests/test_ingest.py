"""API tests: ingest token auth, payload validation, session auth on UI routes."""
import time

import pytest
from fastapi.testclient import TestClient

from gpu_top.config import ServerConfig
from gpu_top.server.app import create_app

TOKEN = "test-token"


@pytest.fixture
def client(tmp_path):
    config = ServerConfig(
        db_path=str(tmp_path / "test.db"),
        session_secret="test-secret",
        agent_tokens=[TOKEN],
        auth_mode="none",
    )
    with TestClient(create_app(config)) as c:
        yield c


def payload(server="hydra1"):
    return {
        "server": server,
        "agent_version": "0.2.0",
        "samples": [{
            "ts": time.time(),
            "gpus": [{"index": 0, "name": "FAKE", "util_pct": 42.0,
                      "mem_used_mib": 100.0, "mem_total_mib": 200.0}],
            "processes": [],
        }],
    }


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def login(client):
    r = client.post("/api/login", json={"username": "dev", "password": "x"})
    assert r.status_code == 200


def test_ingest_ok(client):
    r = client.post("/api/ingest", json=payload(), headers=auth())
    assert r.status_code == 200
    assert r.json() == {"accepted": 1}


def test_ingest_bad_token(client):
    assert client.post("/api/ingest", json=payload(),
                       headers=auth("wrong")).status_code == 401
    assert client.post("/api/ingest", json=payload()).status_code == 401


def test_ingest_malformed(client):
    r = client.post("/api/ingest", json={"server": "x", "samples": [{"nope": 1}]},
                    headers=auth())
    assert r.status_code == 422


def test_ui_routes_require_session(client):
    for path in ("/api/current", "/api/servers", "/api/me"):
        assert client.get(path).status_code == 401


def test_full_flow(client):
    client.post("/api/ingest", json=payload(), headers=auth())
    login(client)
    servers = client.get("/api/servers").json()
    assert servers[0]["name"] == "hydra1"
    current = client.get("/api/current").json()
    assert current["servers"][0]["gpus"][0]["util_pct"] == 42.0
    # optional/missing gpu fields (temp_c etc.) default to null
    assert current["servers"][0]["gpus"][0]["temp_c"] is None
    hist = client.get("/api/history",
                      params={"server": "hydra1", "gpu": 0, "minutes": 5}).json()
    assert len(hist["points"]) == 1


def test_login_rejects_empty_password(client):
    r = client.post("/api/login", json={"username": "dev", "password": ""})
    assert r.status_code == 401


def test_logout(client):
    login(client)
    assert client.get("/api/me").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
