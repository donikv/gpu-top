#!/usr/bin/env python3
"""gpu-top: htop-style live GPU monitor with docker container attribution.

Keys:
  Up/Down or j/k        select process
  Enter / double-click  toggle detail pane for selected process
  g                     filter graphs to selected process's GPU
  Esc                   close detail pane
  q                     quit
"""
import argparse
import curses
import os
import pwd
import re
import subprocess
import time
from collections import deque

GPU_FIELDS = [
    "index", "name", "temperature.gpu", "utilization.gpu", "utilization.memory",
    "memory.used", "memory.total", "power.draw", "power.limit", "fan.speed",
]
PROC_FIELDS = ["pid", "process_name", "used_memory", "gpu_uuid"]
HISTORY_MAXLEN = 600
CID_RE = re.compile(r"[0-9a-f]{64}")
HOME_RE = re.compile(r"/home/([A-Za-z0-9._-]+)")
GPU_COLOR_PALETTE = [
    curses.COLOR_CYAN, curses.COLOR_MAGENTA, curses.COLOR_GREEN,
    curses.COLOR_YELLOW, curses.COLOR_BLUE, curses.COLOR_RED, curses.COLOR_WHITE,
]
DETAIL_HEIGHT = 6  # rows incl. separator


# --------------------------------------------------------------------------- data

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


# ------------------------------------------------------------------------ drawing

def gpu_color_pair(position):
    return 10 + (position % len(GPU_COLOR_PALETTE))


def put(win, y, x, text, attr=0):
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_graph(win, y0, x0, height, width, title, series, colors_by_key, maxy, maxx):
    """series: list of (key, label, values 0..100 oldest-first). Returns next free y."""
    if height < 4 or y0 + height + 2 >= maxy or width < 12:
        return y0

    put(win, y0, x0, title[: max(0, maxx - x0 - 1)], curses.A_BOLD)
    lx = x0 + len(title) + 2
    for key, label, values in series:
        cur = values[-1] if values else 0.0
        text = f" {label} {cur:5.1f}%"
        if lx + len(text) >= maxx:
            break
        put(win, y0, lx, text, curses.color_pair(colors_by_key[key]) | curses.A_BOLD)
        lx += len(text)

    label_w = 5
    plot_y0, plot_x0 = y0 + 1, x0 + label_w
    plot_w = min(width, maxx - plot_x0 - 1)
    if plot_w < 5:
        return y0 + height + 2

    for frac, lbl in ((0.0, "100"), (0.5, " 50"), (1.0, "  0")):
        ry = plot_y0 + int(frac * (height - 1))
        put(win, ry, x0, lbl)
        put(win, ry, plot_x0 - 1, "┤" if ry != plot_y0 + height - 1 else "┴")

    def row_for(val):
        val = max(0.0, min(100.0, val))
        return int(round((100.0 - val) / 100.0 * (height - 1)))

    for key, label, values in series:
        vals = list(values)[-plot_w:]
        color = curses.color_pair(colors_by_key[key])
        offset = plot_w - len(vals)
        prev_row = None
        for i, v in enumerate(vals):
            col = plot_x0 + offset + i
            row = row_for(v)
            lo, hi = (row, row) if prev_row is None else (min(prev_row, row), max(prev_row, row))
            for r in range(lo, hi + 1):
                put(win, plot_y0 + r, col, "•" if r == row else "│", color)
            prev_row = row

    return plot_y0 + height + 1


def draw_proc_table(win, y, y_limit, maxx, procs, sel, colors_by_key):
    """Returns (next_y, {screen_row: proc_index}) for mouse hit-testing."""
    row_map = {}
    if y >= y_limit - 1:
        return y, row_map
    put(win, y, 0, f"{'PID':<8}{'USER':<11}{'CONTAINER':<22}{'GPU':<4}{'MEM(MiB)':<10}PROCESS",
        curses.A_UNDERLINE)
    y += 1
    for i, p in enumerate(procs):
        if y >= y_limit:
            break
        line = (f"{p['pid']:<8}{p['user'][:10]:<11}{p['container'][:21]:<22}"
                f"{p['gpu']:<4}{p['mem']:<10}{p['name']}")
        attr = curses.A_REVERSE if i == sel else 0
        if p["gpu"] in colors_by_key and i != sel:
            attr |= curses.color_pair(colors_by_key[p["gpu"]])
        put(win, y, 0, line[: maxx - 1].ljust(maxx - 1), attr)
        row_map[y] = i
        y += 1
    return y, row_map


def draw_detail(win, proc, info, maxy, maxx):
    y0 = maxy - DETAIL_HEIGHT
    try:
        win.hline(y0, 0, curses.ACS_HLINE, maxx)
    except curses.error:
        pass
    cid = proc["cid"][:12] if proc["cid"] else "-"
    lines = [
        f"PID {proc['pid']}  user {proc['user']}  GPU {proc['gpu']}  "
        f"mem {proc['mem']} MiB  container {info['name']} ({cid})  owner {info['owner'] or '-'}",
        f"cmd:    {cmdline(int(proc['pid'])) or proc['name']}",
        f"binds:  {info['binds'] or '-'}",
        f"labels: {info['labels'] or '-'}",
        "Esc: close   g: filter graphs to this GPU",
    ]
    for i, ln in enumerate(lines):
        if y0 + 1 + i < maxy:
            attr = curses.A_DIM if i == len(lines) - 1 else 0
            put(win, y0 + 1 + i, 0, ln[: maxx - 1], attr)


