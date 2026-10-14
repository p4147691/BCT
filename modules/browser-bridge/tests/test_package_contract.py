import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ID = "acdgnmbgpkfjkckccbhmccojgigbfcge"
HOST = "com.bct.browser_bridge.prototype"
ORIGIN = f"chrome-extension://{EXTENSION_ID}/"


class PackageContractTests(unittest.TestCase):
    def test_extension_id_is_pinned_by_manifest_key(self):
        manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        public_key = __import__("base64").b64decode(manifest["key"])
        extension_id = "".join("abcdefghijklmnop"[value] for byte in hashlib.sha256(public_key).digest()[:16] for value in (byte >> 4, byte & 15))
        self.assertEqual(EXTENSION_ID, extension_id)

    def test_host_template_has_only_the_pinned_origin(self):
        manifest = json.loads((ROOT / "native" / "host-manifest.template.json").read_text(encoding="utf-8"))
        self.assertEqual(HOST, manifest["name"])
        self.assertEqual([ORIGIN], manifest["allowed_origins"])
        self.assertEqual("SET_ABSOLUTE_HOST_EXE_PATH_ONLY_AFTER_APPROVAL", manifest["path"])

    def test_no_runtime_artifacts_are_packaged(self):
        forbidden_suffixes = {".exe", ".dll", ".pyc", ".pem", ".token"}
        found = [path.relative_to(ROOT) for path in ROOT.rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() in forbidden_suffixes]
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
