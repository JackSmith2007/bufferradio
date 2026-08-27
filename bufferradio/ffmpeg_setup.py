"""Locate the ffmpeg binary.

ffmpeg is the one thing this program needs that isn't Python. Rather than ask
users to install it, we depend on ``imageio-ffmpeg``, a pip package whose only
job is to ship a prebuilt ffmpeg binary for the current OS (Windows, macOS
Intel/Apple Silicon, Linux). A system ffmpeg on PATH is the fallback.
"""

from __future__ import annotations

import functools
import shutil

import imageio_ffmpeg

INSTALL_HINT = ("no ffmpeg available for this platform; install it and make sure it is on PATH "
                "(Windows: winget install --id Gyan.FFmpeg -e, macOS: brew install ffmpeg, "
                "Linux: sudo apt install ffmpeg)")


@functools.cache
def ffmpeg_exe() -> str:
    """Path to a working ffmpeg binary. Raises RuntimeError if there is none."""
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        path = shutil.which("ffmpeg")
        if path is None:
            raise RuntimeError(INSTALL_HINT) from None
        return path