# --------------------------------------------------------------------------- main

def main(stdscr, interval, graph_height):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    for i, color in enumerate(GPU_COLOR_PALETTE):
        curses.init_pair(10 + i, color, -1)
    curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)
    stdscr.timeout(100)  # input poll; data refresh decoupled below

    resolver = ContainerResolver()
    util_hist, mem_hist = {}, {}
    gpus, procs, err = [], [], None
    last_fetch = 0.0
    sel, selected_pid = 0, None
    detail = False
    filter_graphs = False
    row_map = {}

    while True:
        now = time.monotonic()
        if now - last_fetch >= interval:
            last_fetch = now
            try:
                gpus = get_gpus()
                procs = get_processes(get_uuid_map(), resolver)
                err = None
            except Exception as e:
                gpus, procs, err = [], [], str(e)
            for g in gpus:
                idx = g["index"]
                util_hist.setdefault(idx, deque(maxlen=HISTORY_MAXLEN)).append(safe_float(g["util"]))
                mem_hist.setdefault(idx, deque(maxlen=HISTORY_MAXLEN)).append(
                    g["memused"] / g["memtotal"] * 100)
            procs.sort(key=lambda p: -safe_float(p["mem"]))

        # keep selection pinned to a pid across refreshes
        pids = [p["pid"] for p in procs]
        if selected_pid in pids:
            sel = pids.index(selected_pid)
        elif procs:
            sel = min(sel, len(procs) - 1)
            selected_pid = procs[sel]["pid"]
        else:
            sel, selected_pid, detail = 0, None, False
        selp = procs[sel] if procs else None

        stdscr.erase()
        maxy, maxx = stdscr.getmaxyx()
        y = 0
        put(stdscr, y, 0,
            f"gpu-top  (refresh {interval:.1f}s, q quit, Enter detail)  {time.strftime('%H:%M:%S')}",
            curses.A_BOLD)
        y += 2
        if err:
            put(stdscr, y, 0, f"nvidia-smi error: {err}")
            y += 2

        colors_by_key = {g["index"]: gpu_color_pair(i) for i, g in enumerate(gpus)}
        shown = gpus
        if filter_graphs and selp and selp["gpu"] != "?":
            shown = [g for g in gpus if g["index"] == selp["gpu"]] or gpus

        for g in shown:
            if y >= maxy - 1:
                break
            hdr = (f"GPU{g['index']}: {g['name']}  {g['temp']}C  "
                   f"{g['pdraw']}/{g['plimit']}W  fan {g['fan']}%  "
                   f"{g['memused']:.0f}/{g['memtotal']:.0f} MiB")
            put(stdscr, y, 0, hdr[: maxx - 1],
                curses.color_pair(colors_by_key[g["index"]]) | curses.A_BOLD)
            y += 1
        y += 1

        graph_width = maxx - 8
        util_series = [(g["index"], f"GPU{g['index']}", util_hist.get(g["index"], [])) for g in shown]
        mem_series = [(g["index"], f"GPU{g['index']}", mem_hist.get(g["index"], [])) for g in shown]
        y = draw_graph(stdscr, y, 0, graph_height, graph_width, "Utilization %",
                       util_series, colors_by_key, maxy, maxx)
        y = draw_graph(stdscr, y, 0, graph_height, graph_width, "Memory %",
                       mem_series, colors_by_key, maxy, maxx)

        table_limit = maxy - (DETAIL_HEIGHT if detail else 0) - 1
        y, row_map = draw_proc_table(stdscr, y, table_limit, maxx, procs, sel, colors_by_key)

        if detail and selp:
            draw_detail(stdscr, selp, resolver.info(selp["cid"]), maxy, maxx)

        stdscr.refresh()

        key = stdscr.getch()
        if key == -1:
            continue
        if key in (ord("q"), ord("Q")):
            break
        elif key == 27:  # Esc
            if detail:
                detail = False
            else:
                break
        elif key in (curses.KEY_DOWN, ord("j")) and procs:
            sel = min(sel + 1, len(procs) - 1)
            selected_pid = procs[sel]["pid"]
        elif key in (curses.KEY_UP, ord("k")) and procs:
            sel = max(sel - 1, 0)
            selected_pid = procs[sel]["pid"]
        elif key in (curses.KEY_ENTER, 10, 13) and procs:
            detail = not detail
        elif key == ord("g"):
            filter_graphs = not filter_graphs
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if my in row_map:
                sel = row_map[my]
                selected_pid = procs[sel]["pid"]
                if bstate & curses.BUTTON1_DOUBLE_CLICKED:
                    detail = not detail


def cli():
    parser = argparse.ArgumentParser(
        prog="gpu-top",
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--interval", type=float, default=0.5,
                        help="data refresh interval in seconds (default: 0.5)")
    parser.add_argument("-H", "--graph-height", type=int, default=8,
                        help="rows per graph (default: 8)")
    args = parser.parse_args()
    try:
        curses.wrapper(main, args.interval, args.graph_height)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
