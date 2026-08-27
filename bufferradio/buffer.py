"""In-memory segment buffer keyed by HLS media sequence number."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class Segment:
    seq: int
    duration: float           # seconds, from the playlist
    data: bytes | None        # None = listed in the playlist but not downloaded yet
    arrived_at: float | None  # time.monotonic() when the bytes were stored


class SegmentBuffer:
    """Thread-safe store shared by the asyncio fetcher and the player thread.

    Playlist metadata is tracked separately from payload bytes: register()
    records that a segment exists (with its duration), store() adds its bytes
    later. A registered segment with data=None is one the fetcher still owes
    us -- the player can substitute exact-length silence, and the fetcher
    knows to backfill it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._segments: dict[int, Segment] = {}

    def register(self, seq: int, duration: float) -> None:
        with self._lock:
            if seq not in self._segments:
                self._segments[seq] = Segment(seq, duration, None, None)

    def store(self, seq: int, data: bytes) -> None:
        with self._lock:
            seg = self._segments.get(seq)
            if seg is not None and seg.data is None:
                seg.data = data
                seg.arrived_at = time.monotonic()

    def get(self, seq: int) -> Segment | None:
        with self._lock:
            return self._segments.get(seq)

    def latest_seq(self) -> int | None:
        with self._lock:
            return max(self._segments) if self._segments else None
