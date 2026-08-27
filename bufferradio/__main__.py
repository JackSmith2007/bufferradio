"""CLI entry point: python -m bufferradio [--url URL | --station NAME] [--delay S]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys

import httpx

from .buffer import SegmentBuffer
from .fetcher import fetch_playlist, register_playlist, run_fetcher, select_media_playlist
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


async def main(url: str, delay: float) -> None:
    buffer = SegmentBuffer()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        media_url = await select_media_playlist(client, url)
        playlist = await fetch_playlist(client, media_url)
        window = sum(s.duration for s in playlist.segments)
        log.info("playlist window: %.0fs (%d segments)", window, len(playlist.segments))
        register_playlist(playlist, buffer)
        start_seq = choose_start_seq(playlist, delay)
        log.info("starting playback at sequence %d, %.0fs behind live", start_seq, delay)

        player = Player(buffer, start_seq)
        player.start()
        try:
            await run_fetcher(client, media_url, buffer)
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
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it with:\n"
                 "  winget install --id Gyan.FFmpeg -e\n"
                 "then restart the terminal.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request lines are noise
    url = args.url or (STATIONS[args.station] if args.station else pick_station())
    try:
        asyncio.run(main(url, args.delay))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
