# bufferradio

Live internet radio that keeps playing through network hiccups.

bufferradio plays an HLS radio stream a configurable number of seconds
**behind** the live edge. Because playback deliberately lags live, a short
outage is inaudible: the audio that was missed is still on the server, and it
is re-downloaded before playback reaches it. Press `f` to simulate an outage
and hear (nothing) for yourself; every download, play, gap and outage is
logged to `metrics.csv`.

## Try it (Windows, nothing to install)

1. Download **[bufferradio.exe](https://github.com/JackSmith2007/bufferradio/releases/latest/download/bufferradio.exe)**
   from the latest release.
2. Double-click it. Pick a station from the menu.

That's it. On the first run it fetches a copy of ffmpeg (about 67 MB, one time,
stored in `%LOCALAPPDATA%\bufferradio`); after that it starts instantly.

Because the exe is not code-signed, Windows SmartScreen may show
"Windows protected your PC" — click **More info → Run anyway**.

To pass options, run it from a terminal instead:

```
bufferradio.exe --station fip --delay 25
```

## Run from source (any OS)

Needs Python 3.12+. On Windows ffmpeg is downloaded automatically; on macOS
or Linux install it first (`brew install ffmpeg` / `sudo apt install ffmpeg libportaudio2`).

```powershell
git clone https://github.com/JackSmith2007/bufferradio.git
cd bufferradio
python -m venv .venv
.\.venv\Scripts\Activate.ps1             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # httpx, m3u8, sounddevice
python run.py --station cbc-radio2       # or: python -m bufferradio ...
```

## Usage

| Option | Meaning |
| --- | --- |
| `--station NAME` | play a preset (`cbc-radio2`, `cbc-radio1-toronto`, `fip`, `france-inter`, `franceinfo`) |
| `--url URL` | play any HLS master or media playlist |
| `--delay S` | seconds behind live (default 20) |
| `--fault-seconds S` | length of the outage injected by the `f` key (default 5) |
| `--metrics-file PATH` | CSV to append events to (default `metrics.csv`) |

With neither `--station` nor `--url`, a numbered menu of presets is shown.

While playing:

| Key | Action |
| --- | --- |
| `f` | inject an outage: every HTTP request fails for `--fault-seconds` |
| `q` or `Ctrl+C` | quit (a summary line is printed) |

In a real console keys take effect as soon as they are pressed. In an IDE run
window (which is not a console) type the key and press Enter.

The delay cannot exceed what the server keeps in its playlist window (about
30 s for the presets). Asking for more prints a warning and uses the window
length as the effective delay.

## How it works

```
             server (HLS)                     this program
   ┌───────────────────────────┐    ┌────────────────────────────────────┐
   │ playlist: seq 100 101 102 │───>│ fetcher (asyncio + httpx)          │
   │ segments:  ▓▓▓ ▓▓▓ ▓▓▓    │───>│  poll playlist, download missing   │
   └───────────────────────────┘    │            │                       │
                                    │            v                       │
                                    │ SegmentBuffer  {seq: (duration,    │
                                    │                       bytes|None)} │
                                    │            │                       │
                                    │            v                       │
                                    │ player thread: ffmpeg -> PCM ->    │
                                    │   sounddevice, `delay` s behind    │
                                    └────────────────────────────────────┘
```

An HLS live stream is a playlist (`.m3u8`) that the server rewrites every few
seconds, listing the last few audio segments (here, three 10 s files) with
increasing *media sequence numbers*.

1. **Startup** (`__main__.py`). The master playlist is resolved to its
   highest-bandwidth variant. From the media playlist, playback starts at the
   newest sequence whose distance to the live edge covers `--delay`; those
   segments already exist, so audio starts within a second while still sitting
   `delay` seconds behind live.
2. **Fetcher** (`fetcher.py`). Every `target-duration / 2` seconds it fetches
   the playlist, *registers* every listed segment (sequence number and
   duration), and downloads any it doesn't hold yet. That one rule is also the
   recovery path: after an outage the missed segments are simply still
   un-downloaded, and the next successful poll picks them up. Playlist
   failures back off exponentially (1 s → 10 s).
3. **Buffer** (`buffer.py`). `SegmentBuffer` keeps playlist metadata separate
   from payload bytes. A registered segment with `data=None` is one the fetcher
   still owes; that gives the player an exact-length silence to substitute if
   the bytes never come, and gives the fetcher an explicit backfill worklist.
   Played segments are evicted, and the eviction point is remembered as a
   floor so nothing already played is ever re-registered or re-downloaded.
