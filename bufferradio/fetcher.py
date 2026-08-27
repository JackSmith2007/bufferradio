"""Playlist polling and segment downloading (asyncio + httpx)."""

from __future__ import annotations

import asyncio
import logging

import httpx
import m3u8

from .buffer import SegmentBuffer

log = logging.getLogger(__name__)

DEFAULT_TARGET_DURATION = 6.0
MAX_BACKOFF_S = 10.0


async def fetch_playlist(client: httpx.AsyncClient, url: str) -> m3u8.M3U8:
    resp = await client.get(url)
    resp.raise_for_status()
    return m3u8.loads(resp.text, uri=url)


async def select_media_playlist(client: httpx.AsyncClient, url: str) -> str:
    """Resolve a master playlist to its highest-bandwidth variant URL.

    If the URL is already a media playlist, return it unchanged.
    """
    playlist = await fetch_playlist(client, url)
    if not playlist.playlists:
        return url
    best = max(playlist.playlists, key=lambda p: p.stream_info.bandwidth or 0)
    log.info("selected variant: %s bps", best.stream_info.bandwidth)
    return best.absolute_uri


def register_playlist(playlist: m3u8.M3U8, buffer: SegmentBuffer) -> dict[int, str]:
    """Register every listed segment; return seq -> segment URL for downloading."""
    urls: dict[int, str] = {}
    first_seq = playlist.media_sequence or 0
    for i, seg in enumerate(playlist.segments):
        seq = first_seq + i
        buffer.register(seq, seg.duration)
        urls[seq] = seg.absolute_uri
    return urls


async def poll_once(client: httpx.AsyncClient, media_url: str, buffer: SegmentBuffer) -> m3u8.M3U8:
    """One fetch cycle: read the playlist, then download every listed segment we lack.

    "Download everything listed that we don't have yet" is also the backfill
    path: after an outage the missed segments are simply still un-stored, and
    get picked up here as long as the server still lists them. Segments the
    player has already passed are below the buffer's floor, so register()
    ignores them and they are never downloaded.

    A playlist failure propagates (the caller backs off); a single segment
    failure is logged and left for the next poll.
    """
    playlist = await fetch_playlist(client, media_url)
    urls = register_playlist(playlist, buffer)
    for seq in sorted(urls):  # oldest first: closest to the playhead, most urgent
        seg = buffer.get(seq)
        if seg is None or seg.data is not None:
            continue
        try:
            resp = await client.get(urls[seq])
            resp.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            log.warning("segment %d download failed: %s", seq, exc)
            continue
        buffer.store(seq, resp.content)
        log.debug("stored segment %d (%d bytes)", seq, len(resp.content))
    return playlist


async def run_fetcher(client: httpx.AsyncClient, media_url: str, buffer: SegmentBuffer) -> None:
    """Poll forever, with exponential backoff while the playlist is unreachable."""
    backoff = 1.0
    while True:
        try:
            playlist = await poll_once(client, media_url, buffer)
        except (httpx.HTTPError, OSError) as exc:
            log.warning("playlist fetch failed: %s (retrying in %.1fs)", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue
        backoff = 1.0
        target = playlist.target_duration or DEFAULT_TARGET_DURATION
        await asyncio.sleep(target / 2)
