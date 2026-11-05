from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class PinnedNativeTransportTests(unittest.TestCase):
    def test_bridge_fixed_id_and_host_name_unchanged(self):
        manifest=json.loads((ROOT/"extension"/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["nativeMessaging"],manifest["permissions"])
        self.assertNotIn("host_permissions",manifest)
        host=json.loads((ROOT/"native"/"host-manifest.template.json").read_text(encoding="utf-8"))
        self.assertEqual("com.bct.browser_bridge.prototype",host["name"])
        self.assertEqual(
            ["chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/"],
            host["allowed_origins"])
        background=(ROOT/"extension"/"background.js").read_text(encoding="utf-8")
        self.assertIn("NATIVE_DISCONNECTED_NO_RETRY",background)
        self.assertIn("BRIDGE_NODE_NATIVE_DISCONNECTED_NO_RETRY",background)
        self.assertNotIn("chrome.tabs.executeScript",background)
        self.assertNotIn("chrome.scripting.executeScript",background)
        self.assertNotIn("node_relay_send_to_chatgpt",background)

    def test_node_host_disabled_by_default_and_separate_from_mcp(self):
        native=(ROOT/"native"/"node_relay_native.py").read_text(encoding="utf-8")
        original=(ROOT/"native"/"persistent_host.py").read_text(encoding="utf-8")
        self.assertIn('BCT_BRIDGE_NODE_RELAY_ENABLED',native)
        self.assertIn('BRIDGE_NODE_RELAY_DISABLED',native)
        self.assertIn('startswith("node_relay_")',original)
        self.assertLess(original.index('startswith("node_relay_")'),
                        original.index("if not WORK_ID or not TOKEN_PATH.is_file():"))
        self.assertIn("serve_node_session",original)

    @unittest.skipUnless(shutil.which("node"),"Node.js is not installed")
    def test_pinned_extension_native_reconnect_no_automatic_resend(self):
        r=subprocess.run(["node","tests/test_node_native_extension.js"],
                         cwd=ROOT,capture_output=True,text=True,
                         timeout=15,check=False)
        self.assertEqual(0,r.returncode,r.stderr or r.stdout)
        self.assertIn("PASS",r.stdout)


if __name__=="__main__":
    unittest.main()
