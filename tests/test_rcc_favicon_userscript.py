"""CI gate for the isolated RCC Chrome node-number favicon userscript.

Runs the zero-Chrome/zero-extension Node VM regressions; the physical browser
smoke remains a local, separate test and never touches the operating profile.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules" / "rcc" / "favicons" / "test_chatgpt_node_favicon.cjs"


class RccFaviconUserscriptTests(unittest.TestCase):
    def test_event_driven_node_favicon_contract(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required to validate the RCC userscript")
        result = subprocess.run(
            [node, str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("ALL 19 FAVICON ISOLATED REGRESSIONS PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
