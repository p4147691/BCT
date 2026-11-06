import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bct.features.files import FileWriteFeature
from bct.core.models import PreconditionError


class WritePreflightGuidanceTests(unittest.TestCase):
    def test_missing_and_conflicting_preconditions_are_actionable(self):
        feature = FileWriteFeature()
        with TemporaryDirectory() as root:
            path = str(Path(root) / "sample.txt")
            work = object()
            with patch("bct.features.files.resolve_in_work", return_value=Path(path)):
                for conditions in ({}, {"expected_absent": True, "expected_sha256": "a" * 64}):
                    with self.subTest(conditions=conditions):
                        with self.assertRaises(PreconditionError) as caught:
                            feature.prepare(work=work, arguments={"path": path, "content": "safe", **conditions})
                        message = str(caught.exception)
                        self.assertIn("EXACTLY_ONE_WRITE_PRECONDITION_REQUIRED", message)
                        self.assertIn("expected_absent", message)
                        self.assertIn("expected_sha256", message)


if __name__ == "__main__":
    unittest.main()
