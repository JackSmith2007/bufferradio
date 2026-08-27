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
- `faults.py` — `FaultInjector` + `FaultyTransport` (httpx transport wrapper
  that raises `ConnectError` while tripped, so nothing else knows about
  faults) + key-listener thread: `f` drops all HTTP for `--fault-seconds`
  (default 5), `q` quits via `_thread.interrupt_main()`.
- `metrics.py` — `Metrics(path)` appends `timestamp,event_type,sequence,
  duration_ms` rows (stored/played/gap/skip/playlist_error/fault) to
  `metrics.csv`; summary line on exit. `Metrics(None)` = counts only (tests).
- `tests/` — pytest, no network: fetcher tests run against a `FakeServer`
  over `httpx.MockTransport`; player tests use a fake stream and monkeypatch
  `decode`; the two real-ffmpeg decode tests skip when ffmpeg is absent.

## Decisions log

- Variant selection: highest bandwidth from the master playlist.
- Delay positioning: start at the newest sequence whose summed duration to the
  live edge >= delay (segments already on the server -> fast start).
- Per-segment ffmpeg subprocess (not one long-lived pipe): simpler, and gap
  handling stays trivial.
- Preset streams verified 2026-08-26; playlist windows are short (~28-30 s),
  so delays much above ~25 s exceed what the server retains (M2 warns).
- Eviction is done by the player right after it plays a segment; the buffer
  keeps the eviction point as a floor so `register()` ignores anything older
  (no re-downloading played audio). Startup evicts everything before the
  chosen start sequence for the same reason.
- Player skip-ahead: if its position was never listed but newer segments
  are, the outage outlasted the server window; jump to the oldest listed.
- Player writes PCM in 0.25 s chunks and aborts the stream on stop. A
  whole-segment write made shutdown `join(5)` time out and the process
  exited inside PortAudio (exit code 0xC0000374, heap corruption).
- Fetcher is `poll_once()` (playlist + download missing) inside the
  `run_fetcher()` backoff loop, so tests exercise one poll at a time.
- M5 (optional, after M4): thin Tkinter GUI (dropdown of presets + custom URL
  box) reusing the same core; no new dependencies.

## Conventions

- Dependencies: only httpx, m3u8, sounddevice (pinned in requirements.txt).
  Any addition must be justified to the user first. pytest is dev-only
  (requirements-dev.txt). Run tests with `python -m pytest`.
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
- M4: unit tests (fake fetcher, no network) + README. **Done** (35 tests,
  <1 s, `python -m pytest`).
