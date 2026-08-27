"""Make sure ffmpeg is available, downloading it once on Windows if it isn't.

ffmpeg is the only thing this program needs that pip can't install. Rather
than ask users to install it themselves, on Windows we fetch a static build
into the user's app-data folder on first run and put that folder on this
process's PATH. Everything else keeps calling plain ``ffmpeg``.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# LGPL build from the BtbN FFmpeg-Builds project; the asset name is stable.
FFMPEG_ZIP_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                  "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip")

INSTALL_HINT = ("install ffmpeg and make sure it is on your PATH:\n"
                "  Windows: winget install --id Gyan.FFmpeg -e\n"
                "  macOS:   brew install ffmpeg\n"
                "  Linux:   sudo apt install ffmpeg\n"
                "then open a new terminal and run bufferradio again.")


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "bufferradio" / "ffmpeg"


def ensure_ffmpeg() -> bool:
    """Return True once ``ffmpeg`` resolves on PATH, downloading it first if needed."""
    if shutil.which("ffmpeg"):
        return True
    dest = install_dir()
    if not (dest / "ffmpeg.exe").exists():
        if sys.platform != "win32":
            log.error("ffmpeg not found; %s", INSTALL_HINT)
            return False
        log.info("ffmpeg not found; downloading it once into %s", dest)
        try:
            download_ffmpeg(dest)
        except (httpx.HTTPError, OSError, zipfile.BadZipFile) as exc:
            log.error("could not download ffmpeg (%s); %s", exc, INSTALL_HINT)
            return False
    os.environ["PATH"] = str(dest) + os.pathsep + os.environ.get("PATH", "")
    return shutil.which("ffmpeg") is not None


def download_ffmpeg(dest: Path, url: str = FFMPEG_ZIP_URL,
                    client: httpx.Client | None = None) -> None:
    """Download the build zip and unpack just bin/ffmpeg.exe and its DLLs into dest."""
    if client is None:
        with httpx.Client(follow_redirects=True, timeout=60.0) as own_client:
            download_ffmpeg(dest, url, own_client)
        return

    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "ffmpeg.zip"
    with client.stream("GET", url) as resp, archive.open("wb") as f:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = shown = 0
        for chunk in resp.iter_bytes():
            f.write(chunk)
            done += len(chunk)
            if done - shown >= 1_000_000 or done == total:
                _print_progress(done, total)
                shown = done
    print(file=sys.stderr)

    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            folder, _, name = member.rpartition("/")
            if folder.endswith("bin") and (name == "ffmpeg.exe" or name.endswith(".dll")):
                with zf.open(member) as src, (dest / name).open("wb") as out:
                    shutil.copyfileobj(src, out)
    archive.unlink()


def _print_progress(done: int, total: int) -> None:
    mb = done / 1e6
    text = f"{mb:.0f} / {total / 1e6:.0f} MB" if total else f"{mb:.0f} MB"
    print(f"\rdownloading ffmpeg (one-time): {text}", end="", file=sys.stderr, flush=True)
