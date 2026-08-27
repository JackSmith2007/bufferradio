from __future__ import annotations

import csv
from pathlib import Path

from bufferradio.metrics import FIELDS, Metrics


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_writes_header_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    metrics = Metrics(path)
    metrics.record("stored", 42, 123.4)
    metrics.record("gap", 43, 2500)
    metrics.record("fault", duration_ms=5000)

    rows = read_rows(path)
    assert list(rows[0]) == list(FIELDS)
    assert [(r["event_type"], r["sequence"], r["duration_ms"]) for r in rows] == [
        ("stored", "42", "123"),
        ("gap", "43", "2500"),
        ("fault", "", "5000"),
    ]
    assert all(r["timestamp"] for r in rows)


def test_appends_across_runs_with_a_single_header(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    Metrics(path).record("played", 1, 10000)
    Metrics(path).record("played", 2, 10000)
    lines = path.read_text().splitlines()
    assert len(lines) == 3
    assert lines[0] == ",".join(FIELDS)


def test_summary_counts_and_silence(tmp_path: Path) -> None:
    metrics = Metrics(tmp_path / "m.csv")
    for seq in range(3):
        metrics.record("played", seq, 10000)
    metrics.record("gap", 3, 1500)
    metrics.record("gap", 4, 1000)
    metrics.record("playlist_error", duration_ms=1000)
    metrics.record("fault", duration_ms=5000)
    summary = metrics.summary()
    assert "3 segments played" in summary
    assert "2 gaps (2.5s silence)" in summary
    assert "1 playlist errors" in summary
    assert "1 faults injected" in summary
    assert "m.csv" in summary


def test_no_path_counts_only(tmp_path: Path) -> None:
    metrics = Metrics(None)
    metrics.record("stored", 1, 100)
    assert metrics.counts["stored"] == 1
    assert list(tmp_path.iterdir()) == []
    assert "->" not in metrics.summary()
