from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import threading
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows named-pipe proof")
class RccNativePipeAclWindowsTests(unittest.TestCase):
    """Disposable proof only: it never opens the installed RCC pipe or Chrome."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.source = cls.root / "modules" / "rcc" / "native-host" / "RelayNativeHostV2.cs"
        cls.csc = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
        if not cls.csc.is_file():
            raise RuntimeError(f"required .NET Framework compiler missing: {cls.csc}")

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="bct-rcc-pipe-acl-"))
        self.host: subprocess.Popen[bytes] | None = None

    def tearDown(self):
        try:
            if self.host is not None:
                try:
                    if self.host.poll() is None:
                        self.host.terminate()
                        try:
                            self.host.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            self.host.kill()
                            self.host.wait(timeout=10)
                finally:
                    for stream in (self.host.stdin, self.host.stdout, self.host.stderr):
                        if stream is not None:
                            stream.close()
        finally:
            shutil.rmtree(self.temp, ignore_errors=False)

    def _compile(self, source: Path, output: Path, *, references: list[Path] | None = None):
        command = [str(self.csc), "/nologo", "/target:exe", f"/out:{output}", str(source)]
        command.extend(f"/reference:{reference}" for reference in references or [])
        completed = subprocess.run(command, capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=60)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    @staticmethod
    def _read_exact(stream, count: int) -> bytes:
        chunks: list[bytes] = []
        while count:
            chunk = stream.read(count)
            if not chunk:
                raise RuntimeError("native host closed before required output")
            chunks.append(chunk)
            count -= len(chunk)
        return b"".join(chunks)

    def _native_message(self, message: dict) -> dict:
        assert self.host is not None and self.host.stdin is not None and self.host.stdout is not None
        encoded = json.dumps(message, separators=(",", ":")).encode("utf-8")
        self.host.stdin.write(struct.pack("<I", len(encoded)) + encoded)
        self.host.stdin.flush()
        results: queue.Queue[dict | Exception] = queue.Queue(maxsize=1)

        def bounded_read():
            try:
                header = self._read_exact(self.host.stdout, 4)
                size = struct.unpack("<I", header)[0]
                if size < 1 or size > 65536:
                    raise ValueError("invalid native framing size")
                results.put(json.loads(self._read_exact(self.host.stdout, size).decode("utf-8")))
            except Exception as exc:
                results.put(exc)

        threading.Thread(target=bounded_read, daemon=True).start()
        try:
            result = results.get(timeout=10)
        except queue.Empty:
            self.fail("disposable host native-ready ACK timed out")
        if isinstance(result, Exception):
            raise result
        return result

    def test_actual_source_host_has_protected_dacl_and_same_session_presence(self):
        host_exe = self.temp / "RelayNativeHostV2.exe"
        self._compile(self.source, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        ack = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:ready-ack", ack["type"])
        self.assertEqual(instance, ack["instanceId"])

        client_source = self.temp / "PipePresenceClient.cs"
        client_source.write_text(r'''
using System;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
class PipePresenceClient {
  static int Main(string[] args) {
    using (var pipe = new NamedPipeClientStream(".", args[0], PipeDirection.InOut)) {
      pipe.Connect(10000);
      Console.WriteLine("SDDL:" + pipe.GetAccessControl().GetSecurityDescriptorSddlForm(AccessControlSections.Access));
      using (var writer = new StreamWriter(pipe, new System.Text.UTF8Encoding(false), 4096, true) { AutoFlush = true })
      using (var reader = new StreamReader(pipe, System.Text.Encoding.UTF8, false, 4096, true)) {
        writer.WriteLine("{\"command\":\"presence\",\"requestId\":\"proof-presence\"}");
        Console.WriteLine("RESPONSE:" + reader.ReadLine());
      }
    }
    return 0;
  }
}
''', encoding="utf-8")
        client_exe = self.temp / "PipePresenceClient.exe"
        self._compile(client_source, client_exe)
        completed = subprocess.run(
            [str(client_exe), ack["pipeName"]], capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=30
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        output = dict(line.split(":", 1) for line in completed.stdout.splitlines() if ":" in line)
        sddl = output["SDDL"]
        self.assertIn("D:P", sddl)
        self.assertIn("S-1-5-5-", sddl)
        self.assertIn(";;;SY)", sddl)
        self.assertNotIn(";;;WD)", sddl)
        self.assertNotIn(";;;AN)", sddl)
        self.assertNotIn(";;;BA)", sddl)
        # Windows prints PipeAccessRights.FullControl as its exact mask
        # (0x1f019f), rather than always using the SDDL FA shorthand.
        aces = re.findall(r"\([^)]*\)", sddl)
        self.assertEqual(2, len(aces), sddl)
        self.assertTrue(all(
            ace.startswith("(A;;0x1f019f;;;") or ace.startswith("(A;;FA;;;")
            for ace in aces
        ), sddl)
        response = json.loads(output["RESPONSE"])
        self.assertEqual("host:result", response["type"])
        self.assertTrue(response["ok"])
        self.assertEqual("proof-presence", response["requestId"])
        self.assertEqual(instance, response["presence"]["instanceId"])

    def test_first_protected_listener_exists_before_ready_ack(self):
        """Immediately consume the actual ACK, then connect within a bounded interval."""
        host_exe = self.temp / "RelayNativeHostV2.exe"
        self._compile(self.source, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        ack = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:ready-ack", ack["type"])
        client_source = self.temp / "ImmediatePipeConnect.cs"
        client_source.write_text(r'''
using System;
using System.IO.Pipes;
class ImmediatePipeConnect {
  static int Main(string[] args) {
    using (var pipe = new NamedPipeClientStream(".", args[0], PipeDirection.InOut)) {
      pipe.Connect(1000);
    }
    return 0;
  }
}
''', encoding="utf-8")
        client_exe = self.temp / "ImmediatePipeConnect.exe"
        self._compile(client_source, client_exe)
        completed = subprocess.run(
            [str(client_exe), ack["pipeName"]], capture_output=True, text=True,
            encoding="mbcs", errors="replace", timeout=10,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_repeated_ready_gets_exact_ack_without_creating_second_listener(self):
        """Preserve the existing Native Messaging ready-ACK idempotency."""
        host_exe = self.temp / "RelayNativeHostV2.exe"
        self._compile(self.source, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        first = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:ready-ack", first["type"])
        second = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual(first, second)

    def test_later_listener_failure_cannot_be_overtaken_by_new_ready_ack(self):
        """Inject failure only at the second pipe instance: no false fresh ACK."""
        source = self.source.read_text(encoding="utf-8-sig")
        field = "static volatile bool PipeStarted = false;"
        constructor = """return new NamedPipeServerStream(
            pipeName, PipeDirection.InOut, 8,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous,
            4096, 4096, security);"""
        self.assertEqual(1, source.count(field))
        self.assertEqual(1, source.count(constructor))
        injected = source.replace(field, field + "\n    static int PipeCreateAttempts = 0;", 1)
        injected = injected.replace(
            constructor,
            'if (Interlocked.Increment(ref PipeCreateAttempts) > 1) '
            'throw new InvalidOperationException("INJECTED_NEXT_LISTENER_FAILURE");\n        '
            + constructor,
            1,
        )
        fixture = self.temp / "RelayNativeHostV2NextFailureFixture.cs"
        fixture.write_text(injected, encoding="utf-8")
        host_exe = self.temp / "RelayNativeHostV2NextFailureFixture.exe"
        self._compile(fixture, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        first = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:ready-ack", first["type"])

        client_source = self.temp / "OneShotPipeConnect.cs"
        client_source.write_text(
            'using System; using System.IO.Pipes; class OneShotPipeConnect { '
            'static int Main(string[] args) { '
            'using (var p=new NamedPipeClientStream(".", args[0], PipeDirection.InOut)) '
            '{ p.Connect(5000); } return 0; } }',
            encoding="utf-8",
        )
        client_exe = self.temp / "OneShotPipeConnect.exe"
        self._compile(client_source, client_exe)
        connected = subprocess.run(
            [str(client_exe), first["pipeName"]], capture_output=True, text=True,
            encoding="mbcs", errors="replace", timeout=10,
        )
        self.assertEqual(0, connected.returncode, connected.stdout + connected.stderr)

        failure = self._native_message({"type": "fixture:noop"})
        self.assertEqual("host:pipe-failure", failure["type"])
        self.assertEqual(instance, failure["instanceId"])
        self.assertEqual("PIPE_LISTENER_FAILED", failure["reason"])
        retry = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:pipe-failure", retry["type"])
        self.assertEqual("PIPE_STARTUP_FAILED", retry["reason"])

    def test_first_listener_creation_failure_has_no_ready_ack(self):
        """Compile only a disposable byte-copy with its exact creation helper forced to fail."""
        source = self.source.read_text(encoding="utf-8-sig")
        original = '''return new NamedPipeServerStream(
            pipeName, PipeDirection.InOut, 8,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous,
            4096, 4096, security);'''
        self.assertIn(original, source)
        injected = source.replace(
            original,
            'throw new InvalidOperationException("INJECTED_FIRST_LISTENER_FAILURE");',
            1,
        )
        fixture_source = self.temp / "RelayNativeHostV2StartupFailureFixture.cs"
        fixture_source.write_text(injected, encoding="utf-8")
        host_exe = self.temp / "RelayNativeHostV2StartupFailureFixture.exe"
        self._compile(fixture_source, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        result = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual("host:pipe-failure", result["type"])
        self.assertEqual(instance, result["instanceId"])
        self.assertEqual("PIPE_STARTUP_FAILED", result["reason"])

    def test_anonymous_token_is_denied_before_opening_disposable_pipe(self):
        """Real Windows Anonymous token; no foreign user account or live host."""
        from ctypes import wintypes

        host_exe = self.temp / "RelayNativeHostV2.exe"
        self._compile(self.source, host_exe)
        instance = f"proof_{uuid.uuid4().hex}"
        self.host = subprocess.Popen(
            [str(host_exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        ack = self._native_message({"type": "host:ready", "instanceId": instance})
        self.assertEqual(instance, ack["instanceId"])
        pipe_path = "\\\\.\\pipe\\" + ack["pipeName"]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        wait_pipe = kernel32.WaitNamedPipeW
        wait_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        wait_pipe.restype = wintypes.BOOL
        self.assertTrue(wait_pipe(pipe_path, 5000), "disposable pipe was not ready")

        get_thread = kernel32.GetCurrentThread
        get_thread.restype = ctypes.c_void_p
        get_thread.argtypes = []
        impersonate = advapi32.ImpersonateAnonymousToken
        impersonate.argtypes = [ctypes.c_void_p]
        impersonate.restype = wintypes.BOOL
        revert = advapi32.RevertToSelf
        revert.argtypes = []
        revert.restype = wintypes.BOOL
        open_pipe = kernel32.CreateFileW
        open_pipe.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ]
        open_pipe.restype = ctypes.c_void_p
        close = kernel32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        close.restype = wintypes.BOOL

        self.assertTrue(impersonate(get_thread()), "anonymous impersonation unavailable")
        handle = None
        error = None
        try:
            handle = open_pipe(pipe_path, 0x80000000, 3, None, 3, 0, None)
            error = ctypes.get_last_error()
        finally:
            reverted = bool(revert())
        if handle not in (None, ctypes.c_void_p(-1).value):
            close(handle)
            self.fail("anonymous caller unexpectedly opened the hardened pipe")
        self.assertTrue(reverted, "failed to revert anonymous thread token")
        self.assertEqual(5, error, f"expected ACCESS_DENIED; got winerror={error}")

    def test_kernel_client_identity_failure_is_fail_closed_before_reader_creation(self):
        source = self.source.read_text(encoding="utf-8-sig")
        handler = source.split("static void HandlePipeClient", 1)[1].split("static void NativeReadLoop", 1)[0]
        self.assertLess(handler.index("IsConnectedClientInServerSession"), handler.index("new StreamReader"))
        host_exe = self.temp / "RelayNativeHostV2.exe"
        self._compile(self.source, host_exe)
        probe_source = self.temp / "InvalidHandleProbe.cs"
        probe_source.write_text(r'''
using System;
using System.Reflection;
using Microsoft.Win32.SafeHandles;
class InvalidHandleProbe {
  static int Main() {
    var method = typeof(RelayNativeHostV2).GetMethod("IsConnectedClientInServerSession", BindingFlags.Static | BindingFlags.NonPublic);
    if (method == null) return 2;
    using (var invalid = new SafePipeHandle(IntPtr.Zero, false)) {
      return (bool)method.Invoke(null, new object[] { invalid, 0 }) ? 3 : 0;
    }
  }
}
''', encoding="utf-8")
        probe_exe = self.temp / "InvalidHandleProbe.exe"
        self._compile(probe_source, probe_exe, references=[host_exe])
        completed = subprocess.run([str(probe_exe)], cwd=self.temp, capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=30)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