4. **Player** (`player.py`). A separate thread plays segments in sequence
   order. Each one is decoded to 48 kHz stereo 16-bit PCM by a short-lived
   `ffmpeg` subprocess (stdin → stdout, no temp files) and written to the
   audio device in 0.25 s chunks; the blocking write paces playback, so there
   is no clock arithmetic. A segment whose bytes never arrive becomes silence
   of exactly its duration, never a crash. If the player's position was never
   listed but newer segments were, the outage outlasted the server's window,
   and it skips ahead instead of waiting forever.
5. **Faults** (`faults.py`). Pressing `f` trips a `FaultInjector`. It sits in
   an httpx *transport* wrapper -- the layer that actually sends bytes -- so
   while tripped every request raises `ConnectError`, exactly what a real
   outage looks like. Nothing else in the program knows faults exist.
6. **Metrics** (`metrics.py`). One CSV row per event, plus a summary on exit.
7. **ffmpeg** (`ffmpeg_setup.py`). ffmpeg is the one dependency pip can't
   install. If it isn't on `PATH`, a static build is downloaded once into the
   user's app-data folder and that folder is put on this process's `PATH`;
   the rest of the program just calls `ffmpeg`.

### Trying the fault injector

```
$ bufferradio --station cbc-radio2
... INFO selected variant: 192000 bps
... INFO playlist window: 30s (3 segments)
... INFO starting playback at sequence 246783, 30s behind live
... INFO press f to inject a 5s outage, q to quit
<press f>
... WARNING FAULT: dropping all HTTP requests for 5s
... WARNING playlist fetch failed: simulated outage (fault injector) (retrying in 1.0s)
<audio keeps playing; a few seconds later the fetcher catches up>
<press q>
... INFO summary: 4 segments played, 0 gaps (0.0s silence), 6 downloaded, 1 playlist errors, 1 faults injected -> metrics.csv
```

An outage longer than the delay *will* produce audible silence, and that is
recorded too: `gap` rows in the CSV and a non-zero silence total in the summary.

The fetcher polls every 5 s (half the segment duration), so a 5 s outage can
fall entirely between two polls and fail no request at all. For a guaranteed
visible failure use `--fault-seconds 10`; for audible gaps, `--fault-seconds 40`
with the default 20 s delay.

### metrics.csv

```
timestamp,event_type,sequence,duration_ms
2026-08-26T23:36:41.811,stored,246796,209
2026-08-26T23:36:42.106,played,246796,10048
2026-08-26T23:36:48.693,fault,,5000
2026-08-26T23:36:53.297,playlist_error,,1000
```

| event_type | sequence | duration_ms |
| --- | --- | --- |
| `stored` | segment downloaded | download time |
| `played` | segment decoded and played | audio length |
| `gap` | silence played instead | silence length |
| `skip` | playhead jumped past expired segments | – |
| `playlist_error` | playlist fetch failed | backoff before retry |
| `fault` | outage injected with `f` | outage length |

The file is appended to across runs (`.gitignore`d).

## Development

```powershell
pip install -r requirements-dev.txt      # + pytest, pyinstaller
python -m pytest                         # ~40 tests, <1 s, no network or audio device needed
```

The fetcher tests run against an in-memory fake HLS server
(`httpx.MockTransport`), the player writes to a fake output stream, and the
ffmpeg downloader unpacks an in-memory zip. Two decode tests use a real
`ffmpeg` and are skipped if it is not installed.

To build the standalone Windows exe (`dist\bufferradio.exe`):

```powershell
python -m PyInstaller --onefile --name bufferradio --clean run.py
```

## Project layout

```
run.py              launcher (source runs and the PyInstaller entry point)
bufferradio/
  __main__.py       CLI, startup, wiring, shutdown
  fetcher.py        playlist polling + segment download (asyncio, httpx, m3u8)
  buffer.py         SegmentBuffer: thread-safe, keyed by media sequence number
  player.py         playback thread: ffmpeg decode -> sounddevice
  faults.py         FaultInjector, FaultyTransport, key listener
  metrics.py        CSV event log + summary
  ffmpeg_setup.py   find ffmpeg, or download it once on Windows
  stations.py       verified presets + terminal picker
tests/              pytest suite (no network)
```

## Limitations

- The maximum useful delay is the server's playlist window (~30 s for the
  presets); HLS servers only keep that much.
- Segment granularity is coarse (10 s for the presets): if a segment's bytes
  haven't arrived 2 s after playback reaches it, the whole segment is silence.
- Only the highest-bandwidth variant is used; there is no adaptive switching.
- The prebuilt exe and the automatic ffmpeg download are Windows-only; other
  platforms run from source with a system ffmpeg.

## License

MIT. The automatically downloaded ffmpeg is an LGPL build from
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds).
