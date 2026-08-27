"""ffmpeg auto-download tests: the "server" is an in-memory zip behind httpx.MockTransport."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from bufferradio import ffmpeg_setup
from bufferradio.ffmpeg_setup import download_ffmpeg, ensure_ffmpeg


def fake_build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ffmpeg-n9.0-win64/bin/ffmpeg.exe", b"FFMPEG")
        zf.writestr("ffmpeg-n9.0-win64/bin/avcodec-62.dll", b"DLL")
        zf.writestr("ffmpeg-n9.0-win64/bin/ffprobe.exe", b"not needed")
        zf.writestr("ffmpeg-n9.0-win64/doc/README.txt", b"not needed")
    return buf.getvalue()


def zip_client(status: int = 200) -> httpx.Client:
    payload = fake_build_zip()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload,
                              headers={"content-length": str(len(payload))})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_extracts_only_ffmpeg_and_dlls(tmp_path: Path) -> None:
    dest = tmp_path / "ffmpeg"
    with zip_client() as client:
        download_ffmpeg(dest, "https://example.test/ffmpeg.zip", client)
    assert sorted(p.name for p in dest.iterdir()) == ["avcodec-62.dll", "ffmpeg.exe"]
    assert (dest / "ffmpeg.exe").read_bytes() == b"FFMPEG"  # the zip itself was removed


def test_download_failure_raises(tmp_path: Path) -> None:
    with zip_client(status=503) as client, pytest.raises(httpx.HTTPStatusError):
        download_ffmpeg(tmp_path / "ffmpeg", "https://example.test/ffmpeg.zip", client)


def test_ensure_is_a_noop_when_ffmpeg_is_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_setup.shutil, "which", lambda name: "C:/somewhere/ffmpeg.exe")
    monkeypatch.setattr(ffmpeg_setup, "download_ffmpeg", lambda *a, **k: pytest.fail("downloaded"))
    assert ensure_ffmpeg() is True


def test_ensure_gives_up_with_a_hint_off_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(ffmpeg_setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(ffmpeg_setup, "install_dir", lambda: tmp_path / "ffmpeg")
    monkeypatch.setattr(ffmpeg_setup.sys, "platform", "linux")
    assert ensure_ffmpeg() is False
    assert "brew install ffmpeg" in caplog.text


@pytest.mark.skipif(sys.platform != "win32", reason="uses a real .exe lookup on PATH")
def test_ensure_downloads_once_then_uses_the_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dest = tmp_path / "ffmpeg"
    monkeypatch.setattr(ffmpeg_setup, "install_dir", lambda: dest)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # nothing on PATH
    calls: list[Path] = []

    def fake_download(target: Path) -> None:
        calls.append(target)
        target.mkdir(parents=True)
        (target / "ffmpeg.exe").write_bytes(b"FFMPEG")

    monkeypatch.setattr(ffmpeg_setup, "download_ffmpeg", fake_download)

    assert ensure_ffmpeg() is True
    assert calls == [dest]
    assert os.environ["PATH"].startswith(str(dest))
    assert ensure_ffmpeg() is True
    assert calls == [dest]  # second run: already there, no download
