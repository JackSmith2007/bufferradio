from __future__ import annotations

import asyncio

import httpx
import pytest

from bufferradio.faults import FaultInjector, FaultyTransport


def test_injector_expires_and_clears() -> None:
    faults = FaultInjector()
    assert not faults.active
    faults.trip(60)
    assert faults.active
    faults.clear()
    assert not faults.active
    faults.trip(0)
    assert not faults.active


def ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="ok")


def test_transport_fails_every_request_while_tripped() -> None:
    faults = FaultInjector()
    transport = FaultyTransport(faults, httpx.MockTransport(ok_handler))

    async def go() -> str:
        async with httpx.AsyncClient(transport=transport) as client:
            faults.trip(60)
            with pytest.raises(httpx.ConnectError):
                await client.get("https://radio.test/index.m3u8")
            faults.clear()
            return (await client.get("https://radio.test/index.m3u8")).text

    assert asyncio.run(go()) == "ok"


def test_simulated_outage_is_an_ordinary_http_error() -> None:
    # The fetcher catches httpx.HTTPError; the injected failure must be one,
    # so no code path needs to know about fault injection.
    assert issubclass(httpx.ConnectError, httpx.HTTPError)
