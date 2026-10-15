"""Native launcher -> Python host isolated framed acceptance (Windows, no Core/registry)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "native" / "launcher" / "bin" / "Release" / "net8.0"
ORIGIN = "chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"


class BuiltLauncherBoundaryTests(unittest.TestCase):
    def test_real_launcher_to_python_framing_and_fail_closed(self):
        self.assertEqual(os.name, "nt", "Windows runner required")
        self.assertTrue((BUILT / "BctBridgeHost.exe").is_file(), "dotnet build required")
        with tempfile.TemporaryDirectory(prefix="bct-bridge-launcher-") as tmp:
            stage = Path(tmp)
            launch = stage / "launcher"
            launch.mkdir()
            for name in ("BctBridgeHost.exe", "BctBridgeHost.dll", "BctBridgeHost.deps.json", "BctBridgeHost.runtimeconfig.json"):
                source = BUILT / name
                if source.exists():
                    shutil.copy2(source, launch / name)
            shutil.copy2(ROOT/"native"/"persistent_host.py", stage/"persistent_host.py")
            shutil.copy2(ROOT/"native"/"native_host.py", stage/"native_host.py")
            env = dict(os.environ)
            env.update(BCT_BRIDGE_EXTENSION_ORIGIN=ORIGIN, BCT_BRIDGE_PYTHON_EXE=str(Path(sys.executable).resolve()),
                       BCT_BRIDGE_PYTHON_SHA256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                       BCT_BRIDGE_MCP_URL="http://127.0.0.1:19991/mcp", BCT_BRIDGE_WORK_ID="",
                       BCT_BRIDGE_TOKEN_PATH=str(stage/"absent.token"))
            exe = str(launch/"BctBridgeHost.exe")
            wrong = subprocess.run([exe, "chrome-extension://wrong/"], input=b"", capture_output=True, env=env, timeout=15)
            self.assertEqual(4, wrong.returncode)
            self.assertEqual(b"", wrong.stdout)
            env["BCT_BRIDGE_PYTHON_EXE"] = "python"
            denied = subprocess.run([exe, ORIGIN], input=b"", capture_output=True, env=env, timeout=15)
            self.assertEqual(5, denied.returncode)
            env["BCT_BRIDGE_PYTHON_EXE"] = str(Path(sys.executable).resolve())
            correct_sha = env["BCT_BRIDGE_PYTHON_SHA256"]
            env["BCT_BRIDGE_PYTHON_SHA256"] = "0" * 64
            bad_digest = subprocess.run([exe, ORIGIN], input=b"", capture_output=True, env=env, timeout=15)
            self.assertEqual(5, bad_digest.returncode)
            env["BCT_BRIDGE_PYTHON_SHA256"] = correct_sha
            payload = json.dumps({"schema_version":1, "type":"bridge_read", "request_id":"a"*32,
                                  "operation_id":"a"*32, "capability":"read", "arguments":{"path":"fixture"}}).encode()
            proc = subprocess.run([exe, ORIGIN], input=struct.pack("<I",len(payload))+payload,
                                  capture_output=True, env=env, timeout=15)
            self.assertEqual(4, proc.returncode, proc.stderr.decode(errors="replace"))
            self.assertGreaterEqual(len(proc.stdout), 4)
            n = struct.unpack("<I", proc.stdout[:4])[0]
            reply = json.loads(proc.stdout[4:4+n])
            self.assertEqual("AUTH_DENIED", reply["outcome"])
            self.assertEqual("a"*32, reply["request_id"])


if __name__ == "__main__":
    unittest.main()
