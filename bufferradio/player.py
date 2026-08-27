"""Playback thread: decode segments with ffmpeg and play via sounddevice."""

from __future__ import annotations

import logging
import subprocess
import threading

import sounddevice as sd

from .buffer import Segment, SegmentBuffer

log = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * 2  # s16le

# How long to keep waiting for a registered segment's bytes before giving up
# and playing silence in its place.
DATA_GRACE_S = 2.0
POLL_S = 0.2


def decode(data: bytes) -> bytes | None:
    """Decode one media segment to raw 48 kHz stereo s16le PCM via ffmpeg.

    Fixed output format regardless of the source stream, so the audio device
    never has to be reconfigured mid-playback.
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0",
         "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1"],
        input=data, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        log.warning("ffmpeg decode failed: %s", proc.stderr.decode(errors="replace").strip())
        return None
    return proc.stdout


def silence(duration: float) -> bytes:
    return bytes(int(duration * SAMPLE_RATE) * BYTES_PER_FRAME)


class Player(threading.Thread):
    """Plays segments in sequence order, sitting `delay` behind the live edge.

    The blocking sounddevice write paces playback: each write returns only
    when the device has consumed enough audio to accept more, so no manual
    sleep-based timing is needed.
    """

    def __init__(self, buffer: SegmentBuffer, start_seq: int) -> None:
        super().__init__(name="player", daemon=True)
        self._buffer = buffer
        self.pos = start_seq
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16")
        stream.start()
        try:
            while not self._stop.is_set():
                self._play_next(stream)
        finally:
            stream.stop()
            stream.close()

    def _play_next(self, stream: sd.RawOutputStream) -> None:
        seg = self._wait_for_segment()
        if seg is None:
            return  # stopping
        pcm = decode(seg.data) if seg.data is not None else None
        if pcm is None:
            log.warning("gap: playing %.1fs of silence for segment %d", seg.duration, seg.seq)
            pcm = silence(seg.duration)
        stream.write(pcm)
        self.pos += 1

    def _wait_for_segment(self) -> Segment | None:
        """Block until segment self.pos has data, its grace expires, or we stop."""
        waited = 0.0
        while not self._stop.is_set():
            seg = self._buffer.get(self.pos)
            if seg is not None and seg.data is not None:
                return seg
            if seg is None:
                waited = 0.0  # not listed yet: we are at the live edge, keep waiting
            elif waited >= DATA_GRACE_S:
                return seg  # listed but bytes never arrived: caller plays silence
            self._stop.wait(POLL_S)
            waited += POLL_S
        return None
