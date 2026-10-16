from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from bct.integrations.rcc import (
    LOCAL_SYSTEM_SID,
    PIPE_FULL_CONTROL,
    NamedPipeRelayClient,
    PipeAccessEntry,
    PipeServerIdentity,
    RelayEffectUnknown,
    RelayUnavailable,
    validate_pipe_server_identity,
)


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
            patch("bct.integrations.rcc.verify_connected_pipe_server"),
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
            patch("bct.integrations.rcc.verify_connected_pipe_server", side_effect=lambda _pipe: events.append("verify")),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                before_write=lambda: events.append("before_write"), timeout_s=1,
            )
        self.assertEqual(["open", "verify", "before_write", "write"], events)

    def test_server_rejection_precedes_before_write_and_request_write(self):
        events: list[str] = []
        pipe = _Pipe([])

        def reject(_pipe):
            events.append("verify")
            raise RelayUnavailable("RCC_PIPE_SERVER_REJECTED:DACL_NOT_PROTECTED")

        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", side_effect=lambda *_args, **_kwargs: (events.append("open") or pipe)),
            patch("bct.integrations.rcc.verify_connected_pipe_server", side_effect=reject),
            self.assertRaises(RelayUnavailable),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                before_write=lambda: events.append("before_write"), timeout_s=1,
            )
        self.assertEqual(["open", "verify"], events)
        self.assertEqual(b"", pipe.written)

    def test_server_identity_api_failure_is_prewrite_unavailable(self):
        events: list[str] = []
        pipe = _Pipe([])

        def unavailable(_pipe):
            events.append("verify")
            raise OSError("GetNamedPipeServerProcessId failed")

        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", side_effect=lambda *_args, **_kwargs: (events.append("open") or pipe)),
            patch("bct.integrations.rcc.verify_connected_pipe_server", side_effect=unavailable),
            self.assertRaisesRegex(RelayUnavailable, "RCC_TRANSPORT_NOT_STARTED"),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                before_write=lambda: events.append("before_write"), timeout_s=1,
            )
        self.assertEqual(["open", "verify"], events)
        self.assertEqual(b"", pipe.written)

    def test_before_write_exception_is_propagated_without_writing(self):
        pipe = _Pipe([])
        failure = OSError("fence failed")

        def fail():
            raise failure

        with (
            patch("bct.integrations.rcc.resolve_instance_id", return_value="instance123"),
            patch("builtins.open", return_value=pipe),
            patch("bct.integrations.rcc.verify_connected_pipe_server"),
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
            patch("bct.integrations.rcc.verify_connected_pipe_server"),
            self.assertRaises(RelayEffectUnknown),
        ):
            NamedPipeRelayClient().request(
                instance_id="instance123", request_id="send-1", command="send",
                timeout_s=1,
            )
        self.assertNotEqual(b"", pipe.written)


class PipeServerIdentityValidationTests(unittest.TestCase):
    @staticmethod
    def _valid_identity(**changes):
        values = {
            "server_pid": 1234,
            "pipe_server_session_id": 3,
            "process_session_id": 3,
            "current_session_id": 3,
            "server_user_sid": "S-1-5-21-1-1001",
            "current_user_sid": "S-1-5-21-1-1001",
            "server_logon_sid": "S-1-5-5-0-12345",
            "current_logon_sid": "S-1-5-5-0-12345",
            "pipe_owner_sid": "S-1-5-21-1-1001",
            "dacl_protected": True,
            "dacl_entries": (
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, "S-1-5-5-0-12345"),
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, LOCAL_SYSTEM_SID),
            ),
        }
        values.update(changes)
        return PipeServerIdentity(**values)

    def test_exact_personal_desktop_boundary_is_accepted(self):
        validate_pipe_server_identity(self._valid_identity())

    def test_user_logon_session_and_owner_mismatches_fail_closed(self):
        cases = (
            {"server_user_sid": "S-1-5-21-9-1002"},
            {"server_logon_sid": "S-1-5-5-0-999"},
            {"pipe_server_session_id": 4},
            {"process_session_id": 4},
            {"pipe_owner_sid": "S-1-5-21-9-1002"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(RelayUnavailable):
                validate_pipe_server_identity(self._valid_identity(**changes))

    def test_unprotected_or_broad_or_inherited_dacl_fails_closed(self):
        cases = (
            {"dacl_protected": False},
            {"dacl_entries": (
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, "S-1-5-5-0-12345"),
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, LOCAL_SYSTEM_SID),
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, "S-1-1-0"),
            )},
            {"dacl_entries": (
                PipeAccessEntry(0, 0x10, PIPE_FULL_CONTROL, "S-1-5-5-0-12345"),
                PipeAccessEntry(0, 0, PIPE_FULL_CONTROL, LOCAL_SYSTEM_SID),
            )},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(RelayUnavailable):
                validate_pipe_server_identity(self._valid_identity(**changes))


if __name__ == "__main__":
    unittest.main()
