"""One playback session: open the stream, start the player, run the fetcher.

Shared by the terminal CLI (__main__.py) and the local web front end (web.py).
"""

from __future__ import annotations

import _thread
import logging

import httpx

from .buffer import SegmentBuffer
from .faults import FaultInjector, FaultyTransport, start_key_listener
from .fetcher import fetch_playlist, register_playlist, run_fetcher, select_media_playlist
from .metrics import Metrics
from .player import Player

log = logging.getLogger("bufferradio")


def choose_start_seq(playlist, delay: float) -> int:
    """Newest sequence whose distance to the live edge covers the delay.

    Those segments already exist on the server, so playback can start almost
    immediately while still sitting `delay` seconds behind live.
    """
    first_seq = playlist.media_sequence or 0
    total = 0.0
    for i in range(len(playlist.segments) - 1, -1, -1):
        total += playlist.segments[i].duration
        if total >= delay:
            return first_seq + i
    return first_seq  # delay exceeds the playlist window: start at the oldest


def inject_fault(faults: FaultInjector, seconds: float, metrics: Metrics) -> None:
    log.warning("FAULT: dropping all HTTP requests for %.0fs", seconds)
    faults.trip(seconds)
    metrics.record("fault", duration_ms=seconds * 1000)


def handle_key(key: str, faults: FaultInjector, fault_seconds: float, metrics: Metrics) -> None:
    """Runs on the key-listener thread: `f` injects an outage, `q` quits."""
    if key == "f":
        inject_fault(faults, fault_seconds, metrics)
    elif key == "q":
        _thread.interrupt_main()  # same as Ctrl+C


async def main(url: str, delay: float, fault_seconds: float, metrics: Metrics,
               faults: FaultInjector | None = None, keys: bool = True) -> None:
    """Play `url` until cancelled (Ctrl+C / `q` in the terminal, Stop on the web page)."""
    buffer = SegmentBuffer()
    faults = faults or FaultInjector()
    transport = FaultyTransport(faults, httpx.AsyncHTTPTransport())
    async with httpx.AsyncClient(transport=transport, timeout=10.0, follow_redirects=True) as client:
        media_url = await select_media_playlist(client, url)
        playlist = await fetch_playlist(client, media_url)
        window = sum(s.duration for s in playlist.segments)
        log.info("playlist window: %.0fs (%d segments)", window, len(playlist.segments))
        if delay > window:
            log.warning("delay %.0fs exceeds the playlist window: the server only keeps %.0fs, "
                        "so the effective delay will be about %.0fs", delay, window, window)
        register_playlist(playlist, buffer)
        start_seq = choose_start_seq(playlist, delay)
        buffer.evict_before(start_seq)  # older segments will never be played: don't fetch them
        first_seq = playlist.media_sequence or 0
        behind = sum(s.duration for s in playlist.segments[start_seq - first_seq:])
        log.info("starting playback at sequence %d, %.0fs behind live", start_seq, behind)

        player = Player(buffer, start_seq, metrics)
        player.start()
        if keys:
            start_key_listener(lambda key: handle_key(key, faults, fault_seconds, metrics))
            log.info("press f to inject a %.0fs outage, q to quit", fault_seconds)
        try:
            await run_fetcher(client, media_url, buffer, metrics)
        finally:
            player.stop()
            player.join(timeout=5)
