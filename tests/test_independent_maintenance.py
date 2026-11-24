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

    def test_registration_plan_checks_review_and_preserves_installed_config(self):
        from unittest.mock import patch
        from bct_maintenance.registration import registration_plan

        before = self.config.read_bytes()
        candidate = "c" * 40
        candidate_hash = "d" * 64
        review = {
            "config_sha256": digest(self.config),
            "candidate": candidate,
            "candidate_manifest_sha256": candidate_hash,
            "rollback": self.good["source_head"],
            "rollback_manifest_sha256": self.good["manifest_sha256"],
            "schema_sha256": self.schema,
            "admission_releases": [candidate],
        }
        with patch("bct_maintenance.registration._target_profile", return_value=self.tool.profile), patch(
            "bct_maintenance.registration._validate_source",
            return_value={"manifest_sha256": candidate_hash},
        ):
            plan = registration_plan(self.tool, review, self.base)
            self.assertEqual(plan["effect"], "NONE_READ_ONLY")
            settings = plan["settings"]
            self.assertTrue(set(self.settings["verified_releases"]) <= set(settings["verified_releases"]))
            self.assertEqual(settings["verified_releases"][candidate], {
                "manifest_sha256": candidate_hash,
                "compatible_schema_sha256": [self.schema],
            })
            self.assertIn(candidate, settings["admission_releases"])
            for override, error in (
                ({"config_sha256": "0" * 64}, "MAINTENANCE_CONFIG_CHANGED"),
                ({"candidate_manifest_sha256": "0" * 64}, "MAINTENANCE_CANDIDATE_NOT_VERIFIED"),
                ({"rollback_manifest_sha256": "0" * 64}, "MAINTENANCE_RELEASE_PIN_MISMATCH"),
                ({"schema_sha256": "0" * 64}, "MAINTENANCE_DB_COMPATIBILITY_NOT_VERIFIED"),
                ({"admission_releases": ["e" * 40]}, "MAINTENANCE_ADMISSION_RELEASE_NOT_VERIFIED"),
            ):
                with self.subTest(error=error), self.assertRaisesRegex(PreconditionError, error):
                    registration_plan(self.tool, {**review, **override}, self.base)
        self.assertEqual(self.config.read_bytes(), before)

    def test_python_environment_pin_is_exact_and_fail_closed(self):
        from bct_maintenance.service_runtime import python_environment_digest

        release = self.good
        old = self.bad
        controller = self.tool.controller
        self.assertEqual(controller.python_binding(old), {"executable": sys.executable})
        environment = self.root / "python-environments" / "sdk-v2"
        environment.mkdir(parents=True)
        program = environment / "python.exe"
        program.write_bytes(b"fixture native interpreter")
        (environment / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
        dependency = environment / "dependency.py"
        dependency.write_bytes(b"approved dependency")
        digest = python_environment_digest(environment.resolve())
        pin_path = self.root / "config" / "core-python-pins.json"
        pin = {"environment": "sdk-v2", "executable": "python.exe",
               "environment_sha256": digest, "manifest_sha256": release["manifest_sha256"]}
        atomic_json(pin_path, {"schema": 1, "releases": {release["source_head"]: pin}})
        self.assertEqual(controller.python_binding(old), {"executable": sys.executable})
        self.assertEqual(self.tool.verify(release["source_head"])["python_binding"], {
            "executable": str(program.resolve()), "environment_sha256": digest,
        })
        for override, expected in (
            ({"manifest_sha256": "0" * 64}, "CORE_PYTHON_RELEASE_PIN_MISMATCH"),
            ({"executable": "../python.exe"}, "CORE_PYTHON_ENVIRONMENT_PATH_INVALID"),
            ({"executable": str(program.resolve())}, "CORE_PYTHON_ENVIRONMENT_PATH_INVALID"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(PreconditionError, expected):
                atomic_json(pin_path, {"schema": 1, "releases": {release["source_head"]: {**pin, **override}}})
                controller.start(release)
        atomic_json(pin_path, {"schema": 1, "releases": {release["source_head"]: pin}})
        dependency.write_bytes(b"tampered")
        with self.assertRaisesRegex(PreconditionError, "CORE_PYTHON_ENVIRONMENT_HASH_MISMATCH"):
            controller.start(release)
        self.assertFalse(controller.service_path.exists())

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

    def test_bootstrap_stops_legacy_core_with_exact_identity_and_backup(self):
        from unittest.mock import patch
        legacy = SERVER.replace("'maintenance_contract':1", "'maintenance_contract':0")
        with patch(__name__ + ".SERVER", legacy):
            self.good = self.make_release("c" * 40)
        self.settings["verified_releases"][self.good["source_head"]] = {"manifest_sha256": self.good["manifest_sha256"], "compatible_schema_sha256": [self.schema]}
        self.settings["admission_releases"].append(self.good["source_head"])
        self.settings["allowed_actions"].append("bootstrap-stop")
        self.save_config()
        self.tool = Maintenance(self.config)
        _write_current(self.tool.profile, self.good)
        self.run_action("start", "legacy-start")
        identity = self.tool.controller.inspect()["fingerprint"]
        with self.assertRaisesRegex(PreconditionError, "NOT_ACKNOWLEDGED"):
            self.run_action("stop", "normal-stop")
        with self.assertRaisesRegex(PreconditionError, "BOOTSTRAP_IDENTITY"):
            self.run_action("bootstrap-stop", "bad-bootstrap", expected_fingerprint=identity)
        self.settings["bootstrap"] = {"release_sha": self.good["source_head"], "fingerprint": identity}
        self.save_config()
        self.tool = Maintenance(self.config)
        result = self.run_action("bootstrap-stop", "bootstrap", expected_fingerprint=identity)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertTrue(Path(result["backup"]["path"]).is_file())
        self.assertIn(self.tool.controller.inspect()["state"], {"STOPPED", "STOPPED_STALE_RECEIPT"})

    def test_pause_resume_preserves_foreign_flags_and_requires_healthy_release(self):
        self.settings["allowed_actions"] += ["pause", "resume"]
        self.save_config()
        self.tool = Maintenance(self.config)
        with self.assertRaisesRegex(PreconditionError, "OWNED_ELSEWHERE"):
            self.run_action("pause", "foreign")
        for name in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE"):
            (self.root / name).unlink()
        self.run_action("pause", "pause")
        with self.assertRaisesRegex(PreconditionError, "RESUME_HEALTH"):
            self.run_action("resume", "premature-resume")
        self.run_action("start", "start-paused")
        self.run_action("resume", "resume")
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())

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
        linked = self.base / "linked-source"
        git("worktree", "add", "--detach", str(linked), sha)
        (source / "ongoing-user-work.txt").write_text("preserve", encoding="utf-8")
        candidate = _validate_source(self.tool.profile, sha, linked)
        from bct_maintenance.registration import registration_plan

        plan = registration_plan(self.tool, {
            "config_sha256": digest(self.config), "candidate": sha,
            "rollback": self.good["source_head"], "schema_sha256": self.schema,
            "candidate_manifest_sha256": candidate["manifest_sha256"],
            "rollback_manifest_sha256": self.good["manifest_sha256"],
        }, linked)
        with self.assertRaisesRegex(PreconditionError, "MAINTENANCE_CANDIDATE_NOT_VERIFIED"):
            self.tool.verify_source(sha, linked)
        atomic_json(self.config, plan["settings"])
        tool = Maintenance(self.config)
        self.assertEqual(tool.verify(self.good["source_head"])["effect"], "NONE_READ_ONLY")
        checked = tool.verify_source(sha, linked)
        self.assertEqual(checked["effect"], "NONE_READ_ONLY")
        self.assertEqual(checked["manifest_sha256"], candidate["manifest_sha256"])
        self.assertFalse((self.root / "releases" / sha).exists())
        result = tool.run("activate", operation_id="activate", expected_current=self.good["source_head"], target=sha, source_worktree=str(linked))
        self.assertEqual((source / "ongoing-user-work.txt").read_text(encoding="utf-8"), "preserve")
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

    def test_operator_restart_uses_external_receipts_and_resumes(self):
        from bct_maintenance.operator import main
        self.settings["allowed_actions"] += ["pause", "resume"]
        self.save_config()
        for name in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE"):
            (self.root / name).unlink()
        self.assertEqual(main(["--config", str(self.config), "restart"]), 0)
        self.assertEqual(self.tool.controller.inspect()["state"], "RUNNING")
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())

    def prepare_operator_start(self, running=True, paused=False):
        if running:
            self.run_action("start", "seed-start")
        self.settings["allowed_actions"] += ["pause", "resume"]
        self.save_config()
        self.tool = Maintenance(self.config)
        for name in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE"):
            flag = self.root / name
            if paused:
                flag.write_text("independent-maintenance\n", encoding="utf-8")
            else:
                flag.unlink()

    def test_operator_start_running_is_read_only_even_with_active_work(self):
        from bct_maintenance.operator import main
        self.prepare_operator_start()
        with closing(sqlite3.connect(self.root / "state/state.sqlite")) as db:
            db.execute("INSERT INTO operations VALUES('active','RUNNING')")
            db.execute("INSERT INTO resource_claims VALUES('unknown',1)")
            db.commit()
        protected = [self.root / "state/state.sqlite", self.root / "service.json", self.root / "current.json"]
        before = {p: p.read_bytes() for p in protected}
        receipts = {p: p.read_bytes() for p in (self.root / "maintenance").glob("*")}
        pid = self.tool.controller.inspect()["pid"]
        for _ in range(2):
            self.assertEqual(main(["--config", str(self.config), "start"]), 0)
        self.assertEqual(self.tool.controller.inspect()["pid"], pid)
        self.assertEqual({p: p.read_bytes() for p in protected}, before)
        self.assertEqual({p: p.read_bytes() for p in (self.root / "maintenance").glob("*")}, receipts)
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())
        self.assertFalse((self.root / "BCT_CORE_SUPERVISOR.STOP").exists())

    def test_operator_start_running_paused_only_resumes(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start(paused=True)
        pid = self.tool.controller.inspect()["pid"]
        result = start(self.tool, "paused-running")
        self.assertEqual(result["effect"], "RESUMED")
        self.assertEqual(self.tool.controller.inspect()["pid"], pid)
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())
        self.assertFalse(self.tool.receipt_path("paused-running-start").exists())
        self.assertEqual(json.loads(self.tool.receipt_path("paused-running-resume").read_text())["state"], "COMPLETED")

    def test_operator_start_stopped_still_starts_and_resumes(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start(running=False)
        result = start(self.tool, "stopped")
        self.assertEqual(result["effect"], "STARTED_AND_RESUMED")
        self.assertEqual(self.tool.controller.inspect()["state"], "RUNNING")
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())
        self.assertTrue(self.tool.receipt_path("stopped-start").exists())

    def test_operator_start_stopped_paused_starts_and_resumes(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start(running=False, paused=True)
        result = start(self.tool, "stopped-paused")
        self.assertEqual(result["effect"], "STARTED_AND_RESUMED")
        self.assertEqual(self.tool.controller.inspect()["state"], "RUNNING")
        for name in ("BCT_CORE_SUPERVISOR.STOP", "BCT_MAINTENANCE.PAUSE"):
            self.assertFalse((self.root / name).exists())
        self.assertFalse(self.tool.receipt_path("stopped-paused-pause").exists())
        for action in ("start", "resume"):
            receipt = json.loads(self.tool.receipt_path("stopped-paused-" + action).read_text())
            self.assertEqual(receipt["state"], "COMPLETED")
        with closing(sqlite3.connect(self.root / "state/state.sqlite")) as db:
            self.assertEqual(db.execute("SELECT value FROM preserved").fetchone()[0], "keep")

    def test_operator_start_preserves_partial_and_foreign_flags(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start()
        pause = self.root / "BCT_MAINTENANCE.PAUSE"
        stop = self.root / "BCT_CORE_SUPERVISOR.STOP"
        pause.write_text("independent-maintenance\n", encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError, "FLAGS_INCONSISTENT"):
            start(self.tool, "partial")
        self.assertFalse(stop.exists())
        stop.write_text("foreign owner", encoding="utf-8")
        with self.assertRaisesRegex(PreconditionError, "OWNED_ELSEWHERE"):
            start(self.tool, "foreign")
        self.assertEqual(stop.read_text(), "foreign owner")
        self.assertTrue(pause.exists())

    def test_operator_start_rejects_running_other_release_without_pausing(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start()
        _write_current(self.tool.profile, self.bad)
        with self.assertRaisesRegex(PreconditionError, "RUNNING_RELEASE_MISMATCH"):
            start(self.tool, "mismatch")
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())

    def test_operator_start_preserves_unknown_journal_and_disabled_authorization(self):
        from bct_maintenance.operator import start
        self.prepare_operator_start()
        old = self.tool.receipt_path("unknown")
        atomic_json(old, {"state": "UNKNOWN", "request": {}})
        original = old.read_bytes()
        with self.assertRaisesRegex(PreconditionError, "PRIOR_EFFECT_UNRESOLVED"):
            start(self.tool, "blocked")
        self.assertEqual(old.read_bytes(), original)
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())
        self.settings["enabled"] = False
        self.save_config()
        with self.assertRaisesRegex(PreconditionError, "NOT_AUTHORIZED"):
            start(Maintenance(self.config), "disabled")

    def test_operator_start_unverified_health_does_not_create_pause(self):
        from unittest.mock import patch
        from bct_maintenance.operator import start
        self.prepare_operator_start()
        with patch.object(self.tool.controller, "inspect", side_effect=PreconditionError("SERVICE_PROCESS_RUNNING_WITHOUT_HEALTH")):
            with self.assertRaisesRegex(PreconditionError, "WITHOUT_HEALTH"):
                start(self.tool, "no-health")
        self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())

    def test_frozen_bundle_runs_without_checkout_imports(self):
        self.prepare_operator_start()
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
            noop = subprocess.run([sys.executable, "-I", str(detached / "run.py"), "--operator", "--config", str(self.config), "start"],
                                  cwd=self.base, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(noop.returncode, 0, noop.stderr)
            self.assertEqual(json.loads(noop.stdout)["effect"], "NONE_READ_ONLY")
            self.assertFalse((self.root / "BCT_MAINTENANCE.PAUSE").exists())
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
