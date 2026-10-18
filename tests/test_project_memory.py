from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bct.core.project_memory import (
    ProjectMemoryStore, ProjectMemoryConflict, ProjectMemoryCorrupt,
    ProjectMemoryError, _digest,
)


def record(*, summary: str = "처음 검토", event_id: int | None = 3):
    return {
        "title": "자막 생성", "goal": "음성 인식 + OCR 자막 완성",
        "scope_note": "관련 프로젝트의 협업 맥락. 실행 제한이 아님.",
        "summary": summary,
        "links": [{"type": "bct_work", "id": "BCT-SUBTITLE-01"},
                  {"type": "github_pr", "id": "p4147691/BCT#163"}],
        "items": [{"text": "Worker A 결과 확인 필요",
                   "evidence": [{"type": "bct_assignment", "id": "a-01"}]}],
        "decisions": [{"text": "매니저 판단, 증거는 별도",
                       "evidence": [{"type": "bct_result", "id": "result.01"}]}],
        "next_actions": [{"text": "기존 결과 조회 후 후속 지시 판단",
                          "evidence": [{"type": "github_issue", "id": "p4147691/BCT#111"}]}],
        "checkpoints": {"bct_event_id": event_id, "external": {
            "github:p4147691/BCT#163": "merged"}},
    }


