from __future__ import annotations

import hashlib
import base64
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BrowserModuleBaselineTests(unittest.TestCase):
    def _assert_baseline(self, module: str, *, superseded: frozenset[str] = frozenset()) -> None:
        root = ROOT / "modules" / module
        lines = (root / "BASELINE_SHA256.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            expected, relative = line.split(maxsplit=1)
            if relative in superseded:
                continue
            path = root / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(expected.lower(), hashlib.sha256(path.read_bytes()).hexdigest(), relative)

    def test_proxy_public_source_matches_recovered_live_bytes(self) -> None:
        self._assert_baseline("proxy", superseded=frozenset({"extension/manifest.json"}))

    def test_new_tab_source_matches_recovered_live_bytes(self) -> None:
        self._assert_baseline("chatgpt-new-tab", superseded=frozenset({"extension/manifest.json"}))

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

    @staticmethod
    def _extension_id(key: str) -> str:
        digest = hashlib.sha256(base64.b64decode(key)).digest()[:16]
        alphabet = "abcdefghijklmnop"
        return "".join(alphabet[value >> 4] + alphabet[value & 15] for value in digest)

    def test_replacement_extensions_have_fixed_bct_identities(self) -> None:
        cases = (
            ("proxy", "BCT Auto Proxy", "belokajbbpdnchnobjmmllelhmiajikn"),
            ("chatgpt-new-tab", "BCT ChatGPT New Tab", "gnfgcjpnkiedhdgblldjehjelnikkhif"),
        )
        for module, name, expected_id in cases:
            manifest = json.loads(
                (ROOT / "modules" / module / "extension" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(name, manifest["name"])
            self.assertEqual("1.0.0", manifest["version"])
            self.assertEqual(expected_id, self._extension_id(manifest["key"]))


if __name__ == "__main__":
    unittest.main()
