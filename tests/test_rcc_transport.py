from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bct.integrations.rcc import NamedPipeRelayClient, RelayEffectUnknown


class _Pipe:
    def __init__(self, messages: list[dict]):
        self.lines = [
            (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
            for message in messages
        ]
        self.written = b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def write(self, value: bytes):
        self.written += value
        return len(value)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


class NamedPipeRelayClientTests(unittest.TestCase):
    def _request(self, pipe: _Pipe, *, return_on_ack: bool):
        extra = {"returnOnAck": True} if return_on_ack else {}
        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", return_value=pipe),
        ):
            result = NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1",
                command="send", to="WORKER", text="bounded", extra=extra,
                timeout_s=1,
            )
        return result, json.loads(pipe.written.decode("utf-8"))

    def test_orchestration_can_return_exact_submit_ack(self):
        pipe = _Pipe([{
            "type": "host:ack", "requestId": "send-1", "ok": True,
            "submitted": True, "effectState": "SUBMITTED",
        }])
        result, request = self._request(pipe, return_on_ack=True)
        self.assertEqual("host:ack", result["type"])
        self.assertTrue(result["submitted"])
        self.assertIs(True, request["returnOnAck"])

    def test_legacy_send_still_waits_for_terminal_result(self):
        pipe = _Pipe([
            {
                "type": "host:ack", "requestId": "send-1", "ok": True,
                "submitted": True,
            },
            {
                "type": "host:result", "requestId": "send-1", "ok": True,
                "reply": "done",
            },
        ])
        result, request = self._request(pipe, return_on_ack=False)
        self.assertEqual("host:result", result["type"])
        self.assertEqual("done", result["reply"])
        self.assertNotIn("returnOnAck", request)

    def test_before_write_runs_after_open_and_immediately_before_write(self):
        events: list[str] = []
        pipe = _Pipe([{
            "type": "host:result", "requestId": "send-1", "ok": True,
            "reply": "done",
        }])
        original_write = pipe.write

        def write(value: bytes):
            events.append("write")
            return original_write(value)

        pipe.write = write
        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", side_effect=lambda *_args, **_kwargs: (events.append("open") or pipe)),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                before_write=lambda: events.append("before_write"), timeout_s=1,
            )
        self.assertEqual(["open", "before_write", "write"], events)

    def test_before_write_exception_is_propagated_without_writing(self):
        pipe = _Pipe([])
        failure = OSError("fence failed")

        def fail():
            raise failure

        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", return_value=pipe),
            self.assertRaises(OSError) as caught,
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                before_write=fail, timeout_s=1,
            )
        self.assertIs(failure, caught.exception)
        self.assertEqual(b"", pipe.written)

    def test_write_exception_is_unknown_even_when_write_does_not_return(self):
        pipe = _Pipe([])

        def partial_write(value: bytes):
            pipe.written += value[:4]
            raise OSError("write completion unknown")

        pipe.write = partial_write
        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", return_value=pipe),
            self.assertRaises(RelayEffectUnknown),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                timeout_s=1,
            )
        self.assertNotEqual(b"", pipe.written)


if __name__ == "__main__":
    unittest.main()
