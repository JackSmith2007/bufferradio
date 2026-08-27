# bufferradio

Live internet radio that keeps playing through network hiccups.

bufferradio plays an HLS radio stream a configurable number of seconds
**behind** the live edge. Because playback deliberately lags live, a short
outage is inaudible: the audio that was missed is still on the server, and it
is re-downloaded before playback reaches it. Press `f` to simulate an outage
and hear (nothing) for yourself; every download, play, gap and outage is
logged to `metrics.csv`.

## Run it

**Step 1 — get the files.** Click the green **Code** button above, choose
**Download ZIP**, and unzip it anywhere.

**Step 2 — double-click the launcher for your computer:**

| | |
| --- | --- |
| Windows | **`start-windows.bat`** |
| Mac | **`start-mac.command`** — the first time, right-click it and choose **Open** (macOS asks once because the file came from the internet) |

The launcher does everything else: it finds Python (or installs it on
Windows), creates a private environment inside the folder, installs the
dependencies — including a copy of ffmpeg, so there is nothing to install by
hand — and opens the control page in your browser. The first run takes about
a minute; after that it opens in a couple of seconds.

**Step 3 — on the page** (http://127.0.0.1:8765), pick a station and click
**Start**. The radio plays 20 seconds behind live, out of the computer's
speakers. Click **Inject 5s outage** — every network request fails for five
seconds and the music keeps playing; the log underneath shows the failure and
then `network back ... backfilled`. **Stop** ends playback. Closing the black
terminal window that opened alongside the browser quits the program.

**Windows alternative:** download
[bufferradio.exe](https://github.com/JackSmith2007/bufferradio/releases/latest/download/bufferradio.exe)
from the latest release — a single file with Python and ffmpeg inside, no
setup at all; double-click it and the same page opens. It isn't code-signed,
so if SmartScreen says "Windows protected your PC", click **More info → Run
anyway**.

## Terminal mode and options

Run a launcher (or the exe) with arguments and it plays in the terminal
instead of opening the web page:

```
start-windows.bat --station fip --delay 25        (Windows)
./start-mac.command --station fip --delay 25      (Mac)
bufferradio.exe --station fip --delay 25          (the exe)
```

In the terminal, press `f` to inject an outage and `q` (or `Ctrl+C`) to quit.

| Option | Meaning |
| --- | --- |
| `--station NAME` | play a preset (`cbc-radio2`, `cbc-radio1-toronto`, `fip`, `france-inter`, `franceinfo`) |
| `--url URL` | play any HLS master or media playlist |
| `--web` | open the control page at http://127.0.0.1:8765 (what a double-click does) |
| `--delay S` | seconds behind live (default 20) |
| `--fault-seconds S` | length of the outage injected by the `f` key (default 5) |
| `--metrics-file PATH` | CSV to append events to (default `metrics.csv`) |

With neither `--station` nor `--url`, the station menu is shown. `Ctrl+C`
also quits. In an IDE run window (which is not a real console) type the key
and press Enter.

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
7. **ffmpeg** (`ffmpeg_setup.py`). ffmpeg is the one dependency that isn't
   Python, so it comes from `imageio-ffmpeg`, a pip package whose only job is
   to ship a prebuilt ffmpeg binary for the current OS. A system ffmpeg on
   `PATH` is the fallback.

### Trying the fault injector

```
$ start-windows.bat --station cbc-radio2
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

Running from a terminal without the launcher:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt          # httpx, m3u8, sounddevice, imageio-ffmpeg
python run.py --station cbc-radio2       # or: python -m bufferradio ...
```

Tests and the Windows exe:

```powershell
pip install -r requirements-dev.txt      # + pytest, pyinstaller
python -m pytest                         # 43 tests, a few seconds, no network or audio device needed
python -m PyInstaller --onefile --name bufferradio --clean run.py   # -> dist\bufferradio.exe
```

The fetcher tests run against an in-memory fake HLS server
(`httpx.MockTransport`) and the player writes to a fake output stream.

## Project layout

```
start-windows.bat   double-click launcher (Windows)
start-mac.command   double-click launcher (macOS / Linux)
run.py              entry point for source runs and the PyInstaller exe
bufferradio/
  __main__.py       command-line interface
  app.py            one playback session: open stream, start player, run fetcher
  web.py            local web front end (--web), stdlib http.server
  fetcher.py        playlist polling + segment download (asyncio, httpx, m3u8)
  buffer.py         SegmentBuffer: thread-safe, keyed by media sequence number
  player.py         playback thread: ffmpeg decode -> sounddevice
  faults.py         FaultInjector, FaultyTransport, key listener
  metrics.py        CSV event log + summary
  ffmpeg_setup.py   locate the bundled (or system) ffmpeg
  stations.py       verified presets + terminal picker
tests/              pytest suite (no network)
```

## Limitations

- The maximum useful delay is the server's playlist window (~30 s for the
  presets); HLS servers only keep that much.
- Segment granularity is coarse (10 s for the presets): if a segment's bytes
  haven't arrived 2 s after playback reaches it, the whole segment is silence.
- Only the highest-bandwidth variant is used; there is no adaptive switching.
- Developed and tested on Windows; the Mac launcher follows the same steps
  but has not been run on a Mac.

## License

MIT. The bundled ffmpeg comes from the
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) package (LGPL build).
