"""UTF-8 input, Windows child argv, CLI serialization boundary regressions.

Fixture only; writes into TemporaryDirectory, never BCT LIVE state.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

URL = "https://chatgpt.com/c/6ad49131-eecc-83ee-8949-9956d2d2c82c"
WORK = "BCT-V2-METADATA-UTF8-ISOLATED"

class MetadataWindowsUnicodeTests(unittest.TestCase):
    def test_korean_browser_input_cli_arguments_and_cache_preserve_unicode(self):
        title = "한국어 대화 제목"
        summary = "과거 기록 검증과 영속 저장 결정"
        text = "내가 한 말: 이전 기록\nChatGPT 답변: 정상 한글"
        with tempfile.TemporaryDirectory(prefix="bct-v2-meta-") as temp:
            root = Path(temp) / "cache"
            payload = Path(temp) / "input.json"
            payload.write_text(json.dumps({"kind":"text","text":text},ensure_ascii=False),encoding="utf-8")
            command = [sys.executable, "-m", "bct.conversation_history",
                       "--root", str(root)]
            env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
                   + os.pathsep + os.environ.get("PYTHONPATH", "")}
            created = subprocess.run(command+["capture","--work-id",WORK,
                "--url",URL,"--title",title,"--summary",summary,"--input",str(payload)],
                capture_output=True,text=True,encoding="utf-8",errors="strict",
                env=env,timeout=20)
            self.assertEqual(0,created.returncode,created.stderr)
            captured = json.loads(created.stdout)
            self.assertEqual(title,captured["title"])
            self.assertEqual(summary,captured["summary"])
            loaded = subprocess.run(command+["latest","--work-id",WORK,
                "--url",URL,"--tail","200"],capture_output=True,text=True,
                encoding="utf-8",errors="strict",env=env,timeout=20)
            self.assertEqual(0,loaded.returncode,loaded.stderr)
            record = json.loads(loaded.stdout)
            self.assertEqual(title,record["title"])
            self.assertEqual(summary,record["summary"])
            self.assertEqual(text,record["loaded_text_tail"])
            self.assertEqual("LOADED_PAGE_ONLY",record["coverage"])
            self.assertFalse(record["full_history_verified"])

    def test_already_corrupted_metadata_is_not_reconstructed(self):
        from bct.conversation_history import ConversationEvidenceCache
        with tempfile.TemporaryDirectory(prefix="bct-v2-lossy-") as temp:
            cache=ConversationEvidenceCache(Path(temp)/"cache")
            cache.capture(work_id=WORK,conversation_url=URL,title="???",
                page_text="내가 한 말: 정상",summary="???")
            row=cache.latest(work_id=WORK,conversation_url=URL)
            self.assertEqual("???",row["title"])
            self.assertEqual("???",row["summary"])
            self.assertIn("정상",row["page_text"])


    def test_strict_utf8_metadata_file_roundtrip_under_legacy_output_codepage(self):
        title = "영속 시스템 체크 · 이전 기록"
        summary = "원문 보존·메시지 중복 제거·다음 실행 판단"
        with tempfile.TemporaryDirectory(prefix="bct-v2-meta-file-") as temp:
            root = Path(temp) / "cache"
            input_file = Path(temp) / "input.json"
            meta_file = Path(temp) / "metadata.json"
            input_file.write_text(json.dumps(
                {"kind": "text", "text": "내가 한 말: 원문\nChatGPT 답변: 정상"},
                ensure_ascii=False), encoding="utf-8")
            meta_file.write_text(json.dumps(
                {"schema": "BCT_CONVERSATION_METADATA_V1", "title": title,
                 "summary": summary}, ensure_ascii=False), encoding="utf-8")
            program = [sys.executable, "-m", "bct.conversation_history",
                       "--root", str(root)]
            env = {**os.environ, "PYTHONIOENCODING": "cp1252:strict",
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
                   + os.pathsep + os.environ.get("PYTHONPATH", "")}
            created = subprocess.run(program + [
                "capture", "--work-id", WORK, "--url", URL,
                "--metadata-input", str(meta_file), "--input", str(input_file)
            ], capture_output=True, text=True, encoding="utf-8", errors="strict",
                env=env, timeout=20)
            self.assertEqual(0, created.returncode, created.stderr)
            self.assertEqual(title, json.loads(created.stdout)["title"])
            retrieved = subprocess.run(program + [
                "latest", "--work-id", WORK, "--url", URL, "--tail", "80"
            ], capture_output=True, text=True, encoding="utf-8", errors="strict",
                env=env, timeout=20)
            self.assertEqual(0, retrieved.returncode, retrieved.stderr)
            value = json.loads(retrieved.stdout)
            self.assertEqual(title, value["title"])
            self.assertEqual(summary, value["summary"])
            self.assertFalse(value["full_history_verified"])

    def test_bad_metadata_encoding_is_rejected_without_cache_effect(self):
        from bct.conversation_history import metadata_from_json_file
        from bct.conversation_history import ConversationEvidenceError
        with tempfile.TemporaryDirectory(prefix="bct-v2-bad-encoding-") as temp:
            bad = Path(temp) / "metadata.json"
            bad.write_bytes(b'{"schema":"BCT_CONVERSATION_METADATA_V1","title":"\xff"}')
            with self.assertRaises(ConversationEvidenceError):
                metadata_from_json_file(bad)
            self.assertFalse((Path(temp) / "cache").exists())

    def test_invalid_or_conflicting_metadata_inputs_do_not_capture(self):
        from bct.conversation_history import metadata_from_json_file
        from bct.conversation_history import ConversationEvidenceError
        with tempfile.TemporaryDirectory(prefix="bct-v2-meta-schema-") as temp:
            path = Path(temp) / "metadata.json"
            path.write_text('{"schema":"BCT_CONVERSATION_METADATA_V1","title":12}',
                            encoding="utf-8")
            with self.assertRaises(ConversationEvidenceError):
                metadata_from_json_file(path)
            program = [sys.executable, "-m", "bct.conversation_history",
                       "--root", str(Path(temp) / "cache")]
            process = subprocess.run(program + [
                "capture", "--work-id", WORK, "--url", URL,
                "--title", "legacy", "--metadata-input", str(path)
            ], input="내가 한 말: 정상", capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
                env={**os.environ,
                     "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
                     + os.pathsep + os.environ.get("PYTHONPATH", "")})
            self.assertNotEqual(0, process.returncode)
            self.assertFalse((Path(temp) / "cache").exists())

if __name__ == "__main__":
    unittest.main()
