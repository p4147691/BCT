from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.monitor_ui_layout import (
    BUTTONS, DEFAULT, FILENAME, decode_unicode_document,
    load_layout, normalize_layout, read_layout,
)


class MonitorUiLayoutTests(unittest.TestCase):
    def test_default_is_compact_inline_and_keeps_five_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout, status = load_layout(Path(tmp))
        self.assertEqual(status, "READY")
        self.assertEqual(layout["toolbar"]["placement"], "inline")
        self.assertEqual(layout["toolbar"]["density"], "compact")
        self.assertEqual(tuple(layout["toolbar"]["order"]), BUTTONS)
        self.assertFalse(layout["toolbar"]["hidden"])

    def test_roundtrip_unicode_bom_newlines(self):
        raw = json.dumps(DEFAULT, ensure_ascii=False)
        for payload in (
            raw.encode("utf-8"),
            b"\xef\xbb\xbf" + raw.encode("utf-8"),
            raw.replace("\n", "\r\n").encode("utf-16"),
        ):
            with self.subTest(prefix=payload[:4]):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / FILENAME
                    target.write_bytes(payload)
                    self.assertEqual(read_layout(Path(tmp)), normalize_layout(DEFAULT))

    def test_bad_layout_fails_closed_without_actions(self):
        for changes in (
            {"toolbar": {"placement": "javascript:alert(1)"}},
            {"toolbar": {"hidden": ["wrong"]}},
            {"toolbar": {"order": [BUTTONS[0]] * 5}},
            {"toolbar": {"gap": True}},
            {"toolbar": {"gap": 200}},
            {"toolbar": {"css": "body{display:none}"}},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                bad = {**DEFAULT, **changes}
                (Path(tmp) / FILENAME).write_text(json.dumps(bad), encoding="utf-8")
                _layout, status = load_layout(Path(tmp))
                self.assertEqual(status, "INVALID_FALLBACK")

    def test_presentation_values_bounded_and_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = {"version": 1, "toolbar": dict(DEFAULT["toolbar"])}
            (Path(tmp) / FILENAME).write_text(json.dumps(original), encoding="utf-8")
            output = read_layout(Path(tmp))
        self.assertEqual(output["presentation"], DEFAULT["presentation"])
        changed = {**original, "presentation": {
            "nodeTitleFontPx": 14,
            "nodeCardMinHeightPx": 42,
            "nodeGapPx": 9,
            "panelPaddingPx": 12,
            "thumbnailStatusIconPx": 23,
        }}
        self.assertEqual(normalize_layout(changed)["presentation"], changed["presentation"])
        for extra in (
            {"nodeGapPx": -1},
            {"nodeCardMinHeightPx": 400},
            {"nodeTitleFontPx": True},
            {"nodeColumns": 2},
            {"statusColor": "green"},
            {"customCss": "*{display:none}"},
            {"thumbnailStatusIconPx": "22"},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValueError):
                    normalize_layout({**original, "presentation": extra})

    def test_capture_fallback_config_backward_compatible_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = {"version": 1, "toolbar": dict(DEFAULT["toolbar"])}
            (Path(tmp) / FILENAME).write_text(json.dumps(legacy), encoding="utf-8")
            normalized = read_layout(Path(tmp))
        self.assertEqual(normalized["captureFallback"], DEFAULT["captureFallback"])
        for mode in ("last_good", "compact", "legacy"):
            config = {**legacy, "captureFallback": {
                "mode": mode, "staleAfterSeconds": 25, "maxAgeSeconds": 240
            }}
            self.assertEqual(normalize_layout(config)["captureFallback"]["mode"], mode)
        for invalid in (
            {"mode": "execute"},
            {"staleAfterSeconds": True},
            {"staleAfterSeconds": 601},
            {"maxAgeSeconds": 20000},
            {"maxAgeSeconds": 10},
            {"staleAfterSeconds": 100, "maxAgeSeconds": 50},
            {"captureHwnd": "123"},
            {"nativeCaptureAction": "reload"}
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_layout({**legacy, "captureFallback": invalid})

    def test_codec_explicit_avoids_mojibake(self):
        for s in ("한글·ABC·日本語·✓", "😀\n한글"):
            for b in (s.encode("utf-8"), b"\xef\xbb\xbf" + s.encode("utf-8"), s.encode("utf-16")):
                self.assertEqual(decode_unicode_document(b), s)
        with self.assertRaises(UnicodeDecodeError):
            decode_unicode_document(b"\xffthis is not unicode")


if __name__ == "__main__":
    unittest.main()
