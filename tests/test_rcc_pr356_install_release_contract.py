"""Guard the exact PR356 RCC cutover assets and runtime inclusion without using live paths."""
import hashlib
from pathlib import Path
import tomllib
import unittest

from bct import rcc_protected_install as rcc


class CurrentRccInstallContractTests(unittest.TestCase):
    def test_protected_installer_shipped_with_core_release(self):
        root = Path(__file__).resolve().parents[1]
        options = tomllib.loads((root / "bct.toml").read_text(encoding="utf-8"))
        files = options["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertIn("src/bct/rcc_protected_install.py", files)
        self.assertIn("src/bct/features/deploy.py", files)
        self.assertTrue((root / "src/bct/rcc_protected_install.py").is_file())

    def test_candidate_identity_is_pinned_to_pr356_and_unique_rollback(self):
        self.assertEqual(
            r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\candidate_receipt_58",
            str(rcc.EXACT_STAGE),
        )
        self.assertEqual(
            r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\rollback_installed_58",
            str(rcc.EXACT_ROLLBACK),
        )
        self.assertEqual(
            r"D:\BCT\data\RCC_PR362_58TO58_PREP_20261030\release_manifest_58to58_immutable.json",
            str(rcc.EXACT_MANIFEST),
        )
        self.assertEqual(
            "b35f64eccce91c1263cb85932c7c882bb181790ab2b3d406937e380e87b9f244",
            rcc.PINNED_MANIFEST_SHA256,
        )
        self.assertEqual(
            "ocbidbaplechjjdacmokhnfbdmgjkphf",
            rcc.EXTENSION_ID,
        )


if __name__ == "__main__":
    unittest.main()
