from __future__ import annotations

import os
import subprocess

import pytest

from bufferradio import ffmpeg_setup
from bufferradio.ffmpeg_setup import ffmpeg_exe


def test_bundled_ffmpeg_exists_and_runs() -> None:
    path = ffmpeg_exe()
    assert os.path.isfile(path)
    out = subprocess.run([path, "-version"], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.startswith("ffmpeg version")


def test_falls_back_to_system_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    ffmpeg_exe.cache_clear()
    monkeypatch.setattr(ffmpeg_setup.imageio_ffmpeg, "get_ffmpeg_exe",
                        lambda: (_ for _ in ()).throw(RuntimeError("no binary")))
    monkeypatch.setattr(ffmpeg_setup.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    try:
        assert ffmpeg_exe() == "/usr/bin/ffmpeg"
    finally:
        ffmpeg_exe.cache_clear()


def test_clear_error_when_nothing_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    ffmpeg_exe.cache_clear()
    monkeypatch.setattr(ffmpeg_setup.imageio_ffmpeg, "get_ffmpeg_exe",
                        lambda: (_ for _ in ()).throw(RuntimeError("no binary")))
    monkeypatch.setattr(ffmpeg_setup.shutil, "which", lambda name: None)
    try:
        with pytest.raises(RuntimeError, match="install it"):
            ffmpeg_exe()
    finally:
        ffmpeg_exe.cache_clear()
