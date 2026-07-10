"""SQLite storage for pushed GPU metrics.

Single-process design: one shared connection, writes serialized with a lock.
At one small batch per agent every few seconds this is far below SQLite's
limits; WAL mode lets reads proceed concurrently with writes.
"""
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  last_seen REAL NOT NULL,          -- server-side receive time (agent clocks may skew)
  agent_version TEXT
);

CREATE TABLE IF NOT EXISTS gpu_samples (
  server_id INTEGER NOT NULL REFERENCES servers(id),
  ts REAL NOT NULL,                 -- agent-side sample time
  gpu_index INTEGER NOT NULL,
  gpu_name TEXT, uuid TEXT,
  temp_c REAL, util_pct REAL, mem_util_pct REAL,
  mem_used_mib REAL, mem_total_mib REAL,
  power_w REAL, power_limit_w REAL, fan_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_gpu_samples ON gpu_samples(server_id, gpu_index, ts);

-- Only the latest process snapshot per server is kept (replaced on each push).
CREATE TABLE IF NOT EXISTS current_processes (
  server_id INTEGER NOT NULL REFERENCES servers(id),
  gpu_index INTEGER, pid INTEGER, name TEXT,
  mem_mib REAL, user TEXT, container TEXT, owner TEXT
);
"""


class Database:
    def __init__(self, path):
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------- writes

    def ingest(self, server_name, agent_version, samples, received_at=None):
        """Store a batch of samples pushed by one agent. Returns rows accepted."""
        received_at = received_at if received_at is not None else time.time()
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT id FROM servers WHERE name=?", (server_name,)).fetchone()
            if row:
                sid = row["id"]
                self.conn.execute(
                    "UPDATE servers SET last_seen=?, agent_version=? WHERE id=?",
                    (received_at, agent_version, sid))
            else:
                sid = self.conn.execute(
                    "INSERT INTO servers (name, last_seen, agent_version) VALUES (?,?,?)",
                    (server_name, received_at, agent_version)).lastrowid

            accepted = 0
            for sample in samples:
                # Guard against wildly future agent clocks so staleness/history math
                # stays sane; past timestamps are fine (backlog flush).
                ts = min(sample["ts"], received_at)
                self.conn.executemany(
                    """INSERT INTO gpu_samples (server_id, ts, gpu_index, gpu_name, uuid,
                         temp_c, util_pct, mem_util_pct, mem_used_mib, mem_total_mib,
                         power_w, power_limit_w, fan_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(sid, ts, g["index"], g["name"], g.get("uuid", ""),
                      g["temp_c"], g["util_pct"], g["mem_util_pct"],
                      g["mem_used_mib"], g["mem_total_mib"],
                      g["power_w"], g["power_limit_w"], g["fan_pct"])
                     for g in sample["gpus"]])
                accepted += 1

            # Processes: only the newest sample in the batch matters.
            if samples:
                newest = max(samples, key=lambda s: s["ts"])
                self.conn.execute("DELETE FROM current_processes WHERE server_id=?", (sid,))
                self.conn.executemany(
                    """INSERT INTO current_processes
                         (server_id, gpu_index, pid, name, mem_mib, user, container, owner)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [(sid, p["gpu_index"], p["pid"], p["name"], p["mem_mib"],
                      p["user"], p["container"], p["owner"])
                     for p in newest["processes"]])
            return accepted

    def prune(self, retention_days):
        cutoff = time.time() - retention_days * 86400
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM gpu_samples WHERE ts < ?", (cutoff,))
            return cur.rowcount

    # -------------------------------------------------------------- reads

    def list_servers(self):
        rows = self.conn.execute(
            """SELECT s.name, s.last_seen, s.agent_version,
                      (SELECT COUNT(DISTINCT gpu_index) FROM gpu_samples
                        WHERE server_id = s.id) AS gpu_count
               FROM servers s ORDER BY s.name""").fetchall()
        return [dict(r) for r in rows]

    def current(self, stale_after):
        """Latest sample per server plus staleness, for the dashboard grid."""
        now = time.time()
        out = []
        for srv in self.conn.execute(
                "SELECT id, name, last_seen FROM servers ORDER BY name").fetchall():
            gpus = self.conn.execute(
                """SELECT * FROM gpu_samples
                   WHERE server_id=? AND ts=(SELECT MAX(ts) FROM gpu_samples
                                             WHERE server_id=?)
                   ORDER BY gpu_index""",
                (srv["id"], srv["id"])).fetchall()
            procs = self.conn.execute(
                """SELECT gpu_index, pid, name, mem_mib, user, container, owner
                   FROM current_processes WHERE server_id=?
                   ORDER BY mem_mib DESC""", (srv["id"],)).fetchall()
            out.append(dict(
                name=srv["name"],
                last_seen=srv["last_seen"],
                stale=(now - srv["last_seen"]) > stale_after,
                gpus=[{k: g[k] for k in g.keys() if k != "server_id"} for g in gpus],
                processes=[dict(p) for p in procs],
            ))
        return out

    def history(self, server_name, gpu_index, minutes, points):
        """Time-bucketed averages so the response never exceeds `points` rows."""
        row = self.conn.execute(
            "SELECT id FROM servers WHERE name=?", (server_name,)).fetchone()
        if not row:
            return None
        since = time.time() - minutes * 60
        bucket = max(1.0, minutes * 60 / points)
        rows = self.conn.execute(
            """SELECT CAST(ts / :bucket AS INT) * :bucket AS t,
                      AVG(util_pct) AS util_pct,
                      AVG(CASE WHEN mem_total_mib > 0
                          THEN mem_used_mib / mem_total_mib * 100 END) AS mem_pct,
                      AVG(temp_c) AS temp_c,
                      AVG(power_w) AS power_w
               FROM gpu_samples
               WHERE server_id = :sid AND gpu_index = :gpu AND ts >= :since
               GROUP BY t ORDER BY t""",
            dict(bucket=bucket, sid=row["id"], gpu=gpu_index, since=since)).fetchall()
        return [dict(ts=r["t"], util_pct=r["util_pct"], mem_pct=r["mem_pct"],
                     temp_c=r["temp_c"], power_w=r["power_w"]) for r in rows]
