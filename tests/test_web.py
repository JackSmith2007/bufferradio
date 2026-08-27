"""Web front end tests: real HTTP against the stdlib server, fake playback session."""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from bufferradio import web
from bufferradio.web import Radio, make_server


class FakeSession:
    """Stands in for app.main(): records the call, then waits until cancelled."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self.cancelled = threading.Event()

    async def __call__(self, url: str, delay: float, fault_seconds: float, metrics, faults, keys) -> None:
        self.calls.append((url, delay))
        assert keys is False
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    fake = FakeSession()
    monkeypatch.setattr(web, "main", fake)
    return fake


@pytest.fixture
def server(session: FakeSession):
    radio = Radio(None, fault_seconds=3.0)
    srv = make_server(radio, delay=20, port=0)  # any free port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        yield base, radio
    finally:
        radio.stop()
        srv.shutdown()
        srv.server_close()


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read().decode()


def post(endpoint: str, **fields: str) -> tuple[int, str]:
    req = urllib.request.Request(endpoint, data=urlencode(fields).encode(), method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except HTTPError as err:
        return err.code, err.read().decode()


def test_page_lists_stations(server) -> None:
    base, _ = server
    status, body = get(base + "/")
    assert status == 200
    assert "<title>bufferradio</title>" in body
    assert 'value="cbc-radio2"' in body
    assert "Inject 3s outage" in body


def test_status_when_stopped(server) -> None:
    base, _ = server
    status = json.loads(get(base + "/status")[1])
    assert status["running"] is False
    assert status["played"] == 0


def test_start_fault_stop_cycle(server, session: FakeSession) -> None:
    base, radio = server
    code, body = post(base + "/start", station="cbc-radio2", delay="15")
    assert code == 200
    assert json.loads(body)["running"] is True
    assert session.calls == [(web.STATIONS["cbc-radio2"], 15.0)]

    code, body = post(base + "/fault")
    assert json.loads(body)["fault_active"] is True
    assert radio.metrics.counts["fault"] == 1
    assert any("FAULT" in line for line in radio.logs.lines)

    code, body = post(base + "/stop")
    assert json.loads(body)["running"] is False
    assert session.cancelled.is_set()
    assert any("summary" in line for line in radio.logs.lines)


def test_custom_url_and_validation(server, session: FakeSession) -> None:
    base, _ = server
    code, body = post(base + "/start", station="", url="")
    assert code == 400
    code, body = post(base + "/start", station="", url="https://radio.test/live.m3u8")
    assert code == 200
    assert session.calls[-1] == ("https://radio.test/live.m3u8", 20.0)


def test_unknown_paths_404(server) -> None:
    base, _ = server
    with pytest.raises(HTTPError) as err:
        get(base + "/nope")
    assert err.value.code == 404
