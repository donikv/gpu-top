"""Storage tests: ingest, staleness, retention, downsampling."""
import time

import pytest

from gpu_top.server.db import Database


def sample(ts, util=50.0):
    return {
        "ts": ts,
        "gpus": [{"index": 0, "name": "FAKE", "uuid": "GPU-x", "temp_c": 60.0,
                  "util_pct": util, "mem_util_pct": 40.0, "mem_used_mib": 1000.0,
                  "mem_total_mib": 2000.0, "power_w": 200.0,
                  "power_limit_w": 400.0, "fan_pct": None}],
        "processes": [{"pid": 1, "name": "python", "gpu_index": 0,
                       "mem_mib": 900.0, "user": "alice", "container": "c",
                       "owner": "alice"}],
    }


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    yield d
    d.close()


def test_ingest_and_current(db):
    now = time.time()
    assert db.ingest("hydra1", "0.2.0", [sample(now - 5), sample(now)], now) == 2
    (srv,) = db.current(stale_after=30.0)
    assert srv["name"] == "hydra1"
    assert not srv["stale"]
    assert srv["gpus"][0]["util_pct"] == 50.0
    assert srv["gpus"][0]["fan_pct"] is None
    assert srv["processes"][0]["user"] == "alice"


def test_staleness(db):
    old = time.time() - 120
    db.ingest("hydra1", "0.2.0", [sample(old)], received_at=old)
    (srv,) = db.current(stale_after=30.0)
    assert srv["stale"]


def test_skewed_agent_clock_anchored_to_server_time(db):
    now = time.time()
    # agent clock 2h BEHIND: newest sample must be stored at received_at, and
    # the 5s spacing of the backlog preserved (else charts show empty windows)
    behind = now - 7200
    db.ingest("hydra1", "0.2.0", [sample(behind - 5), sample(behind)], received_at=now)
    (srv,) = db.current(stale_after=30.0)
    assert srv["gpus"][0]["ts"] == pytest.approx(now)
    rows, _, _ = db.history("hydra1", 0, minutes=1, points=60)
    assert len(rows) == 2                # both samples inside the 1min window

    # agent clock ahead: also anchored back to received_at
    db.ingest("hydra2", "0.2.0", [sample(now + 9999)], received_at=now)
    srv2 = [s for s in db.current(stale_after=30.0) if s["name"] == "hydra2"][0]
    assert srv2["gpus"][0]["ts"] == pytest.approx(now)


def test_retention(db):
    now = time.time()
    db.ingest("hydra1", "0.2.0", [sample(now - 10 * 86400)], now - 10 * 86400)
    db.ingest("hydra1", "0.2.0", [sample(now)], now)
    assert db.prune(retention_days=7) == 1
    rows, _, _ = db.history("hydra1", 0, minutes=60 * 24 * 31, points=300)
    assert len(rows) == 1


def test_history_downsampled(db):
    now = time.time()
    samples = [sample(now - i, util=float(i % 100)) for i in range(600)]
    db.ingest("hydra1", "0.2.0", samples, now)
    rows, since, until = db.history("hydra1", 0, minutes=10, points=50)
    assert 2 <= len(rows) <= 51          # bucketed, not one row per sample
    assert all(p["mem_pct"] == 50.0 for p in rows)  # 1000/2000 MiB
    assert since < until <= time.time()  # requested window bounds for the UI


def test_history_unknown_server(db):
    assert db.history("nope", 0, 60, 300) is None


def test_servers_natural_order(db):
    now = time.time()
    for name in ("zver10", "hydra2", "zver2", "hydra", "zver1"):
        db.ingest(name, "0.2.0", [sample(now)], now)
    names = [s["name"] for s in db.list_servers()]
    assert names == ["hydra", "hydra2", "zver1", "zver2", "zver10"]
    assert [s["name"] for s in db.current(30.0)] == names
