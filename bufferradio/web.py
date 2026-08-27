"""Minimal local web front end (python -m bufferradio --web).

Standard-library http.server only. The page is a control panel: audio still
plays on the machine running this program. One HTML page, three actions
(start / stop / inject outage) and a status endpoint the page polls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .app import inject_fault, main
from .faults import FaultInjector
from .metrics import Metrics
from .stations import STATIONS

log = logging.getLogger("bufferradio")

HOST, PORT = "127.0.0.1", 8765


class LogBuffer(logging.Handler):
    """Keeps the last N log lines so the page can show what the console shows."""

    def __init__(self, size: int = 60) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=size)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


class Radio:
    """Runs one playback session at a time on a background thread."""

    def __init__(self, metrics_path: Path | None, fault_seconds: float) -> None:
        self._metrics_path = metrics_path
        self.fault_seconds = fault_seconds
        self.url = ""
        self.delay = 0.0
        self.metrics = Metrics(None)
        self.faults = FaultInjector()
        self.logs = LogBuffer()
        app_log = logging.getLogger("bufferradio")  # parent of every module logger here
        app_log.addHandler(self.logs)
        if app_log.getEffectiveLevel() > logging.INFO:
            app_log.setLevel(logging.INFO)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, url: str, delay: float) -> None:
        self.stop()
        self.url, self.delay = url, delay
        self.metrics = Metrics(self._metrics_path)
        self.faults = FaultInjector()
        self._loop = asyncio.new_event_loop()
        self._task = self._loop.create_task(
            main(url, delay, self.fault_seconds, self.metrics, faults=self.faults, keys=False))
        self._thread = threading.Thread(target=self._run, name="radio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._loop is not None and self._task is not None
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - anything else ends the session with a message
            log.error("stopped: %s", exc)
        finally:
            self._loop.close()
            log.info("summary: %s", self.metrics.summary())

    def stop(self) -> None:
        if self.running:
            assert self._loop is not None and self._task is not None and self._thread is not None
            self._loop.call_soon_threadsafe(self._task.cancel)
            self._thread.join(timeout=10)

    def fault(self) -> None:
        if self.running:
            inject_fault(self.faults, self.fault_seconds, self.metrics)

    def status(self) -> dict:
        names = {url: name for name, url in STATIONS.items()}
        return {
            "running": self.running,
            "station": names.get(self.url, self.url),
            "delay": self.delay,
            "fault_active": self.faults.active,
            "played": self.metrics.counts["played"],
            "gaps": self.metrics.counts["gap"],
            "silence_s": round(self.metrics.silence_ms / 1000, 1),
            "faults": self.metrics.counts["fault"],
            "log": list(self.logs.lines),
        }


PAGE = """<!doctype html>
<title>bufferradio</title>
<h1>bufferradio</h1>
<form id="form">
  <label>Station
    <select name="station">
      {options}
      <option value="">custom URL:</option>
    </select>
  </label>
  <input name="url" size="50" placeholder="https://.../master.m3u8">
  <label>Delay <input name="delay" type="number" value="{delay}" min="0" max="60" size="3"> s</label>
  <button type="submit">Start</button>
  <button type="button" id="stop">Stop</button>
  <button type="button" id="fault">Inject {fault}s outage</button>
</form>
<p id="status">stopped</p>
<pre id="log"></pre>
<script>
const form = document.getElementById("form");
function post(path, body) {{ return fetch(path, {{method: "POST", body}}).then(refresh); }}
form.onsubmit = e => {{ e.preventDefault(); post("/start", new URLSearchParams(new FormData(form))); }};
document.getElementById("stop").onclick = () => post("/stop", "");
document.getElementById("fault").onclick = () => post("/fault", "");
async function refresh() {{
  const s = await (await fetch("/status")).json();
  document.getElementById("status").textContent = s.running
    ? `playing ${{s.station}} ${{s.delay}}s behind live | ${{s.played}} segments played, ` +
      `${{s.gaps}} gaps (${{s.silence_s}}s silence), ${{s.faults}} outages injected` +
      (s.fault_active ? " | OUTAGE ACTIVE" : "")
    : "stopped";
  document.getElementById("log").textContent = s.log.join("\\n");
}}
refresh();
setInterval(refresh, 1000);
</script>
"""


class Handler(BaseHTTPRequestHandler):
    radio: Radio  # set by serve()
    page: str

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", self.page)
        elif self.path == "/status":
            self._send(200, "application/json", json.dumps(self.radio.status()))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        if self.path == "/start":
            station = form.get("station", [""])[0]
            url = STATIONS.get(station) or form.get("url", [""])[0].strip()
            if not url:
                self._send(400, "text/plain", "choose a station or enter a URL")
                return
            self.radio.start(url, float(form.get("delay", ["20"])[0]))
        elif self.path == "/stop":
            self.radio.stop()
        elif self.path == "/fault":
            self.radio.fault()
        else:
            self.send_error(404)
            return
        self._send(200, "application/json", json.dumps(self.radio.status()))

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep the console for the radio's own log lines

    def _send(self, code: int, content_type: str, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(radio: Radio, delay: float, host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    options = "\n".join(f'<option value="{name}">{name}</option>' for name in sorted(STATIONS))
    handler = type("BoundHandler", (Handler,), {
        "radio": radio,
        "page": PAGE.format(options=options, delay=int(delay), fault=int(radio.fault_seconds)),
    })
    return ThreadingHTTPServer((host, port), handler)


def serve(metrics_path: Path | None, fault_seconds: float, delay: float) -> None:
    radio = Radio(metrics_path, fault_seconds)
    server = make_server(radio, delay)
    url = f"http://{HOST}:{PORT}"
    log.info("web front end at %s (Ctrl+C to quit)", url)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        radio.stop()
        server.server_close()
