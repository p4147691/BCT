import unittest
from bct.memoryguard_node_process import project_node_processes

NOW = 1000.
KEY = "12345678-1234-1234-1234-123456789abc"
def status(tabs=None, generated=995):
    return {"core": {"ready": True, "generation": 243},
            "monitor": {"generated_at": generated, "rcc": {"instances": [{
                "state": "OPEN", "instance_id": "instance-1", "session_id": "session-1",
                "tabs": tabs or [{"tab_id": 42, "window_id": 7,
                                  "conversation_key": KEY, "node_label": "N69",
                                  "title": "MemoryGuard window", "presence": "OPEN"}],
            }]}}}
def chrome(**overrides):
    row = {"source": "RCC_CHROME_PROCESSES_READONLY",
           "instance_id": "instance-1", "session_id": "session-1",
           "tab_id": 42, "window_id": 7, "conversation_uuid": KEY,
           "renderer_process_id": 901, "tab_renderer_process_id": 901,
           "os_process_id": 501, "process_type": "renderer",
           "exclusive_task_list_proven": True, "task_tab_ids": [42],
           "observed_at_unix": 995}
    row.update(overrides)
    return row
def os_processes(**overrides):
    value = {"pid": 501, "name": "chrome.exe", "create_time": 123.5,
             "observed_at_unix": 995}
    value.update(overrides)
    return {501: value}
class MemoryguardNodeProofTests(unittest.TestCase):
    def run_projection(self,**kwargs):
        return project_node_processes(status(),renderer_observations=[chrome()],
                                      os_process_observations=os_processes(),now_unix=NOW,**kwargs)
    def test_positive_contract_matches_memoryguard_consumer(self):
        from pathlib import Path
        import sys
        # Keep consumer import optional; no application runtime or GUI modification.
        out = self.run_projection()
        self.assertEqual(out["status"],"VERIFIED")
        b=out["verified_bindings"][0]
        self.assertEqual(("N69",501,123.5, "MemoryGuard window"),
                         (b["node"],b["pid"],b["create_time"],b["tab_title"]))
        self.assertFalse(b["authorize_unload"])
        self.assertEqual("TARGET_PROCESS_EXCLUSIVE",b["window_attribution"])
    def test_no_renderer_source_remains_unverified(self):
        out=project_node_processes(status(),now_unix=NOW)
        self.assertEqual([],out["verified_bindings"])
        self.assertEqual("미확인",out["unverified_targets"][0]["status"])
    def test_stale_bct_rejected(self):
        self.assertEqual("BCT_STATUS_STALE",project_node_processes(status(generated=879),now_unix=NOW)["reason"])
    def test_stale_or_future_browser_proof_rejected(self):
        for value in (879,1001):
            with self.subTest(value=value):
                out=project_node_processes(status(),renderer_observations=[chrome(observed_at_unix=value)],
                    os_process_observations=os_processes(),now_unix=NOW)
                self.assertEqual([],out["verified_bindings"])
    def test_stale_or_reused_windows_pid_rejected(self):
        for v in ({"observed_at_unix":879},{"pid":999},{"name":"python.exe"}):
            out=project_node_processes(status(),renderer_observations=[chrome()],
                os_process_observations=os_processes(**v),now_unix=NOW)
            self.assertFalse(out["verified_bindings"])
    def test_shared_renderer_is_not_per_tab_memory(self):
        for tasks in ([42,43],[],[43]):
            out=project_node_processes(status(),renderer_observations=[
                chrome(task_tab_ids=tasks)],os_process_observations=os_processes(),now_unix=NOW)
            self.assertFalse(out["verified_bindings"])
    def test_false_attestation_and_pid_identity_rejected(self):
        for value in ({"source":"USER_INPUT"},{"process_type":"browser"},
                      {"exclusive_task_list_proven":False},
                      {"tab_renderer_process_id":902}, {"window_id":8}):
            out=project_node_processes(status(),renderer_observations=[chrome(**value)],
                os_process_observations=os_processes(),now_unix=NOW)
            self.assertEqual([],out["verified_bindings"])
    def test_conflicting_binding_is_rejected(self):
        out=project_node_processes(status(),renderer_observations=[chrome(),chrome()],
            os_process_observations=os_processes(),now_unix=NOW)
        self.assertEqual([],out["verified_bindings"])
    def test_uuid_and_node_validation(self):
        bad=status()[ "monitor"]["rcc"]["instances"][0]["tabs"][0].copy()
        bad["node_label"]="N0"
        out=project_node_processes(status([bad]),now_unix=NOW)
        self.assertEqual([],out["unverified_targets"])
    def test_no_unload_authority(self):
        self.assertFalse(self.run_projection()["authorize_unload"])
if __name__=="__main__": unittest.main()
