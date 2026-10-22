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

    def test_codec_explicit_avoids_mojibake(self):
        for s in ("한글·ABC·日本語·✓", "😀\n한글"):
            for b in (s.encode("utf-8"), b"\xef\xbb\xbf" + s.encode("utf-8"), s.encode("utf-16")):
                self.assertEqual(decode_unicode_document(b), s)
        with self.assertRaises(UnicodeDecodeError):
            decode_unicode_document(b"\xffthis is not unicode")


if __name__ == "__main__":
    unittest.main()
