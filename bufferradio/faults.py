"""Fault injection: simulate a network outage on demand.

The outage is injected at the httpx transport layer -- the piece that
actually sends bytes -- so the rest of the program cannot tell it apart
from a real connection failure and needs no special-casing.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

import httpx


class FaultInjector:
    """While tripped, every HTTP request fails. Expires on its own."""

    def __init__(self) -> None:
        self._until = 0.0

    def trip(self, seconds: float) -> None:
        self._until = time.monotonic() + seconds

    def clear(self) -> None:
        self._until = 0.0

    @property
    def active(self) -> bool:
        return time.monotonic() < self._until


class FaultyTransport(httpx.AsyncBaseTransport):
    """Wraps a real transport; raises ConnectError while the injector is active."""

    def __init__(self, faults: FaultInjector, inner: httpx.AsyncBaseTransport) -> None:
        self._faults = faults
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._faults.active:
            raise httpx.ConnectError("simulated outage (fault injector)", request=request)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def start_key_listener(on_key: Callable[[str], None]) -> None:
    """Call on_key(char) for each key pressed, from a daemon thread.

    On a Windows console keys are read as they are pressed. Anywhere else
    (including IDE run windows, which are not real consoles) input is
    line-based: type the key and press Enter.
    """
    def loop() -> None:
        if sys.platform == "win32" and sys.stdin.isatty():
            import msvcrt
            while True:
                on_key(msvcrt.getwch())
        else:
            for line in sys.stdin:
                if line.strip():
                    on_key(line.strip()[0])

    threading.Thread(target=loop, name="keys", daemon=True).start()
