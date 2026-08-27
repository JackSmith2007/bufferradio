"""Event log for observability: one CSV row per notable event, plus a summary.

Columns: timestamp,event_type,sequence,duration_ms

Event types:
  stored          segment bytes downloaded   (duration_ms = download time)
  played          segment decoded and played (duration_ms = audio length)
  gap             silence played instead     (duration_ms = silence length)
  skip            playhead jumped past segments the server no longer had
  playlist_error  playlist fetch failed      (duration_ms = backoff before retry)
  fault           outage injected by the user (duration_ms = outage length)
"""

from __future__ import annotations

import csv
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

FIELDS = ("timestamp", "event_type", "sequence", "duration_ms")


class Metrics:
    """Appends rows to a CSV file (or nowhere, if path is None) and keeps counts.

    Called from both the player thread and the asyncio loop, hence the lock.
    The file is opened per write: events arrive at most a few times per
    second, and this way nothing is lost if the process is killed.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.counts: Counter[str] = Counter()
        self.silence_ms = 0.0

    def record(self, event_type: str, seq: int | None = None,
               duration_ms: float | None = None) -> None:
        with self._lock:
            self.counts[event_type] += 1
            if event_type == "gap" and duration_ms:
                self.silence_ms += duration_ms
            if self._path is None:
                return
            new_file = not self._path.exists() or self._path.stat().st_size == 0
            with self._path.open("a", newline="") as f:
                writer = csv.writer(f)
                if new_file:
                    writer.writerow(FIELDS)
                writer.writerow([
                    datetime.now().isoformat(timespec="milliseconds"),
                    event_type,
                    "" if seq is None else seq,
                    "" if duration_ms is None else round(duration_ms),
                ])

    def summary(self) -> str:
        c = self.counts
        line = (f"{c['played']} segments played, {c['gap']} gaps "
                f"({self.silence_ms / 1000:.1f}s silence), {c['stored']} downloaded, "
                f"{c['playlist_error']} playlist errors, {c['fault']} faults injected")
        if self._path is not None:
            line += f" -> {self._path}"
        return line
