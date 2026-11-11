"""Isolated Loop/Chain adapter tests. No physical RCC or LIVE effects."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bct.core.models import Work
from bct.core.store import Store
from bct.loop_store import LoopStore, LoopStateError
from bct.loop_supervisor_handoff import LoopReviewLedger, LoopSupervisorHandoff, validate_loop_review_topology
from bct.loop_self_outbox import LoopSelfOutbox
from test_loop_self_dispatch import OWNER, snapshot

SUPERVISOR = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SHA = "a" * 40


def topology():
    m = {"instance_id":"a"*32,"node_info":{"roles":["Manager"],"network_id":"solo"}}
    s = {"instance_id":"a"*32,"node_info":{"roles":["Supervisor"],"network_id":""}}
    return {OWNER:m, SUPERVISOR:s}


class LoopReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/"db.sqlite")
        self.store.create_work(Work(work_id="work", request_summary="review", roots=(self.tmp.name,),
            actions=frozenset({"browser"}), owner_principal_id="principal"))
        from bct.chain_direction import ChainDirectionLedger
        ChainDirectionLedger(self.store).save(direction_id="dir",work_id="work",source_kind="USER",decision="NEW_TASK",direction_text="Verify exact candidate")
        self.loop = LoopStore(self.store)
        self.loop.start(work_id="work", direction_id="dir", task_id="task", owner=OWNER, plan_text="verified plan", now=100)
        self.loop.prepare_operation(work_id="work", owner=OWNER, epoch=1, operation_id="step", now=101)
        self.loop.reconcile(work_id="work", owner=OWNER, epoch=1, operation_id="step", result="APPLIED", now=102)
        self.loop.advance(work_id="work", owner=OWNER, epoch=1, next_step=1, now=103)
        self.ledger = LoopReviewLedger(self.store)
        self.routes = topology()
        self.route_patch = patch("bct.loop_supervisor_handoff.resolve_direction_target",
            side_effect=lambda **kw: self.routes[kw["conversation_key"]])
        self.route_patch.start()
        self.addCleanup(self.route_patch.stop)
        self.ledger.configure(work_id="work",owner=OWNER,supervisor=SUPERVISOR,instruction="Independent exact SHA acceptance, no deployment authorized",snapshot={})

    def request(self):
        return self.ledger.request(work_id="work",owner=OWNER,epoch=1,candidate_sha=SHA,evidence_text="CI and source evidence",now=110)

    def test_single_manager_global_supervisor_no_worker(self):
        validate_loop_review_topology({},owner=OWNER,supervisor=SUPERVISOR)
        self.assertEqual(self.ledger.get("work")["state"],"CONFIGURED")

    def test_same_uuid_and_role_scope_conflicts_rejected(self):
        with self.assertRaisesRegex(LoopStateError,"NOT_INDEPENDENT"):
            validate_loop_review_topology({},owner=OWNER,supervisor=OWNER)
        self.routes[SUPERVISOR]["node_info"]["network_id"]="solo"
        with self.assertRaisesRegex(LoopStateError,"MUST_BE_GLOBAL"):
            validate_loop_review_topology({},owner=OWNER,supervisor=SUPERVISOR)
        self.routes[SUPERVISOR]["node_info"]["network_id"]=""
        self.routes[OWNER]["node_info"]["roles"].append("worker")
        with self.assertRaisesRegex(LoopStateError,"MANAGER_ROLE_REQUIRED"):
            validate_loop_review_topology({},owner=OWNER,supervisor=SUPERVISOR)

    def test_request_is_immutable_and_does_not_complete(self):
        first=self.request()
        self.assertEqual(first,self.request())
        self.assertEqual(self.loop.get("work")["state"],"REVIEW_PENDING")
        with self.assertRaisesRegex(LoopStateError,"CONFLICT"):
            self.ledger.request(work_id="work",owner=OWNER,epoch=1,candidate_sha="b"*40,evidence_text="changed",now=111)
        with self.assertRaisesRegex(LoopStateError,"REVIEW_PENDING"):
            self.loop.claim(work_id="work",owner=OWNER,epoch=1,now=112)

    def test_boolean_completion_cannot_bypass_independent_review(self):
        with self.assertRaisesRegex(LoopStateError,"INDEPENDENT_ACCEPTANCE_REQUIRED"):
            self.loop.complete(work_id="work",owner=OWNER,epoch=1,verified=True,now=110)

    def test_pending_self_prevents_review_race(self):
        LoopSelfOutbox(self.store).queue(work_id="work",owner=OWNER,epoch=1,step=1,message="continue",now=105)
        with self.assertRaisesRegex(LoopStateError,"SELF_EFFECT_UNRESOLVED"):
            self.request()

    def make_dispatcher(self, outcome="APPLIED", crash=False):
        receipts = {}
        calls = []
        def receipt(**kw):
            if kw["operation_id"] not in receipts:
                raise KeyError(kw["operation_id"])
            return receipts[kw["operation_id"]]
        self.store.get_operation_for = receipt
        def run(**kw):
            calls.append(kw)
            if crash:
                raise RuntimeError("crash after reservation")
            result=SimpleNamespace(state=SimpleNamespace(value="FINISHED"),outcome=SimpleNamespace(value=outcome))
            receipts[kw["operation_id"]]=result
            return result
        adapter=LoopSupervisorHandoff(self.store,SimpleNamespace(run=run),SimpleNamespace())
        adapter.service.prearm=lambda **kw: {"state":"WATCHING"}
        self.send_patch=patch("bct.loop_supervisor_handoff.NodeRecoveryLedger.assert_send_allowed")
        self.send_patch.start();self.addCleanup(self.send_patch.stop)
        return adapter,calls,receipts

    def test_exact_handoff_sent_once_and_original_receipt_reused(self):
        row=self.request()
        adapter,calls,_=self.make_dispatcher()
        result=adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        self.assertEqual(result[0]["state"],"DELIVERED")
        adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["operation_id"],row["operation_id"])
        self.assertEqual(calls[0]["arguments"]["conversation_key"],SUPERVISOR)
        self.assertIn("no deployment authorized",calls[0]["arguments"]["text"])

    def test_unknown_or_crash_is_never_replayed(self):
        self.request()
        adapter,calls,_=self.make_dispatcher(crash=True)
        for _ in range(3):
            adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        self.assertEqual(len(calls),1)
        self.assertEqual(self.ledger.get("work")["state"],"DISPATCHING")
        with self.assertRaisesRegex(LoopStateError,"HOLD_REQUIRED"):
            self.ledger.resume(work_id="work",owner=OWNER,epoch=1,response_sha256="a"*64,snapshot={})

    def test_not_applied_is_visible_not_auto_retried(self):
        self.request()
        adapter,calls,_=self.make_dispatcher(outcome="NOT_APPLIED")
        adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        self.assertEqual(len(calls),1)
        self.assertEqual(self.ledger.get("work")["state"],"NOT_APPLIED")

    def test_changed_role_stops_before_send(self):
        self.request()
        adapter,calls,_=self.make_dispatcher()
        self.routes[SUPERVISOR]["node_info"]["roles"]=["worker"]
        adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        self.assertEqual(calls,[])
        self.assertEqual(self.ledger.get("work")["state"],"PENDING")

    def returned_context(self, payload):
        return {"task_id":self.ledger.get("work")["task_id"],"generation":1,
            "watch_state":"RETURNED_TO_MANAGER","worker_conversation_key":SUPERVISOR,
            "response_turn_id":"exact-review-response", "binding":{"work_id":"work","manager_conversation_key":OWNER},
            "decision":{"route":"MANAGER","payload":payload,"response_turn_key":"reply","response_sha256":"a"*64}}

    def delivered(self):
        self.request()
        adapter,calls,receipts=self.make_dispatcher()
        adapter.run_once(snapshot=snapshot(owner=SUPERVISOR))
        return adapter,receipts

    def test_acceptance_requires_exact_sha_and_return_receipt(self):
        adapter,receipts=self.delivered()
        ctx=self.returned_context("LOOP ACCEPTANCE: PASS\nLOOP CANDIDATE SHA: "+SHA)
        key=hashlib.sha256(f"{ctx['task_id']}|1|exact-review-response".encode()).hexdigest()[:24]
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        ChainExecutionPlanLedger(self.store).save(plan_id="review-plan",work_id="work",direction_id="dir",task_id=ctx["task_id"],generation=1,plan_text="Verify candidate")
        ChainExecutionPlanLedger(self.store).record_execute_plan_check(work_id="work", direction_id="dir",
            task_id=ctx["task_id"],generation=1,response_sha256="a"*64,
            assessment={"plan_id":"review-plan","reported_revision":0,"completed_steps":1,"total_steps":1,"issues":[]})
        with patch("bct.loop_supervisor_handoff.DurableWatchLedger.read_execution_context",return_value=ctx):
            adapter.run_once(snapshot={})
            self.assertEqual(self.loop.get("work")["state"],"REVIEW_PENDING")
            receipts["delayed-manager-"+key]=SimpleNamespace(state=SimpleNamespace(value="FINISHED"),outcome=SimpleNamespace(value="APPLIED"))
            adapter.run_once(snapshot={})
        self.assertEqual(self.loop.get("work")["state"],"COMPLETED")
        self.assertEqual(self.ledger.get("work")["state"],"ACCEPTED")
        from bct.loop_result import LoopResultLedger
        report = LoopResultLedger(self.store).get("work")
        self.assertEqual(report["state"], "READY_FOR_REQUESTER")
        self.assertEqual(report["result"]["candidate_sha"], SHA)
        self.assertEqual(report["result"]["return_operation_id"], "delayed-manager-"+key)
        self.assertEqual(report["result"]["user_notification"], "UNVERIFIED")
        # Upgrade from an older accepted review may reconstruct the same result
        # only after checking its original watch and return receipt.
        with self.store.transaction() as db:
            db.execute("DELETE FROM loop_result_reports WHERE work_id='work'")
        with patch("bct.loop_supervisor_handoff.DurableWatchLedger.read_execution_context",return_value=ctx):
            restored = LoopResultLedger(self.store).recover_acceptance("work")
        self.assertEqual(restored["result"], report["result"])
        self.assertEqual(restored["operation_id"], report["operation_id"])

    def test_generic_code_pass_is_not_acceptance(self):
        adapter,receipts=self.delivered()
        ctx=self.returned_context("CODE_REVIEW_PASS")
        key=hashlib.sha256(f"{ctx['task_id']}|1|exact-review-response".encode()).hexdigest()[:24]
        receipts["delayed-manager-"+key]=SimpleNamespace(state=SimpleNamespace(value="FINISHED"),outcome=SimpleNamespace(value="APPLIED"))
        with patch("bct.loop_supervisor_handoff.DurableWatchLedger.read_execution_context",return_value=ctx):
            adapter.run_once(snapshot={})
        self.assertEqual(self.loop.get("work")["state"],"REVIEW_PENDING")
        self.assertEqual(self.ledger.get("work")["state"],"REVIEW_HOLD")
        from bct.loop_result import LoopResultLedger
        self.assertIsNone(LoopResultLedger(self.store).get("work"))

class ComposedReviewTransportTests(unittest.TestCase):
    def test_real_ledgers_chain_watch_and_return_with_simulated_rcc(self):
        self.run_transport()

    def test_hold_resume_new_sha_and_second_independent_review(self):
        self.run_transport(first_hold=True)

    def test_acceptance_result_sent_once_to_explicit_existing_requester(self):
        self.run_transport(report_to_requester=True)

    def run_transport(self, first_hold=False, report_to_requester=False):
        import test_delayed_send_rcc_flow as fixtures
        from bct.service import BCT
        from bct.features.rcc import BrowserFeature
        from bct.core.models import Principal
        from bct.chain_direction import ChainDirectionLedger
        from bct.chain_execution_plan import ChainExecutionPlanLedger
        with tempfile.TemporaryDirectory() as tmp, patch.object(fixtures,"INSTANCE","a"*32):
            root=Path(tmp)
            policy=root/"bct.toml"
            policy.write_text('[policy]\nnormal_actions=["browser"]\napproval_actions=[]\n')
            bct=BCT(state_path=root/"state.sqlite",policy_path=policy)
            rcc=fixtures.SimulatedRcc()
            browser=BrowserFeature(rcc,store=bct.store)
            bct.operations._features["browser"]=browser
            owner,supervisor=fixtures.MANAGER,fixtures.SUPERVISOR
            bct.create_work(work_id="review-work",request_summary="isolated adapter",roots=[str(root)],
                actions=["browser"],principal=Principal("tester","test",frozenset({"browser"})))
            loop=LoopStore(bct.store)
            ChainDirectionLedger(bct.store).save(direction_id="review-direction",work_id="review-work",
                source_kind="USER",decision="NEW_TASK",direction_text="Independent source-only acceptance")
            loop.start(work_id="review-work",direction_id="review-direction",task_id="loop-task",owner=owner,plan_text="Verify candidate")
            loop.prepare_operation(work_id="review-work",owner=owner,epoch=1,operation_id="verified-step")
            loop.reconcile(work_id="review-work",owner=owner,epoch=1,operation_id="verified-step",result="APPLIED")
            loop.advance(work_id="review-work",owner=owner,epoch=1,next_step=1)
            view=snapshot(owner=owner)
            node=view["current_nodes"]["items"][0]
            node.update(tab_id=12,window_id=11,roles=["Manager"],network_id="solo")
            tab=view["rcc"]["instances"][0]["tabs"][0]
            tab.update(tab_id=12,window_id=11,conversation_scope={"scope_id":"solo","role_tags":["Manager"]})
            view["rcc"]["instances"][0]["session_id"]=fixtures.SESSION
            view["current_nodes"]["items"].append({**node,"conversation_uuid":supervisor,"tab_id":13,"roles":["Supervisor"],"network_id":""})
            view["rcc"]["instances"][0]["tabs"].append({**tab,"conversation_key":supervisor,"tab_id":13,"conversation_scope":{"role_tags":["Supervisor"]}})
            if report_to_requester:
                requester = fixtures.WORKER  # Existing origin conversation; never provisioned.
                view["current_nodes"]["items"].append({**node,"conversation_uuid":requester,"tab_id":10,"roles":[],"network_id":""})
                view["rcc"]["instances"][0]["tabs"].append({**tab,"conversation_key":requester,"tab_id":10,"conversation_scope":{}})
                from bct.loop_result import LoopResultLedger
                LoopResultLedger(bct.store).configure(work_id="review-work",owner=owner,
                    requester_ref="explicit-origin:42",conversation_key=requester,snapshot={"monitor":view})
            adapter=LoopSupervisorHandoff(bct.store,bct.operations,browser)
            adapter.ledger.configure(work_id="review-work",owner=owner,supervisor=supervisor,
                instruction="Source-only review; no deployment",snapshot={"monitor":view})
            adapter.ledger.request(work_id="review-work",owner=owner,epoch=1,candidate_sha=SHA,evidence_text="exact source")
            rcc.reply(supervisor,"A prior unrelated completed reply")
            outcomes=adapter.run_once(snapshot={"monitor":view})
            self.assertEqual(outcomes[0]["state"],"DELIVERED",outcomes)
            review=adapter.ledger.get("review-work")
            ChainExecutionPlanLedger(bct.store).save(plan_id="review-plan",work_id="review-work",
                direction_id="review-direction",task_id=review["task_id"],generation=1,plan_text="Independently verify source")
            verdict = "HOLD" if first_hold else "PASS"
            rcc.reply(supervisor,"PLAN REVISION: 0\nPROGRESS: 1/1 — source checked\nNEXT TASK — MANAGER\nLOOP ACCEPTANCE: "+verdict+"\nLOOP CANDIDATE SHA: "+SHA)
            outcome=adapter.service.poll_once()
            self.assertEqual(outcome["events"][0]["status"],"RETURNED_TO_MANAGER",outcome)
            result=adapter.run_once(snapshot={"monitor":view})
            if first_hold:
                self.assertEqual(result[0]["state"],"REVIEW_HOLD",result)
                prior=adapter.ledger.get("review-work")
                import json
                proof=json.loads(prior["response_json"])["decision"]["response_sha256"]
                with self.assertRaisesRegex(LoopStateError,"RETURN_PROOF_REQUIRED"):
                    adapter.ledger.resume(work_id="review-work",owner=owner,epoch=1,response_sha256="0"*64,snapshot={"monitor":view})
                resumed=adapter.ledger.resume(work_id="review-work",owner=owner,epoch=1,response_sha256=proof,snapshot={"monitor":view})
                self.assertNotEqual(prior["task_id"],resumed["task_id"])
                self.assertNotEqual(prior["operation_id"],resumed["operation_id"])
                self.assertEqual(loop.get("review-work")["epoch"],2)
                with self.assertRaisesRegex(LoopStateError,"HOLD_REQUIRED"):
                    adapter.ledger.resume(work_id="review-work",owner=owner,epoch=1,response_sha256=proof,snapshot={"monitor":view})
                loop.prepare_operation(work_id="review-work",owner=owner,epoch=2,operation_id="correction-step")
                loop.reconcile(work_id="review-work",owner=owner,epoch=2,operation_id="correction-step",result="APPLIED")
                loop.advance(work_id="review-work",owner=owner,epoch=2,next_step=2)
                adapter.ledger.request(work_id="review-work",owner=owner,epoch=2,candidate_sha="b"*40,evidence_text="corrected source")
                self.assertEqual(adapter.run_once(snapshot={"monitor":view})[0]["state"],"DELIVERED")
                ChainExecutionPlanLedger(bct.store).save(plan_id="review-plan-2",work_id="review-work",
                    direction_id="review-direction",task_id=resumed["task_id"],generation=1,plan_text="Review corrected candidate")
                rcc.reply(supervisor,"PLAN REVISION: 0\nPROGRESS: 1/1 — correction independently verified\nNEXT TASK — MANAGER\nLOOP ACCEPTANCE: PASS\nLOOP CANDIDATE SHA: "+"b"*40)
                self.assertEqual(adapter.service.poll_once()["events"][0]["status"],"RETURNED_TO_MANAGER")
                result=adapter.run_once(snapshot={"monitor":view})
                history=adapter.ledger.history("review-work")
                self.assertEqual(len(history),1)
                self.assertEqual(json.loads(history[0]["payload_json"])["review"],prior)
            self.assertEqual(result[0]["state"],"ACCEPTED",result)
            self.assertEqual(loop.get("review-work")["state"],"COMPLETED")
            from bct.loop_result import LoopResultLedger
            report = LoopResultLedger(bct.store).get("review-work")
            self.assertEqual(report["state"], "PENDING" if report_to_requester else "READY_FOR_REQUESTER")
            self.assertEqual(report["result"]["candidate_sha"], "b"*40 if first_hold else SHA)
            self.assertEqual([target for target,_,_ in rcc.sent],[supervisor,owner] * (2 if first_hold else 1))
            adapter.run_once(snapshot={"monitor":view})
            self.assertEqual(len(rcc.sent),4 if first_hold else 2)
            if report_to_requester:
                from bct.loop_result import LoopResultDispatcher
                dispatcher = LoopResultDispatcher(bct.store,bct.operations)
                sent = dispatcher.run_once(snapshot={"monitor":view})
                self.assertEqual(sent[0]["state"], "DELIVERED_TO_CONVERSATION", sent)
                dispatcher.run_once(snapshot={"monitor":view})
                self.assertEqual([target for target,_,_ in rcc.sent], [supervisor,owner,requester])
                self.assertEqual(rcc.create_count, 0)
                self.assertEqual(dispatcher.ledger.get("review-work")["result"]["user_notification"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
