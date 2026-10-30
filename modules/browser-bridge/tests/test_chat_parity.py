"""Independent Local Bridge parity: strict chat READ and Native Host boundary."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChatParityTests(unittest.TestCase):
    def test_manifest_is_exact_chatgpt_opt_in_only(self):
        manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["https://chatgpt.com/c/*"], manifest["content_scripts"][0]["matches"])
        self.assertEqual(["chat_protocol.js", "chat_content.js"], manifest["content_scripts"][0]["js"])
        self.assertFalse(manifest["content_scripts"][0]["all_frames"])
        self.assertEqual(set(["activeTab", "nativeMessaging", "storage"]), set(manifest["permissions"]))
        self.assertNotIn("externally_connectable", manifest)
        self.assertNotIn("host_permissions", manifest)

    def test_browser_protocol_and_background_mock(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is unavailable")
        result = subprocess.run(
            [node, str(ROOT / "tests/check_chat_parity.cjs")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=25, check=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        self.assertEqual(0, result.returncode, output)
        self.assertIn("pass 5", output)

    def test_existing_native_host_has_no_chat_execution_privilege(self):
        source = (ROOT / "native/native_host.py").read_text(encoding="utf-8")
        self.assertIn('("bridge_read", "receipt_lookup")', source)
        self.assertIn('"capability"] != "read"', source)
        self.assertNotIn("bct_execute", source)


if __name__ == "__main__":
    unittest.main()