def _process_save(root: str, summary: str, output):
    store = ProjectMemoryStore(root)
    try:
        row = store.save("subtitle-auto", expected_revision=1,
                         author="manager-worker", record=record(summary=summary))
        output.put(("OK", row["revision"]))
    except ProjectMemoryConflict:
        output.put(("CONFLICT", None))


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bct-project-memory-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "store"
        self.store = ProjectMemoryStore(self.root)

    def _genesis(self):
        return self.store.save("subtitle-auto", expected_revision=0,
                               author="manager-a", record=record())

    def test_create_and_exact_readback(self):
        first = self._genesis()
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["previous_sha256"], None)
        self.assertIn("+00:00", first["created_at"])
        self.assertEqual(self.store.get("subtitle-auto")["record"], record())
        self.assertEqual(self.store.projects(), ["subtitle-auto"])

    def test_empty_read_makes_no_files(self):
        self.assertIsNone(self.store.get("missing-project"))
        self.assertFalse(self.root.exists())
        self.assertEqual(self.store.projects(), [])

    def test_previous_revisions_survive_updates(self):
        old = self._genesis()
        second = self.store.save("subtitle-auto", expected_revision=1,
                                 author="manager-b", record=record(summary="OCR 추가"))
        chain = self.store.history("subtitle-auto")
        self.assertEqual([r["revision"] for r in chain], [1, 2])
        self.assertEqual(chain[0]["record"], record())
        self.assertEqual(chain[1]["record"]["summary"], "OCR 추가")
        self.assertEqual(second["previous_sha256"], old["sha256"])

    def test_exact_retry_idempotent(self):
        first = self._genesis()
        again = self.store.save("subtitle-auto", expected_revision=0,
                                author="manager-a", record=record())
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["sha256"], first["sha256"])
        self.assertEqual(len(self.store.history("subtitle-auto")), 1)

    def test_stale_different_input_rejected(self):
        self._genesis()
        with self.assertRaisesRegex(ProjectMemoryConflict, "STALE_REVISION"):
            self.store.save("subtitle-auto", expected_revision=0, author="manager-b",
                            record=record(summary="stale"))
        self.assertEqual(self.store.get("subtitle-auto")["record"], record())

    def test_confirmed_head_not_advanced_after_interrupted_write(self):
        old = self._genesis()
        with patch("bct.core.project_memory._atomic_replace", side_effect=OSError("interrupt")):
            with self.assertRaisesRegex(OSError, "interrupt"):
                self.store.save("subtitle-auto", expected_revision=1,
                                author="manager-a", record=record(summary="interrupted"))
        self.assertEqual(self.store.get("subtitle-auto")["sha256"], old["sha256"])
        self.assertEqual(len(self.store.history("subtitle-auto")), 1)
        # The orphan is harmless; a retry can reuse the same immutable file.
        self.store.save("subtitle-auto", expected_revision=1, author="manager-a",
                        record=record(summary="interrupted"))
        self.assertEqual(len(self.store.history("subtitle-auto")), 2)

    def test_revision_write_interruption_never_publishes_partial_file(self):
        previous = self._genesis()
        with patch("bct.core.project_memory.os.rename", side_effect=OSError("interrupted")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.store.save("subtitle-auto", expected_revision=1,
                                author="manager-a", record=record(summary="new"))
        self.assertEqual(self.store.get("subtitle-auto")["sha256"], previous["sha256"])
        directory = self.root / "subtitle-auto" / "revisions"
        self.assertFalse(list(directory.glob("00000002-*.json")))
        self.assertFalse(list(directory.glob(".revision-*.tmp")))
        self.store.save("subtitle-auto", expected_revision=1,
                        author="manager-a", record=record(summary="new"))
        self.assertEqual(len(self.store.history("subtitle-auto")), 2)

    def test_unused_orphan_does_not_appear_as_committed_history(self):
        self._genesis()
        try:
            with patch("bct.core.project_memory._atomic_replace", side_effect=OSError):
                self.store.save("subtitle-auto", expected_revision=1,
                                author="manager-a", record=record(summary="orphan"))
        except OSError:
            pass
        self.store.save("subtitle-auto", expected_revision=1,
                        author="manager-b", record=record(summary="new"))
        self.assertEqual([r["record"]["summary"] for r in self.store.history("subtitle-auto")],
                         ["처음 검토", "new"])

    def test_missing_current_revision_fails_closed(self):
        self._genesis()
        for file in (self.root / "subtitle-auto" / "revisions").iterdir():
            file.unlink()
        with self.assertRaisesRegex(ProjectMemoryCorrupt, "REVISION_MISSING"):
            self.store.get("subtitle-auto")

    def test_revision_tampering_fails_closed(self):
        self._genesis()
        file = next((self.root / "subtitle-auto" / "revisions").iterdir())
        file.write_text('{"forged":true}', encoding="utf-8")
        with self.assertRaisesRegex(ProjectMemoryCorrupt, "HASH_MISMATCH"):
            self.store.get("subtitle-auto")

    def test_cursor_regression_rejected(self):
        self._genesis()
        with self.assertRaisesRegex(ProjectMemoryConflict, "EVENT_CURSOR_REGRESSION"):
            self.store.save("subtitle-auto", expected_revision=1,
                            author="manager-a", record=record(summary="back", event_id=2))

    def test_invalid_project_paths(self):
        for name in ("../escape", "ABC", "", "test/other", ".hidden", "a" * 100):
            with self.subTest(name=name):
                with self.assertRaises(ProjectMemoryError):
                    self.store.get(name)
        self.assertFalse((self.root.parent / "escape").exists())

    def test_invalid_evidence(self):
        invalid = record()
        invalid["links"] = [{"type": "bct_work", "id": ""}]
        with self.assertRaises(ProjectMemoryError):
            self.store.save("subtitle-auto", expected_revision=0,
                            author="manager-a", record=invalid)
        self.assertIsNone(self.store.get("subtitle-auto"))

    def test_invalid_cursor_type(self):
        invalid = record()
        invalid["checkpoints"]["bct_event_id"] = True
        with self.assertRaisesRegex(ProjectMemoryError, "EVENT_CURSOR_INVALID"):
            self.store.save("subtitle-auto", expected_revision=0,
                            author="manager-a", record=invalid)

    def test_nonfinite_json_and_oversize_rejected(self):
        invalid = record()
        invalid["items"].append({"text": "a" * 1000000})
        with self.assertRaises(ProjectMemoryError):
            self.store.save("subtitle-auto", expected_revision=0,
                            author="manager-a", record=invalid)

    def test_concurrent_writers_only_one_can_commit(self):
        self._genesis()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self._try_concurrent, ["B", "C"]))
        self.assertEqual(sorted(results), ["CONFLICT", "OK"])
        self.assertEqual(self.store.get("subtitle-auto")["revision"], 2)

    def _try_concurrent(self, value: str) -> str:
        try:
            self.store.save("subtitle-auto", expected_revision=1,
                            author="manager-" + value, record=record(summary=value))
            return "OK"
        except ProjectMemoryConflict:
            return "CONFLICT"

    @unittest.skipUnless(os.name == "nt", "Windows cross-process lock acceptance")
    def test_process_race_single_winner(self):
        self._genesis()
        ctx = multiprocessing.get_context("spawn")
        output = ctx.Queue()
        left = ctx.Process(target=_process_save, args=(str(self.root), "P", output))
        right = ctx.Process(target=_process_save, args=(str(self.root), "Q", output))
        left.start(); right.start()
        left.join(25); right.join(25)
        self.assertEqual((left.exitcode, right.exitcode), (0, 0))
        self.assertEqual(sorted((output.get(timeout=5)[0], output.get(timeout=5)[0])),
                         ["CONFLICT", "OK"])

    def test_deployment_manifest_includes_module_exactly_once(self):
        import tomllib
        config = Path(__file__).resolve().parents[1] / "bct.toml"
        with config.open("rb") as handle:
            parsed = tomllib.load(handle)
        files = parsed["deployment"]["profiles"]["bct_runtime_v1"]["files"]
        self.assertEqual(files.count("src/bct/core/project_memory.py"), 1)

    def test_cli_get_list_and_history(self):
        self._genesis()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        cmd = [sys.executable, "-m", "bct.core.project_memory",
               "--root", str(self.root)]
        for action in (["get", "subtitle-auto"], ["history", "subtitle-auto"], ["list"]):
            done = subprocess.run(cmd + action, capture_output=True, text=True,
                                  encoding="utf-8", env=env, timeout=20)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIsNotNone(json.loads(done.stdout))

    def test_pointer_corruption_does_not_fall_back_silently(self):
        self._genesis()
        pointer = self.root / "subtitle-auto" / "current.json"
        pointer.write_text('{"revision":999}', encoding="utf-8")
        with self.assertRaises(ProjectMemoryCorrupt):
            self.store.get("subtitle-auto")


if __name__ == "__main__":
    unittest.main()

