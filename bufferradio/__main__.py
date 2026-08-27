"""CLI entry point: python -m bufferradio [--url URL | --station NAME] [--delay S]"""

from __future__ import annotations

import _thread
import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

import httpx

from .buffer import SegmentBuffer
from .faults import FaultInjector, FaultyTransport, start_key_listener
from .fetcher import fetch_playlist, register_playlist, run_fetcher, select_media_playlist
from .metrics import Metrics
from .player import Player
from .stations import STATIONS, pick_station

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


def handle_key(key: str, faults: FaultInjector, fault_seconds: float, metrics: Metrics) -> None:
    """Runs on the key-listener thread: `f` injects an outage, `q` quits."""
    if key == "f":
        log.warning("FAULT: dropping all HTTP requests for %.0fs", fault_seconds)
        faults.trip(fault_seconds)
        metrics.record("fault", duration_ms=fault_seconds * 1000)
    elif key == "q":
        _thread.interrupt_main()  # same as Ctrl+C


async def main(url: str, delay: float, fault_seconds: float, metrics: Metrics) -> None:
    buffer = SegmentBuffer()
    faults = FaultInjector()
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
        start_key_listener(lambda key: handle_key(key, faults, fault_seconds, metrics))
        log.info("press f to inject a %.0fs outage, q to quit", fault_seconds)
        try:
            await run_fetcher(client, media_url, buffer, metrics)
        finally:
            player.stop()
            player.join(timeout=5)


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="bufferradio",
        description="Play live HLS internet radio delayed behind the live edge.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", help="master or media HLS playlist URL")
    group.add_argument("--station", choices=sorted(STATIONS), help="play a preset station")
    parser.add_argument("--delay", type=float, default=20.0,
                        help="seconds behind live (default: 20)")
    parser.add_argument("--fault-seconds", type=float, default=5.0,
                        help="length of the outage injected by the f key (default: 5)")
    parser.add_argument("--metrics-file", type=Path, default=Path("metrics.csv"),
                        help="CSV file to append events to (default: metrics.csv)")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it with:\n"
                 "  winget install --id Gyan.FFmpeg -e\n"
                 "then restart the terminal.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request lines are noise
    url = args.url or (STATIONS[args.station] if args.station else pick_station())
    metrics = Metrics(args.metrics_file)
    try:
        asyncio.run(main(url, args.delay, args.fault_seconds, metrics))
    except KeyboardInterrupt:
        pass
    except httpx.HTTPError as exc:
        sys.exit(f"could not open stream: {exc}")
    finally:
        log.info("summary: %s", metrics.summary())


if __name__ == "__main__":
    cli()
