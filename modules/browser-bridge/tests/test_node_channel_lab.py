from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "node-channel"


class IndependentNodeChannelLabTests(unittest.TestCase):
    def test_existing_bridge_identity_and_permissions_remain_unmodified(self):
        product = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        node = json.loads((LAB / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["nativeMessaging"], product["permissions"])
        self.assertNotIn("host_permissions", product)
        self.assertNotIn("key", node)
        self.assertNotIn("nativeMessaging", node["permissions"])
        self.assertEqual(["https://chatgpt.com/*"], node["host_permissions"])
        self.assertIn("tabs", node["permissions"])
        self.assertIn("scripting", node["permissions"])
        self.assertNotIn("externally_connectable", node)
        self.assertNotIn("content_scripts", node)
        self.assertNotIn("nativeMessaging", (LAB / "worker.js").read_text(encoding="utf-8"))

    def test_injected_reader_is_bounded_and_non_mutating(self):
        code = (LAB / "page_reader.js").read_text(encoding="utf-8")
        for forbidden in ("fetch(", "XMLHttpRequest", "chrome.runtime.sendMessage(",
                          "click(", "execCommand(", "localStorage", "sessionStorage",
                          "postMessage(", "navigator.clipboard", "keydown"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, code)
        self.assertIn("slice(0,2400)", code)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_three_exact_nodes_and_readonly_transport(self):
        for name in ("test_node_channel.js", "test_page_reader.js"):
            with self.subTest(script=name):
                result = subprocess.run(
                    ["node", name], cwd=LAB, capture_output=True,
                    text=True, timeout=15, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr or result.stdout)
                self.assertIn("PASS", result.stdout)

    def test_no_shared_runtime_or_executable(self):
        existing = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("background.js", existing["background"]["service_worker"])
        forbidden = {".exe", ".dll", ".token", ".pem", ".pyc"}
        self.assertEqual([], [
            p.relative_to(LAB).as_posix() for p in LAB.rglob("*")
            if p.is_file() and p.suffix.lower() in forbidden
        ])


if __name__ == "__main__":
    unittest.main()
