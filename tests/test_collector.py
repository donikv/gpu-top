"""Parsing tests for the shared collector, using monkeypatched nvidia-smi output."""
from gpu_top import collector


def fake_run_query(rows_by_mode):
    def run_query(fields, mode="gpu"):
        return rows_by_mode.get((mode, tuple(fields)), rows_by_mode.get(mode, []))
    return run_query


GPU_ROW = ["0", "NVIDIA A100", "61", "87", "54", "40120", "81920",
           "312.40", "400.00", "[N/A]"]


def test_get_gpus_keeps_strings_for_tui(monkeypatch):
    monkeypatch.setattr(collector, "run_query", fake_run_query({"gpu": [GPU_ROW]}))
    (g,) = collector.get_gpus()
    assert g["temp"] == "61"            # raw string, as the TUI expects
    assert g["memused"] == 40120.0      # except the two floats it always had
    assert g["fan"] == "[N/A]"


def test_collect_snapshot_typed(monkeypatch):
    uuid = "GPU-abc"
    rows = {
        ("gpu", tuple(collector.GPU_FIELDS)): [GPU_ROW],
        ("gpu", ("index", "uuid")): [["0", uuid]],
        ("compute-apps", tuple(collector.PROC_FIELDS)):
            [["123", "python", "1000", uuid],
             ["456", "[Not Found]", "[N/A]", "GPU-unknown"]],
    }
    monkeypatch.setattr(collector, "run_query", fake_run_query(rows))
    snap = collector.collect_snapshot(resolver=collector.ContainerResolver())

    (g,) = snap["gpus"]
    assert g["index"] == 0
    assert g["temp_c"] == 61.0
    assert g["fan_pct"] is None          # '[N/A]' -> null, not 0
    assert g["uuid"] == uuid

    p1, p2 = snap["processes"]
    assert p1["pid"] == 123 and p1["gpu_index"] == 0 and p1["mem_mib"] == 1000.0
    assert p2["gpu_index"] == -1         # unknown uuid
    assert p2["mem_mib"] is None


def test_safe_float_default():
    assert collector.safe_float("[N/A]") == 0.0
    assert collector.safe_float("2.5") == 2.5
