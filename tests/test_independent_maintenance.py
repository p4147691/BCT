from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from bct_maintenance.cli import Maintenance, digest, state_snapshot
from bct_maintenance.errors import PreconditionError, UnknownEffectError
from bct_maintenance.locking import maintenance_lock
from bct_maintenance.releases import _write_current
from bct_maintenance.service_runtime import atomic_json, process_identity


SERVER = '''
import argparse, json, os, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
p=argparse.ArgumentParser()
for name in ('runtime-root','service-name','release-sha','manifest-sha256','generation','instance-id','port'):
    p.add_argument('--'+name, required=True)
a=p.parse_args(); root=Path(a.runtime_root)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        receipt=json.loads((root/'service.json').read_text())
        health={**receipt,'ready':True,'status':'OK','mcp_ready':True,
                'maintenance_contract':1,'maintenance_paused':(root/'BCT_MAINTENANCE.PAUSE').is_file(),
                'mcp_endpoint':'http://127.0.0.1:'+a.port+'/mcp'}
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(health).encode())
    def do_POST(self):
        if self.path!='/shutdown' or self.headers.get('X-BCT-Control-Token')!=os.environ['BCT_CONTROL_TOKEN']:
            self.send_response(403); self.end_headers(); return
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        threading.Thread(target=server.shutdown,daemon=True).start()
    def log_message(self,*args): pass
server=HTTPServer(('127.0.0.1',int(a.port)), Handler)
server.serve_forever(); server.server_close()
'''


class IndependentMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bct-independent-maintenance-")
        self.base = Path(self.temp.name)
        self.root = self.base / "runtime"
        (self.root / "state").mkdir(parents=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.policy = self.base / "trusted.toml"
        self.files = ["bct.toml", "src/bct/__init__.py", "src/bct/runtime_server.py"]
        self.policy.write_text(
            '[deployment.profiles.test_runtime]\nsource_root = '+json.dumps(str(self.base / "source"))+
            '\nruntime_root = '+json.dumps(str(self.root))+
            '\nservice_name = "bct-test"\nport = '+str(port)+
            '\nfiles = '+json.dumps(self.files)+'\n', encoding="utf-8")
        with closing(sqlite3.connect(self.root / "state" / "state.sqlite", isolation_level=None)) as db:
            db.executescript('CREATE TABLE operations(operation_id TEXT,state TEXT);'
                             'CREATE TABLE resource_claims(resource_key TEXT,unresolved INTEGER);'
                             'CREATE TABLE preserved(value TEXT); INSERT INTO preserved VALUES("keep");')
        self.good = self.make_release("a" * 40)
        self.bad = self.make_release("b" * 40, broken=True)
        self.schema = state_snapshot(self.root)["schema_sha256"]
        self.config = self.base / "maintenance.json"
        self.settings = {
            "schema": 1, "enabled": True, "policy_path": str(self.policy),
            "policy_sha256": digest(self.policy), "profile": "test_runtime",
            "runtime_root": str(self.root), "python_path": sys.executable,
            "admission_releases": [self.good["source_head"], self.bad["source_head"]],
            "allowed_actions": ["start", "stop", "stop-unresponsive", "recover", "activate", "backup"],
            "verified_releases": {r["source_head"]: {"manifest_sha256": r["manifest_sha256"],
                                     "compatible_schema_sha256": [self.schema]} for r in (self.good, self.bad)}}
        self.save_config()
        self.tool = Maintenance(self.config)
        _write_current(self.tool.profile, self.good)
        (self.root / "BCT_CORE_SUPERVISOR.STOP").touch()
        (self.root / "BCT_MAINTENANCE.PAUSE").touch()
        self.tool.controller.readiness_timeout = 1

    def save_config(self):
        atomic_json(self.config, self.settings)

    def make_release(self, sha, broken=False):
        release_root = self.root / "releases" / sha
        (release_root / "src" / "bct").mkdir(parents=True)
        (release_root / "bct.toml").write_bytes(self.policy.read_bytes())
        (release_root / "src/bct/__init__.py").write_text(
            'raise RuntimeError("broken BCT package")\n' if broken else '', encoding="utf-8")
        (release_root / "src/bct/runtime_server.py").write_text(SERVER, encoding="utf-8")
        files = {name: digest(release_root / name) for name in self.files}
        manifest = {"source_head": sha, "release_path": str(release_root), "files": files,
                    "manifest_sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        atomic_json(release_root / "manifest.json", manifest)
        return manifest

    def tearDown(self):
        try:
            self.tool.controller.stop()
        finally:
            self.temp.cleanup()

    def run_action(self, action, op="one", **kw):
        return self.tool.run(action, operation_id=op, expected_current=self.good["source_head"], **kw)

    def test_external_cli_imports_no_bct_even_when_bct_is_broken(self):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([
            str(Path(self.bad["release_path"]) / "src"), str(Path(__file__).resolve().parents[1] / "src")]))
        script = 'import sys; from bct_maintenance.cli import main; rc=main(sys.argv[1:]); assert "bct" not in sys.modules; raise SystemExit(rc)'
        run = subprocess.run([sys.executable, "-c", script, "--config", str(self.config), "status"],
                             env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(json.loads(run.stdout)["service"]["state"], "STOPPED")

    def test_real_process_start_stop_and_repeated_id_no_replay(self):
        original = digest(self.root / "state/state.sqlite")
        result = self.run_action("start")
        pid = result["result"]["pid"]
        self.assertEqual(self.tool.controller.inspect()["state"], "RUNNING")
        self.assertEqual(self.run_action("start")["result"]["pid"], pid)
        self.assertFalse(self.run_action("start")["replayed"])
        self.run_action("stop", "two")
        self.assertIsNone(process_identity(pid))
        self.assertEqual(digest(self.root / "state/state.sqlite"), original)

    def test_broken_release_failure_then_external_recovery(self):
        _write_current(self.tool.profile, self.bad)
        with self.assertRaises(UnknownEffectError):
            self.tool.run("start", operation_id="broken", expected_current=self.bad["source_head"])
        self.assertEqual(self.tool.reconcile("broken")["receipt"]["state"], "UNKNOWN")
        with self.assertRaisesRegex(PreconditionError, "RECONCILE_REQUIRED"):
            self.tool.run("start", operation_id="broken", expected_current=self.bad["source_head"])
        recovered = self.tool.run("recover", operation_id="recover", expected_current=self.bad["source_head"],
                                  target=self.good["source_head"], resolves="broken")
        self.assertEqual(recovered["result"]["release_sha"], self.good["source_head"])
        self.assertEqual(self.tool.controller.inspect()["state"], "RUNNING")

    def test_active_and_unknown_work_preserved_and_blocked(self):
        for table, values in (("operations", '("work", "RUNNING")'),
                              ("resource_claims", '("unknown", 1)')):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.root / "state/state.sqlite", isolation_level=None)) as db:
                    db.execute(f"INSERT INTO {table} VALUES {values}")
                with self.assertRaisesRegex(PreconditionError, "ACTIVE_OR_UNRESOLVED"):
                    self.run_action("start")
                self.assertFalse(self.tool.receipt_path("one").exists())
                with closing(sqlite3.connect(self.root / "state/state.sqlite", isolation_level=None)) as db:
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
                    db.execute(f"DELETE FROM {table}")

    def test_tampered_release_stale_pointer_and_schema_mismatch(self):
        with self.assertRaisesRegex(PreconditionError, "STALE_CURRENT"):
            self.tool.run("start", operation_id="stale", expected_current="c" * 40)
        self.settings["verified_releases"][self.good["source_head"]]["compatible_schema_sha256"] = []
        self.save_config()
        with self.assertRaisesRegex(PreconditionError, "COMPATIBILITY"):
            Maintenance(self.config).run("start", operation_id="schema", expected_current=self.good["source_head"])
        (Path(self.good["release_path"]) / "src/bct/runtime_server.py").write_text("tamper", encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError, "HASH_MISMATCH"):
            self.tool.verify(self.good["source_head"])

    def test_incomplete_receipt_never_replayed(self):
        self.tool.receipt_path("one").parent.mkdir()
        atomic_json(self.tool.receipt_path("one"), {"state": "STARTED", "request": {}})
        with self.assertRaisesRegex(PreconditionError, "ID_REUSED"):
            self.run_action("start")
        self.assertEqual(self.tool.reconcile("one")["receipt"]["state"], "STARTED")

    def test_external_lock_blocks_another_process(self):
        with maintenance_lock(self.root):
            script = 'from bct_maintenance.locking import maintenance_lock; import sys\nwith maintenance_lock(sys.argv[1]): pass'
            run = subprocess.run([sys.executable, "-c", script, str(self.root)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("LOCK_HELD", run.stderr)

    def test_pause_flags_required_and_backup_is_consistent(self):
        (self.root / "BCT_MAINTENANCE.PAUSE").unlink()
        with self.assertRaisesRegex(PreconditionError, "ADMISSION_NOT_PAUSED"):
            self.run_action("backup")
        (self.root / "BCT_MAINTENANCE.PAUSE").touch()
        result = self.run_action("backup")
        with closing(sqlite3.connect(result["result"]["path"])) as db:
            self.assertEqual(db.execute("SELECT value FROM preserved").fetchone()[0], "keep")

    def test_unresponsive_core_exact_identity_only(self):
        module = Path(self.good["release_path"]) / "src/bct/runtime_server.py"
        module.write_text("import time; time.sleep(120)\n", encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-m", "bct.runtime_server", "--runtime-root", str(self.root)],
                                 env=dict(os.environ, PYTHONPATH=str(module.parents[1])),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            identity = process_identity(child.pid)
            self.assertIsNotNone(identity)
            atomic_json(self.root / "service.json", {**identity.as_dict(), "state": "RUNNING",
                        "release_sha": self.good["source_head"]})
            with self.assertRaisesRegex(PreconditionError, "APPROVAL_MISMATCH"):
                self.run_action("stop-unresponsive", expected_fingerprint="wrong")
            self.assertIsNone(child.poll())
            result = self.run_action("stop-unresponsive", expected_fingerprint=identity.fingerprint)
            self.assertEqual(result["result"]["state"], "STOPPED")
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)

    def test_new_id_cannot_bypass_unknown(self):
        self.tool.receipt_path("prior").parent.mkdir()
        atomic_json(self.tool.receipt_path("prior"), {"state": "UNKNOWN", "request": {}})
        with self.assertRaisesRegex(PreconditionError, "PRIOR_EFFECT_UNRESOLVED"):
            self.run_action("start", "different")

    def test_external_activate_uses_clean_main_and_shared_engine(self):
        import shutil
        from bct_maintenance.releases import _validate_source
        source = self.base / "source"
        shutil.copytree(Path(self.good["release_path"]), source)
        (source / "manifest.json").unlink()
        def git(*args):
            return subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", check=True, timeout=10).stdout.strip()
        git("init", "-b", "main")
        git("config", "user.name", "Maintenance fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("add", ".")
        git("commit", "-m", "isolated candidate")
        sha = git("rev-parse", "HEAD")
        candidate = _validate_source(self.tool.profile, sha)
        self.settings["verified_releases"][sha] = {
            "manifest_sha256": candidate["manifest_sha256"], "compatible_schema_sha256": [self.schema]}
        self.save_config()
        tool = Maintenance(self.config)
        result = tool.run("activate", operation_id="activate", expected_current=self.good["source_head"], target=sha)
        self.assertEqual(result["result"]["source_head"], sha)
        self.assertEqual(tool.controller.inspect()["release_sha"], sha)
        self.assertTrue(Path(result["backup"]["path"]).is_file())

    def test_real_store_pause_preserves_receipts_and_resume(self):
        from bct.core.store import Store
        from bct.core.models import Work, ConflictError
        root = self.base / "real-store"
        (root / "state").mkdir(parents=True)
        store = Store(root / "state/state.sqlite")
        work = Work("work", "preserve", (str(root),), ("write",), "owner")
        store.create_work(work)
        values = dict(work=work, principal_id="owner", request_digest="hash", capability="write",
                      target="target", resources=("resource",), policy_revision="test")
        created, _ = store.begin_operation(operation_id="existing", **values)
        self.assertTrue(created)
        pause = root / "BCT_MAINTENANCE.PAUSE"
        pause.touch()
        duplicate, _ = store.begin_operation(operation_id="existing", **values)
        self.assertFalse(duplicate)
        with self.assertRaisesRegex(ConflictError, "ADMISSION_PAUSED"):
            store.begin_operation(operation_id="new", **values)
        pause.unlink()
        created, _ = store.begin_operation(operation_id="new", **values)
        self.assertTrue(created)

    def test_frozen_bundle_runs_without_checkout_imports(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "scripts/build_maintenance_bundle.py"
        spec = importlib.util.spec_from_file_location("bundle_builder", path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        # Build under the check-out as enforced, then test a detached copy in temp.
        import uuid, shutil
        output = path.parents[1] / "artifacts" / ("test-bundle-" + uuid.uuid4().hex)
        try:
            builder.build(output)
            detached = self.base / "detached"
            shutil.copytree(output, detached)
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            result = subprocess.run([sys.executable, str(detached / "run.py"), "--config", str(self.config), "status"],
                                    cwd=self.base, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            (detached / "src/bct_maintenance/cli.py").write_text("tamper", encoding="utf-8")
            tampered = subprocess.run([sys.executable, str(detached / "run.py"), "--help"],
                                     env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("HASH_MISMATCH", tampered.stderr)
        finally:
            # Exact task-owned directory beneath this checkout's artifacts only.
            output.resolve().relative_to((path.parents[1] / "artifacts").resolve())
            shutil.rmtree(output)


if __name__ == "__main__":
    unittest.main()
