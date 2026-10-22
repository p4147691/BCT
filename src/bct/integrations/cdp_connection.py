"""BCT-owned, process-scoped Chrome DevTools MCP connection.

Only BCT's operation coordinator may invoke this adapter. Connection startup is
lazy and Chrome's own human-consent dialog is never clicked programmatically.
A dedicated event loop keeps one approved stdio connection alive across requests
from independent BCT worker threads. Calls are serialized in the MCP client.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading

from bct.features.cdp_persistent import PersistentCDP


class CDPConnectionManager:
    _ALLOWED = {
        ("tools/list", None),
        ("ping", None),
        ("tools/call", "list_pages"),
    }

    def __init__(self) -> None:
        self._argv: tuple[str, ...] | None = None
        self._timeout = 30.0
        self._guard = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: PersistentCDP | None = None

    def configure(self, argv: tuple[str, ...], *, timeout: float = 30.0) -> None:
        argv = tuple(argv)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("CDP_MCP_ARGV_INVALID")
        if not 1 <= timeout <= 300:
            raise ValueError("CDP_MCP_TIMEOUT_INVALID")
        with self._guard:
            if self._argv is not None:
                if argv != self._argv or timeout != self._timeout:
                    raise RuntimeError("CDP_MCP_CONNECTION_ALREADY_CONFIGURED")
                return
            self._argv = argv
            self._timeout = timeout

    @property
    def connected(self) -> bool:
        with self._guard:
            return self._client is not None and self._client.connected

    @property
    def generation(self) -> int:
        with self._guard:
            return self._client.generation if self._client is not None else 0

    @staticmethod
    def _validate(method: str, params: dict) -> None:
        if method in {"tools/list", "ping"} and params == {}:
            return
        if method == "tools/call" and params == {
            "name": "list_pages", "arguments": {}
        }:
            return
        raise PermissionError("CDP_MCP_OPERATION_NOT_AUTHORIZED")

    def _start_loop(self) -> None:
        if self._loop is not None:
            return
        assert self._argv is not None
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def serve() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        thread = threading.Thread(
            target=serve, name="bct-cdp-mcp-owner", daemon=True)
        thread.start()
        if not ready.wait(timeout=5):
            raise RuntimeError("CDP_MCP_LOOP_NOT_READY")
        self._loop = loop
        self._thread = thread
        self._client = PersistentCDP(self._argv, timeout=self._timeout)

    def request(self, method: str, params: dict | None = None) -> dict:
        normalized = {} if params is None else params
        if not isinstance(normalized, dict):
            raise ValueError("CDP_MCP_PARAMS_INVALID")
        self._validate(method, normalized)
        with self._guard:
            if self._argv is None:
                raise RuntimeError("CDP_MCP_NOT_CONFIGURED")
            self._start_loop()
            assert self._loop is not None and self._client is not None
            future = asyncio.run_coroutine_threadsafe(
                self._client.request(method, normalized), self._loop)
            try:
                result = future.result(timeout=self._timeout + 10)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise RuntimeError("CDP_MCP_RESPONSE_UNCERTAIN") from exc
        if not isinstance(result, dict):
            raise RuntimeError("CDP_MCP_RESULT_INVALID")
        return result

    def close(self) -> None:
        """Bounded final shutdown; never closes the user's Chrome browser."""
        with self._guard:
            loop, thread, client = self._loop, self._thread, self._client
            self._loop = None
            self._thread = None
            self._client = None
            self._argv = None
            if loop is None:
                return
            if client is not None:
                future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                try:
                    future.result(timeout=5)
                except (concurrent.futures.TimeoutError, RuntimeError):
                    future.cancel()
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(timeout=5)
