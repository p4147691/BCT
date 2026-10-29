"""Run the real RCC source and PR352 userscript event VMs in BCT CI."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "modules/rcc/extension/test_node_favicon_notify_v1.js",
    "modules/rcc/extension/test_node_favicon_fullchain_v1.js",
    "modules/rcc/favicons/test_chatgpt_node_favicon.cjs",
)


class NodeFaviconRccIntegrationTests(unittest.TestCase):
    def test_source_event_transports_and_existing_renderer(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "RCC event validation requires Node.js")
        for script in SCRIPTS:
            with self.subTest(script=script):
                result = subprocess.run(
                    [node, str(ROOT / script)],
                    cwd=ROOT, capture_output=True, text=True, timeout=25, check=False
                )
                self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
