"""Player tests with a fake output stream; ffmpeg is only needed for the decode test."""

from __future__ import annotations

import io
import shutil
import wave

import pytest

from bufferradio import player as player_module
from bufferradio.buffer import SegmentBuffer
from bufferradio.metrics import Metrics
from bufferradio.player import BYTES_PER_FRAME, CHUNK_BYTES, SAMPLE_RATE, Player, decode, silence


class FakeStream:
    """Stands in for sd.RawOutputStream: records what would have been played."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    @property
    def played(self) -> bytes:
        return b"".join(self.writes)


def fake_pcm(seconds: float) -> bytes:
    return b"\x01\x00" * (int(seconds * SAMPLE_RATE) * 2)  # non-zero, so it isn't silence


@pytest.fixture
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(player_module, "decode", lambda data: fake_pcm(1.0))


def make_player(buf: SegmentBuffer, start_seq: int, metrics: Metrics | None = None) -> Player:
    return Player(buf, start_seq, metrics or Metrics(None), grace_s=0.0)


def test_silence_has_exact_length() -> None:
    pcm = silence(1.5)
    assert len(pcm) == int(1.5 * SAMPLE_RATE) * BYTES_PER_FRAME
    assert not any(pcm)


def test_plays_stored_segment_then_evicts_it(no_ffmpeg: None) -> None:
    buf, metrics, stream = SegmentBuffer(), Metrics(None), FakeStream()
    buf.register(7, 1.0)
    buf.store(7, b"encoded audio")
    player = make_player(buf, 7, metrics)

    player._play_next(stream)

    assert stream.played == fake_pcm(1.0)
    assert player.pos == 8
    assert buf.get(7) is None  # evicted: never needed again
    assert metrics.counts["played"] == 1


def test_missing_segment_becomes_exact_length_silence(no_ffmpeg: None) -> None:
    buf, metrics, stream = SegmentBuffer(), Metrics(None), FakeStream()
    buf.register(7, 0.5)  # listed but the bytes never arrived
    player = make_player(buf, 7, metrics)

    player._play_next(stream)

    assert stream.played == silence(0.5)
    assert player.pos == 8
    assert metrics.counts["gap"] == 1
    assert metrics.silence_ms == 500


def test_skips_ahead_when_position_expired_from_server() -> None:
    buf, metrics = SegmentBuffer(), Metrics(None)
    buf.register(12, 10.0)  # newer segment listed, but 10 and 11 never were
    buf.store(12, b"x")
    player = make_player(buf, 10, metrics)

    seg = player._wait_for_segment()

    assert seg is not None and seg.seq == 12
    assert player.pos == 12
    assert metrics.counts["skip"] == 1


def test_stop_unblocks_waiting_for_the_live_edge() -> None:
    player = make_player(SegmentBuffer(), 10)
    player.stop()
    assert player._wait_for_segment() is None


def test_writes_in_chunks_and_stops_between_them(no_ffmpeg: None) -> None:
    buf, stream = SegmentBuffer(), FakeStream()
    buf.register(1, 1.0)
    buf.store(1, b"x")
    player = make_player(buf, 1)
    stream.write = lambda data: (stream.writes.append(data), player.stop())  # type: ignore[assignment]

    player._play_next(stream)

    assert len(stream.writes) == 1
    assert len(stream.writes[0]) == CHUNK_BYTES
    assert player.pos == 1  # interrupted: not counted as played


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_decode_resamples_to_48k_stereo() -> None:
    # 0.5 s of 44.1 kHz mono: output must be resampled to the fixed device format.
    src = io.BytesIO()
    with wave.open(src, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x10" * (44100 // 2))
    pcm = decode(src.getvalue())
    assert pcm is not None
    expected = int(0.5 * SAMPLE_RATE) * BYTES_PER_FRAME
    assert abs(len(pcm) - expected) < expected * 0.02


def test_decode_failure_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    assert decode(b"this is not audio") is None
    assert "decode failed" in caplog.text
