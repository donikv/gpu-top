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


def test_future_timestamps_clamped(db):
    now = time.time()
    db.ingest("hydra1", "0.2.0", [sample(now + 9999)], received_at=now)
    (srv,) = db.current(stale_after=30.0)
    assert srv["gpus"][0]["ts"] <= now


def test_retention(db):
    now = time.time()
    db.ingest("hydra1", "0.2.0", [sample(now - 10 * 86400), sample(now)], now)
    assert db.prune(retention_days=7) == 1
    points = db.history("hydra1", 0, minutes=60 * 24 * 31, points=300)
    assert len(points) == 1


def test_history_downsampled(db):
    now = time.time()
    samples = [sample(now - i, util=float(i % 100)) for i in range(600)]
    db.ingest("hydra1", "0.2.0", samples, now)
    points = db.history("hydra1", 0, minutes=10, points=50)
    assert 2 <= len(points) <= 51        # bucketed, not one row per sample
    assert all(p["mem_pct"] == 50.0 for p in points)  # 1000/2000 MiB


def test_history_unknown_server(db):
    assert db.history("nope", 0, 60, 300) is None
