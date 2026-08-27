# bufferradio

Resume/co-op project: a Python CLI that plays live internet radio (HLS) at a
configurable delay behind the live edge. Because playback lags live, short
network outages are inaudible: the missed segments are re-downloaded from the
server before playback reaches them. Design priority: **simple and idiomatic —
the author must be able to explain every part in a co-op interview.**

## Environment

- Windows 11, PowerShell, PyCharm. All commands must be PowerShell compatible.
- Python **3.14.6** venv at `.venv` (spec originally said 3.12; user approved 3.14).
- ffmpeg required on PATH (`winget install --id Gyan.FFmpeg -e`).

## Usage

```
python -m bufferradio --url <hls_url> --delay 20     # any custom HLS stream
python -m bufferradio --station cbc-radio2           # a verified preset
python -m bufferradio                                # interactive station picker
```

## Architecture

- `__main__.py` — argparse CLI, startup (variant selection, start-sequence
  computation), wiring, clean shutdown.
- `fetcher.py` — asyncio + httpx: polls the media playlist (parsed with m3u8),
  registers listed segments, downloads any it doesn't have. That same path is
  the backfill after an outage. Exponential backoff on playlist failures.
- `buffer.py` — `SegmentBuffer`, thread-safe, keyed by media sequence number.
  **Core idea:** playlist metadata (seq -> duration) is registered separately
  from payload bytes; a registered segment with `data=None` is one the fetcher
  still owes us. This gives exact-length silence for gaps, an explicit
  backfill worklist, and network-free tests.
- `player.py` — separate thread. Decodes each segment to fixed 48 kHz stereo
  s16le PCM via a short-lived ffmpeg subprocess (pipes), outputs with
  sounddevice; the blocking write paces playback. Missing segment -> silence
  for its duration, never a crash.
- `stations.py` — preset name -> master URL dict + terminal picker. Only
  verified-working URLs may be added.
- `faults.py` (M3) — pressing `f` drops all HTTP requests for N s (default 5).
- `metrics.py` (M3) — appends events to `metrics.csv`
  (`timestamp,event_type,sequence,duration_ms`); summary line on exit.

## Decisions log

- Variant selection: highest bandwidth from the master playlist.
- Delay positioning: start at the newest sequence whose summed duration to the
  live edge >= delay (segments already on the server -> fast start).
- Per-segment ffmpeg subprocess (not one long-lived pipe): simpler, and gap
  handling stays trivial.
- Preset streams verified 2026-08-26; playlist windows are short (~28-30 s),
  so delays much above ~25 s exceed what the server retains (M2 warns).
- M5 (optional, after M4): thin Tkinter GUI (dropdown of presets + custom URL
  box) reusing the same core; no new dependencies.

## Conventions

- Dependencies: only httpx, m3u8, sounddevice (pinned in requirements.txt).
  Any addition must be justified to the user first. (pytest proposed as
  dev-only for M4 in requirements-dev.txt.)
- Type hints, small functions, no over-engineering; brief comments only where
  logic is non-obvious.
- Milestones M1-M4 (see git history), one at a time, user approval between
  each; commit per approved milestone, never push.

## Milestone status

- M1: plays stream at configured delay, station presets + picker. **Done**
  (audio acceptance passed 2026-08-26 on cbc-radio2, ffmpeg 9.0.1).
- M2: backfill hardening, eviction, playlist-window warning. **Done.**
- M3: fault injector (`f` key) + metrics.csv. **Done** (verified: 5 s
  outage at 20 s delay recovers with zero gaps).
- M4: unit tests (fake fetcher, no network) + README. Not started.
