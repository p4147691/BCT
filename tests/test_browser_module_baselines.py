from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BrowserModuleBaselineTests(unittest.TestCase):
    def _assert_baseline(self, module: str) -> None:
        root = ROOT / "modules" / module
        lines = (root / "BASELINE_SHA256.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            expected, relative = line.split(maxsplit=1)
            path = root / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(expected.lower(), hashlib.sha256(path.read_bytes()).hexdigest(), relative)

    def test_proxy_public_source_matches_recovered_live_bytes(self) -> None:
        self._assert_baseline("proxy")

    def test_new_tab_source_matches_recovered_live_bytes(self) -> None:
        self._assert_baseline("chatgpt-new-tab")

    def test_proxy_secrets_and_runtime_assets_are_not_tracked(self) -> None:
        root = ROOT / "modules" / "proxy"
        forbidden = (
            "private",
            "extension/local-token.js",
            "wireproxy.conf",
            "wireproxy.exe",
            "helper.log",
        )
        for relative in forbidden:
            self.assertFalse((root / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
