"""Shared data-collection layer: nvidia-smi queries + docker container attribution.

Used by both the local TUI (gpu_top.tui) and the push agent (gpu_top.agent).
Must never import curses.
"""
import os
import pwd
import re
import subprocess
import time

GPU_FIELDS = [
    "index", "name", "temperature.gpu", "utilization.gpu", "utilization.memory",
    "memory.used", "memory.total", "power.draw", "power.limit", "fan.speed",
]
PROC_FIELDS = ["pid", "process_name", "used_memory", "gpu_uuid"]
CID_RE = re.compile(r"[0-9a-f]{64}")
HOME_RE = re.compile(r"/home/([A-Za-z0-9._-]+)")


def run_query(fields, mode="gpu"):
    flag = "--query-gpu" if mode == "gpu" else "--query-compute-apps"
    out = subprocess.run(
        ["nvidia-smi", f"{flag}={','.join(fields)}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )
    if out.returncode != 0:
        return []
    return [[p.strip() for p in line.split(",")]
            for line in out.stdout.strip().splitlines() if line.strip()]


def get_gpus():
    gpus = []
    for row in run_query(GPU_FIELDS):
        idx, name, temp, util, memutil, memused, memtotal, pdraw, plimit, fan = row
        gpus.append(dict(
            index=idx, name=name, temp=temp, util=util, memutil=memutil,
            memused=safe_float(memused), memtotal=safe_float(memtotal, 1),
            pdraw=pdraw, plimit=plimit, fan=fan,
        ))
    return gpus


def get_uuid_map():
    return {r[1]: r[0] for r in run_query(["index", "uuid"]) if len(r) == 2}


def username(pid):
    try:
        return pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
    except Exception:
        return "?"


def proc_name(pid, fallback):
    if fallback != "[Not Found]":
        return fallback
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip() or fallback
    except OSError:
        return fallback


def cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


class ContainerResolver:
    """PID -> container id via /proc/<pid>/cgroup, then batched+cached docker inspect."""

    def __init__(self):
        self.pid_cid = {}   # pid -> cid | None
        self.cid_info = {}  # cid -> dict(name, owner, binds, labels)
        self.docker_ok = True

    def cid_for(self, pid):
        if pid not in self.pid_cid:
            cid = None
            try:
                with open(f"/proc/{pid}/cgroup") as f:
                    m = CID_RE.search(f.read())
                cid = m.group(0) if m else None
            except OSError:
                pass
            self.pid_cid[pid] = cid
        return self.pid_cid[pid]

    def refresh(self, cids):
        missing = [c for c in cids if c and c not in self.cid_info]
        if not missing or not self.docker_ok:
            return
        fmt = ("{{.Id}}\t{{.Name}}"
               "\t{{range .HostConfig.Binds}}{{.}} {{end}}"
               "\t{{range $k, $v := .Config.Labels}}{{$k}}={{$v}} {{end}}")
        try:
            out = subprocess.run(
                ["docker", "inspect", "--format", fmt, *missing],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.docker_ok = False
            return
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            cid, name, binds, labels = parts
            m = HOME_RE.search(binds)
            self.cid_info[cid] = dict(
                name=name.lstrip("/"), binds=binds.strip(),
                labels=labels.strip(), owner=m.group(1) if m else "",
            )
        for c in missing:  # dead/unknown containers: don't re-inspect every tick
            self.cid_info.setdefault(c, dict(name="?", binds="", labels="", owner=""))

    def info(self, cid):
        if cid is None:
            return dict(name="host", binds="", labels="", owner="")
        return self.cid_info.get(cid, dict(name="?", binds="", labels="", owner=""))


def get_processes(uuid_to_index, resolver):
    rows = [r for r in run_query(PROC_FIELDS, mode="compute-apps") if len(r) == 4]
    cids = set()
    procs = []
    for pid, pname, used_mem, uuid in rows:
        cid = resolver.cid_for(pid)
        cids.add(cid)
        procs.append(dict(
            pid=pid, name=proc_name(pid, pname), mem=used_mem,
            gpu=uuid_to_index.get(uuid, "?"), user=username(pid), cid=cid,
        ))
    resolver.refresh(cids)
    for p in procs:
        p["container"] = resolver.info(p["cid"])["name"]
        p["owner"] = resolver.info(p["cid"])["owner"]
    return procs


def safe_float(s, default=0.0):
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


# ------------------------------------------------------------- typed snapshots

def _num(s):
    """nvidia-smi numeric field -> float, or None for '[N/A]' and friends."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _int(s, default=-1):
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def collect_snapshot(resolver=None):
    """One fully typed sample of all GPUs + processes, ready for JSON transport.

    Unlike get_gpus()/get_processes() (which keep nvidia-smi's raw strings for
    the TUI), every numeric field is a float/int and '[N/A]' becomes None.
    """
    if resolver is None:
        resolver = ContainerResolver()
    gpus = []
    for g in get_gpus():
        gpus.append(dict(
            index=_int(g["index"]),
            name=g["name"],
            temp_c=_num(g["temp"]),
            util_pct=_num(g["util"]),
            mem_util_pct=_num(g["memutil"]),
            mem_used_mib=g["memused"],
            mem_total_mib=g["memtotal"],
            power_w=_num(g["pdraw"]),
            power_limit_w=_num(g["plimit"]),
            fan_pct=_num(g["fan"]),
        ))
    uuid_map = get_uuid_map()
    # attach uuids to gpus by index
    index_to_uuid = {_int(v): k for k, v in uuid_map.items()}
    for g in gpus:
        g["uuid"] = index_to_uuid.get(g["index"], "")
    processes = []
    for p in get_processes(uuid_map, resolver):
        processes.append(dict(
            pid=_int(p["pid"]),
            name=p["name"],
            gpu_index=_int(p["gpu"]),
            mem_mib=_num(p["mem"]),
            user=p["user"],
            container=p["container"],
            owner=p["owner"],
        ))
    return dict(ts=time.time(), gpus=gpus, processes=processes)
