"""One persistent, serialized MCP stdio session for Chrome DevTools.

The process is reused across calls. In-flight requests are never replayed after
a transport failure; Chrome's human approval remains mandatory when prompted.
"""
import asyncio
import itertools
import json


class UncertainDelivery(RuntimeError):
    pass


class PersistentCDP:
    def __init__(self, argv, timeout=30):
        self.argv = tuple(argv)
        self.timeout = timeout
        self._proc = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self.generation = 0

    @property
    def connected(self):
        return self._proc is not None and self._proc.returncode is None

    async def _send(self, value):
        self._proc.stdin.write((json.dumps(value) + "\n").encode())
        await self._proc.stdin.drain()

    async def _exchange(self, method, params):
        ident = next(self._ids)
        await self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            line = await asyncio.wait_for(self._proc.stdout.readline(), self.timeout)
            if not line:
                raise UncertainDelivery("MCP connection closed; result unknown")
            try:
                msg = json.loads(line)
            except ValueError as exc:
                raise UncertainDelivery("Invalid MCP JSON") from exc
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result")
            if "id" in msg:
                raise UncertainDelivery("Unexpected response id")

    async def _connect(self):
        if self.connected:
            return
        self._proc = await asyncio.create_subprocess_exec(
            *self.argv, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.generation += 1
        try:
            await self._exchange("initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "bct-cdp", "version": "0.1"}})
            await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            await self._close()
            raise

    async def request(self, method, params=None):
        async with self._lock:
            await self._connect()
            try:
                return await self._exchange(method, params or {})
            except (OSError, asyncio.TimeoutError, UncertainDelivery) as exc:
                await self._close()
                raise UncertainDelivery("MCP effect uncertain; do not retry automatically") from exc

    async def _close(self):
        proc, self._proc = self._proc, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def close(self):
        async with self._lock:
            await self._close()
