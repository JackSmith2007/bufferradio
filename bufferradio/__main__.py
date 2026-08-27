"""CLI entry point: python -m bufferradio [--url URL | --station NAME] [--delay S] [--web]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx

from .app import main
from .ffmpeg_setup import ffmpeg_exe
from .metrics import Metrics
from .stations import STATIONS, pick_station

log = logging.getLogger("bufferradio")


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="bufferradio",
        description="Play live HLS internet radio delayed behind the live edge.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", help="master or media HLS playlist URL")
    group.add_argument("--station", choices=sorted(STATIONS), help="play a preset station")
    group.add_argument("--web", action="store_true",
                       help="control playback from a web page at http://127.0.0.1:8765")
    parser.add_argument("--delay", type=float, default=20.0,
                        help="seconds behind live (default: 20)")
    parser.add_argument("--fault-seconds", type=float, default=5.0,
                        help="length of the outage injected by the f key (default: 5)")
    parser.add_argument("--metrics-file", type=Path, default=Path("metrics.csv"),
                        help="CSV file to append events to (default: metrics.csv)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request lines are noise
    try:
        log.debug("ffmpeg: %s", ffmpeg_exe())  # fail fast, before any audio starts
    except RuntimeError as exc:
        sys.exit(str(exc))

    if args.web:
        from .web import serve
        serve(args.metrics_file, args.fault_seconds, args.delay)
        return

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
