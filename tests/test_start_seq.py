import m3u8
import pytest

from bufferradio.app import choose_start_seq

# Three 10 s segments, sequences 100-102, so the window is 30 s.
PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:100
#EXTINF:10.0,
seg100.aac
#EXTINF:10.0,
seg101.aac
#EXTINF:10.0,
seg102.aac
"""


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (0, 102),    # no delay: newest segment
        (10, 102),   # exactly one segment covers it
        (15, 101),   # needs two segments
        (20, 101),
        (30, 100),   # the whole window
        (45, 100),   # exceeds the window: oldest available (effective delay 30 s)
    ],
)
def test_choose_start_seq(delay: float, expected: int) -> None:
    playlist = m3u8.loads(PLAYLIST)
    assert choose_start_seq(playlist, delay) == expected


def test_missing_media_sequence_defaults_to_zero() -> None:
    playlist = m3u8.loads(PLAYLIST.replace("#EXT-X-MEDIA-SEQUENCE:100\n", ""))
    assert choose_start_seq(playlist, 15) == 1
