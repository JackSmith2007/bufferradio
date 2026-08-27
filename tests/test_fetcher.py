"""Fetcher tests against an in-memory fake HLS server (httpx.MockTransport, no network)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from bufferradio.buffer import SegmentBuffer
from bufferradio.fetcher import poll_once, select_media_playlist
from bufferradio.metrics import Metrics

BASE = "https://radio.test/live/"

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=64000,CODECS="mp4a.40.2"
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=192000,CODECS="mp4a.40.2"
high/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=128000,CODECS="mp4a.40.2"
mid/index.m3u8
"""


class FakeServer:
    """Serves a sliding 3-segment media playlist plus the segments themselves."""

    def __init__(self) -> None:
        self.first_seq = 100
        self.failing: set[int] = set()   # segment seqs that return 503
        self.playlist_down = False
        self.requests: list[str] = []

    def playlist(self) -> str:
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:10",
                 f"#EXT-X-MEDIA-SEQUENCE:{self.first_seq}"]
        for seq in range(self.first_seq, self.first_seq + 3):
            lines += ["#EXTINF:10.0,", f"seg{seq}.aac"]
        return "\n".join(lines) + "\n"

    def advance(self) -> None:
        self.first_seq += 1  # live edge moves on; oldest segment drops off

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        if name == "master.m3u8":
            return httpx.Response(200, text=MASTER)
        if name.endswith(".m3u8"):
            return httpx.Response(503 if self.playlist_down else 200, text=self.playlist())
        seq = int(name[len("seg"):-len(".aac")])
        if seq in self.failing:
            return httpx.Response(503)
        return httpx.Response(200, content=f"audio{seq}".encode())

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def poll(server: FakeServer, buf: SegmentBuffer, metrics: Metrics | None = None) -> None:
    async def go() -> None:
        async with server.client() as client:
            await poll_once(client, BASE + "index.m3u8", buf, metrics or Metrics(None))
    asyncio.run(go())


def test_poll_registers_and_downloads_every_listed_segment() -> None:
    server, buf, metrics = FakeServer(), SegmentBuffer(), Metrics(None)
    poll(server, buf, metrics)
    assert [buf.get(s).data for s in (100, 101, 102)] == [b"audio100", b"audio101", b"audio102"]
    assert metrics.counts["stored"] == 3


def test_failed_segment_stays_owed_and_is_backfilled_next_poll() -> None:
    server, buf = FakeServer(), SegmentBuffer()
    server.failing.add(101)
    poll(server, buf)
    assert buf.get(101).data is None           # registered (duration known) but owed
    assert buf.get(101).duration == 10.0
    assert buf.get(102).data == b"audio102"    # one failure doesn't block the rest

    server.failing.clear()
    poll(server, buf)
    assert buf.get(101).data == b"audio101"    # backfilled by the ordinary poll path


def test_already_stored_segments_are_not_downloaded_again() -> None:
    server, buf = FakeServer(), SegmentBuffer()
    poll(server, buf)
    server.requests.clear()
    poll(server, buf)
    assert server.requests == ["index.m3u8"]


def test_evicted_segments_are_never_re_downloaded() -> None:
    server, buf = FakeServer(), SegmentBuffer()
    buf.evict_before(102)  # player has moved past 100 and 101
    poll(server, buf)
    assert server.requests == ["index.m3u8", "seg102.aac"]
    assert buf.get(100) is None


def test_sliding_window_picks_up_new_segments() -> None:
    server, buf = FakeServer(), SegmentBuffer()
    poll(server, buf)
    server.advance()
    poll(server, buf)
    assert buf.get(103).data == b"audio103"
    assert buf.latest_seq() == 103


def test_playlist_failure_propagates_to_the_caller() -> None:
    server, buf = FakeServer(), SegmentBuffer()
    server.playlist_down = True
    with pytest.raises(httpx.HTTPError):
        poll(server, buf)
    assert len(buf) == 0


def test_outage_verdict_when_the_buffer_covered_it(caplog: pytest.LogCaptureFixture) -> None:
    from bufferradio.fetcher import run_fetcher

    server, buf, metrics = FakeServer(), SegmentBuffer(), Metrics(None)
    server.playlist_down = True

    async def go() -> None:
        async with server.client() as client:
            task = asyncio.create_task(run_fetcher(client, BASE + "index.m3u8", buf, metrics))
            await asyncio.sleep(0.2)          # first poll fails, backoff of 1 s begins
            server.playlist_down = False      # "network back" before the retry
            for _ in range(50):
                if "OUTAGE SURVIVED" in caplog.text:
                    break
                await asyncio.sleep(0.1)
            task.cancel()

    caplog.set_level("INFO")
    asyncio.run(go())
    assert "OUTAGE SURVIVED" in caplog.text
    assert "3 segment(s) backfilled" in caplog.text
    assert metrics.counts["playlist_error"] == 1


def test_outage_verdict_when_silence_was_played(caplog: pytest.LogCaptureFixture) -> None:
    from bufferradio.fetcher import run_fetcher

    server, buf, metrics = FakeServer(), SegmentBuffer(), Metrics(None)
    server.playlist_down = True

    async def go() -> None:
        async with server.client() as client:
            task = asyncio.create_task(run_fetcher(client, BASE + "index.m3u8", buf, metrics))
            await asyncio.sleep(0.2)
            metrics.record("gap", 100, 10000)  # the player ran dry during the outage
            server.playlist_down = False
            for _ in range(50):
                if "OUTAGE EXCEEDED BUFFER" in caplog.text:
                    break
                await asyncio.sleep(0.1)
            task.cancel()

    caplog.set_level("INFO")
    asyncio.run(go())
    assert "OUTAGE EXCEEDED BUFFER" in caplog.text
    assert "1 gap(s) of silence" in caplog.text


def test_select_media_playlist_picks_highest_bandwidth() -> None:
    server = FakeServer()

    async def go() -> tuple[str, str]:
        async with server.client() as client:
            from_master = await select_media_playlist(client, BASE + "master.m3u8")
            from_media = await select_media_playlist(client, BASE + "index.m3u8")
            return from_master, from_media

    from_master, from_media = asyncio.run(go())
    assert from_master == BASE + "high/index.m3u8"
    assert from_media == BASE + "index.m3u8"  # already a media playlist: unchanged
