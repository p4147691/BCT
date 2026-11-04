from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bct.conversation_network import (
    ConversationNetworkError, arrange_conversations, configure_conversation_scope,
    ensure_observed_node_labels, retire_conversation_node_label,
    set_conversation_network_name,
    conversation_display_order_directory, conversation_scope_directory,
    patch_conversation_role_tags, project_view, record_monitor_snapshot,
    resolve_project_id, scope_directory, set_membership, upsert_conversation, upsert_project,
)
from bct.core.store import Store


MANAGER = "6ad5afa4-b1e0-83ee-8692-aec4bb51523e"
WORKER = "6ad4bb5d-6624-83ee-b045-e57fdad5120e"


class ConversationNetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite")
        upsert_project(self.store, project_id="bct.rcc", display_name="BCT RCC", now=100.0)
        upsert_conversation(self.store, conversation_key=MANAGER, display_name="오류 병목 감시 측정기", now=100.0)
        upsert_conversation(self.store, conversation_key=WORKER, display_name="대화 기록 조회 구현", now=100.0)
        set_membership(self.store, project_id="bct.rcc", conversation_key=MANAGER,
                       tags=["조정", "병목 분석"], now=100.0)
        set_membership(self.store, project_id="bct.rcc", conversation_key=WORKER,
                       tags=["구현", "테스트"], now=100.0)

    def test_scope_directory_retains_active_scope_without_open_node(self):
        directory = scope_directory(self.store)
        self.assertEqual(1, len(directory))
        scope = directory[0]
        self.assertEqual("bct.rcc", scope["scope_id"])
        self.assertEqual("ACTIVE", scope["state"])
        self.assertEqual(2, scope["member_count"])
        # Directory state comes from durable scope membership, not an open-tab snapshot.
        self.assertEqual({"구현": 1, "테스트": 1, "조정": 1, "병목 분석": 1},
                         scope["role_counts"])

    def test_network_name_set_keeps_id_members_and_node_metadata(self):
        before = configure_conversation_scope(
            self.store, conversation_key=WORKER, display_name="Worker",
            scope_name="BCT RCC", role_tags=["Worker"],
            node_memo="keep memo", assigned_task="keep task",
        )
        changed = set_conversation_network_name(
            self.store, project_id=before["scope_id"],
            expected_name="BCT RCC", new_name="Renamed Network",
        )
        self.assertEqual(before["scope_id"], changed["project_id"])
        self.assertTrue(changed["changed"])
        after = conversation_scope_directory(self.store, conversation_keys=[MANAGER, WORKER])
        self.assertEqual("Renamed Network", after[MANAGER]["scope_name"])
        self.assertEqual("Renamed Network", after[WORKER]["scope_name"])
        self.assertEqual("keep memo", after[WORKER]["node_memo"])
        self.assertEqual("keep task", after[WORKER]["assigned_task"])
        with self.assertRaises(ConversationNetworkError):
            set_conversation_network_name(
                self.store, project_id=before["scope_id"],
                expected_name="BCT RCC", new_name="stale",
            )
        upsert_project(self.store, project_id="other", display_name="Other Network")
        with self.assertRaises(ConversationNetworkError):
            set_conversation_network_name(
                self.store, project_id=before["scope_id"],
                expected_name="Renamed Network", new_name="Other Network",
            )

    def test_node_memo_task_persist_and_legacy_edit_preserves_them(self):
        saved = configure_conversation_scope(
            self.store, conversation_key=WORKER, display_name="Worker",
            scope_name="BCT RCC", role_tags=["개발"],
            node_memo="GPU tests ready", assigned_task="Verify regression",
        )
        self.assertEqual("GPU tests ready", saved["node_memo"])
        self.assertEqual("Verify regression", saved["assigned_task"])
        # Older callers do not pass the new fields and must not erase them.
        configure_conversation_scope(
            self.store, conversation_key=WORKER, display_name="Worker",
            scope_name="BCT RCC", role_tags=["개발", "검토"],
        )
        scope = conversation_scope_directory(self.store, conversation_keys=[WORKER])[WORKER]
        self.assertEqual("GPU tests ready", scope["node_memo"])
        self.assertEqual("Verify regression", scope["assigned_task"])
        with self.assertRaises(ConversationNetworkError):
            configure_conversation_scope(
                self.store, conversation_key=WORKER, display_name="Worker",
                scope_name="BCT RCC", node_memo="x" * 2001,
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def snapshot(snapshot_id: str = "monitor.1", completeness: str = "COMPLETE", nodes=None):
        return {
            "schema": "BCT_MONITOR_NODE_SNAPSHOT_V1", "source": "MONITOR",
            "snapshot_id": snapshot_id, "observed_at": "2026-10-20T03:18:00Z",
            "completeness": completeness,
            "nodes": nodes if nodes is not None else [
                {"node_label": "D1-3", "conversation_key": MANAGER,
                 "title": "오류 병목 감시 측정기", "presence": "OPEN"},
                {"node_label": "D1-4", "conversation_key": WORKER,
                 "title": "대화 기록 조회 구현", "presence": "OPEN"},
            ],
        }

    def test_literal_monitor_label_is_recorded_and_matched_by_conversation_key(self):
        receipt = record_monitor_snapshot(self.store, self.snapshot(), now=200.0)
        self.assertEqual({"snapshot_id": "monitor.1", "duplicate": False, "recorded": True,
                          "completeness": "COMPLETE", "node_count": 2}, receipt)
        view = project_view(self.store, project_id="bct.rcc")
        manager = next(item for item in view["members"] if item["display_name"] == "오류 병목 감시 측정기")
        self.assertEqual("N1", manager["node_label"])
        self.assertEqual("D1-3", manager["monitor"]["node_label"])
        self.assertEqual("MATCHED", manager["monitor_match"])
        self.assertCountEqual(["조정", "병목 분석"], manager["role_tags"])
        self.assertEqual([], view["monitor_only"])
        self.assertNotIn(MANAGER, json.dumps(view, ensure_ascii=False))
        self.assertNotIn("snapshot_id", view["monitor_snapshot"])

    def test_internal_identity_is_opt_in_for_current_presence_join(self):
        public = project_view(self.store, project_id="bct.rcc")
        internal = project_view(
            self.store, project_id="bct.rcc", include_internal_identity=True,
        )
        self.assertTrue(all("_conversation_key" not in item for item in public["members"]))
        manager = next(
            item for item in internal["members"]
            if item["display_name"] == "오류 병목 감시 측정기"
        )
        self.assertEqual(MANAGER, manager["_conversation_key"])

    def test_partial_snapshot_never_treats_missing_member_as_removed(self):
        record_monitor_snapshot(self.store, self.snapshot(nodes=[
            {"node_label": "D1-4", "conversation_key": WORKER,
             "title": "대화 기록 조회 구현", "presence": "OPEN"},
        ], completeness="PARTIAL"), now=200.0)
        view = project_view(self.store, project_id="bct.rcc")
        manager = next(item for item in view["members"] if item["display_name"] == "오류 병목 감시 측정기")
        self.assertEqual("PARTIAL_UNOBSERVED", manager["monitor_match"])

    def test_monitor_only_node_is_visible_but_not_auto_added_to_project(self):
        third = "6ad5b191-947c-83ee-8dae-b9c867af9026"
        record_monitor_snapshot(self.store, self.snapshot(nodes=[
            {"node_label": "D1-3", "conversation_key": MANAGER,
             "title": "오류 병목 감시 측정기", "presence": "OPEN"},
            {"node_label": "D1-5", "conversation_key": third,
             "title": "새 대화", "presence": "OPEN"},
        ]), now=200.0)
        view = project_view(self.store, project_id="bct.rcc")
        self.assertEqual([{"node_label": "D1-5", "title": "새 대화", "presence": "OPEN"}], view["monitor_only"])
        self.assertEqual(2, len(view["members"]))

    def test_conflicting_label_is_rejected_without_recording(self):
        with self.assertRaisesRegex(ConversationNetworkError, "CONVERSATION_NETWORK_LABEL_CONFLICT"):
            record_monitor_snapshot(self.store, self.snapshot(nodes=[
                {"node_label": "D1-3", "conversation_key": MANAGER, "title": "A", "presence": "OPEN"},
                {"node_label": "D1-3", "conversation_key": WORKER, "title": "B", "presence": "OPEN"},
            ]), now=200.0)
        self.assertIsNone(project_view(self.store, project_id="bct.rcc")["monitor_snapshot"])

    def test_unavailable_snapshot_does_not_erase_last_observation(self):
        record_monitor_snapshot(self.store, self.snapshot(), now=200.0)
        record_monitor_snapshot(self.store, self.snapshot("monitor.2", "UNAVAILABLE", []), now=201.0)
        view = project_view(self.store, project_id="bct.rcc")
        self.assertEqual("UNAVAILABLE", view["monitor_snapshot"]["completeness"])
        self.assertTrue(all(item["monitor_match"] == "MONITOR_UNAVAILABLE" for item in view["members"]))

    def test_display_name_resolves_without_requiring_a_project_id(self):
        self.assertEqual("bct.rcc", resolve_project_id(self.store, project_reference="BCT RCC"))

    def test_display_labels_are_permanent_and_do_not_depend_on_monitor_order(self):
        first = upsert_conversation(self.store, conversation_key=MANAGER,
                                    display_name="제목이 바뀌어도 같은 대화", now=200.0)
        third = upsert_conversation(self.store, conversation_key="6ad5b191-947c-83ee-8dae-b9c867af9026",
                                    display_name="새 대화", now=201.0)
        self.assertEqual("N1", first["node_label"])
        self.assertEqual("N3", third["node_label"])

    def test_display_labels_cycle_after_ninety_nine_without_changing_identity(self):
        last = None
        for number in range(3, 101):
            key = f"00000000-0000-4000-8000-{number:012d}"
            last = upsert_conversation(self.store, conversation_key=key, display_name=f"node {number}")
        self.assertEqual("N1", last["node_label"])

    def test_retired_closed_node_gets_new_non_conflicting_label_when_observed_again(self):
        retired = retire_conversation_node_label(
            self.store, conversation_key=MANAGER, expected_node_label="N1",
        )
        self.assertEqual("RETIRED", retired["status"])
        directory = conversation_scope_directory(self.store, conversation_keys=[MANAGER])
        self.assertEqual("BCT RCC", directory[MANAGER]["scope_name"])
        labels = ensure_observed_node_labels(self.store, conversations=[
            (WORKER, "still open"), (MANAGER, "restored"),
        ])
        self.assertEqual("N2", labels[WORKER])
        self.assertEqual("N3", labels[MANAGER])
        with self.assertRaisesRegex(ConversationNetworkError, "NODE_LABEL_CHANGED"):
            retire_conversation_node_label(
                self.store, conversation_key=MANAGER, expected_node_label="N1",
            )

    def test_scope_allows_only_one_manager_and_supervisor_is_unassigned(self):
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="모니터 관리",
            role_tags=["Manager", "병목 분석"],
            now=300.0,
        )
        with self.assertRaisesRegex(ConversationNetworkError, "CONVERSATION_NETWORK_MANAGER_ALREADY_ASSIGNED"):
            configure_conversation_scope(
                self.store,
                conversation_key=WORKER,
                display_name="대화 기록 조회 구현",
                scope_name="모니터 관리",
                role_tags=["Manager", "구현"],
                now=301.0,
            )
        directory = conversation_scope_directory(
            self.store, conversation_keys=[MANAGER, WORKER]
        )
        self.assertEqual("모니터 관리", configured["scope_name"])
        self.assertIn("Manager", directory[MANAGER]["role_tags"])
        self.assertNotIn("Manager", directory[WORKER]["role_tags"])

        with self.assertRaisesRegex(ConversationNetworkError, "CONVERSATION_NETWORK_SUPERVISOR_MUST_BE_UNASSIGNED"):
            configure_conversation_scope(
                self.store, conversation_key=WORKER, display_name="대화 기록 조회 구현",
                scope_name="모니터 관리", role_tags=["supervisor"], now=301.0,
            )
        configure_conversation_scope(
            self.store, conversation_key=MANAGER, display_name="오류 병목 감시 측정기",
            scope_name="", role_tags=["supervisor"], now=301.5,
        )
        with self.assertRaisesRegex(ConversationNetworkError, "CONVERSATION_NETWORK_SUPERVISOR_ALREADY_ASSIGNED"):
            configure_conversation_scope(
                self.store, conversation_key=WORKER, display_name="대화 기록 조회 구현",
                scope_name="", role_tags=["supervisor"], now=301.6,
            )

        moved = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="RCC 개선",
            role_tags=[],
            now=302.0,
        )
        self.assertEqual("RCC 개선", moved["scope_name"])
        with self.store.transaction() as db:
            active = list(db.execute(
                "SELECT project_id FROM conversation_network_memberships "
                "WHERE conversation_key=? AND activity='ACTIVE'",
                (MANAGER,),
            ))
            old = list(db.execute(
                "SELECT project_id FROM conversation_network_memberships "
                "WHERE conversation_key=? AND activity='EXCLUDED'",
                (MANAGER,),
            ))
        self.assertEqual(1, len(active))
        self.assertGreaterEqual(len(old), 1)

    def test_role_patch_uses_utf8_digest_and_updates_the_shared_store(self):
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="BCT RCC",
            role_tags=["Manager", "검색", "검증 🧪"],
            now=300.0,
        )
        first_digest = configured["role_tags_sha256"]
        self.assertRegex(first_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(
            first_digest,
            conversation_scope_directory(
                self.store, conversation_keys=[MANAGER]
            )[MANAGER]["role_tags_sha256"],
        )

        patched = patch_conversation_role_tags(
            self.store,
            project_id=configured["scope_id"],
            node_label="N1",
            add=["CI"],
            remove=["검색"],
            expected_role_tags_sha256=first_digest,
            now=301.0,
        )
        self.assertTrue(patched["changed"])
        self.assertCountEqual(["Manager", "검증 🧪", "CI"], patched["role_tags"])
        current = conversation_scope_directory(
            self.store, conversation_keys=[MANAGER]
        )[MANAGER]
        self.assertEqual(patched["role_tags_sha256"], current["role_tags_sha256"])
        self.assertCountEqual(patched["role_tags"], current["role_tags"])

    def test_stale_role_digest_rejects_without_overwriting_newer_edit(self):
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="BCT RCC",
            role_tags=["Manager"],
            now=300.0,
        )
        changed = patch_conversation_role_tags(
            self.store,
            project_id=configured["scope_id"],
            node_label="N1",
            add=["검토"],
            expected_role_tags_sha256=configured["role_tags_sha256"],
            now=301.0,
        )
        with self.assertRaisesRegex(
            ConversationNetworkError, "CONVERSATION_NETWORK_ROLE_TAGS_CONFLICT"
        ):
            patch_conversation_role_tags(
                self.store,
                project_id=configured["scope_id"],
                node_label="N1",
                add=["CI"],
                expected_role_tags_sha256=configured["role_tags_sha256"],
                now=302.0,
            )
        current = conversation_scope_directory(
            self.store, conversation_keys=[MANAGER]
        )[MANAGER]
        self.assertCountEqual(["Manager", "검토"], current["role_tags"])
        self.assertEqual(changed["role_tags_sha256"], current["role_tags_sha256"])

    def test_scope_editor_can_compare_and_swap_role_tags(self):
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="BCT RCC",
            role_tags=["Manager"],
            now=300.0,
        )
        updated = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="BCT RCC",
            role_tags=["Manager", "조정"],
            expected_role_tags_sha256=configured["role_tags_sha256"],
            now=301.0,
        )
        self.assertNotEqual(configured["role_tags_sha256"], updated["role_tags_sha256"])
        with self.assertRaisesRegex(
            ConversationNetworkError, "CONVERSATION_NETWORK_ROLE_TAGS_CONFLICT"
        ):
            configure_conversation_scope(
                self.store,
                conversation_key=MANAGER,
                display_name="오류 병목 감시 측정기",
                scope_name="BCT RCC",
                role_tags=["Manager", "이전 편집"],
                expected_role_tags_sha256=configured["role_tags_sha256"],
                now=302.0,
            )

    def test_blank_scope_means_unassigned_without_reusing_node_number(self):
        before = upsert_conversation(
            self.store, conversation_key=MANAGER, display_name="이름", now=300.0
        )["node_label"]
        cleared = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="이름",
            scope_name="",
            role_tags=["supervisor"],
            now=301.0,
        )
        self.assertEqual("", cleared["scope_id"])
        self.assertEqual(["supervisor"], cleared["role_tags"])
        self.assertEqual(["supervisor"], conversation_scope_directory(
            self.store, conversation_keys=[MANAGER]
        )[MANAGER]["role_tags"])
        after = upsert_conversation(
            self.store, conversation_key=MANAGER, display_name="다시 열린 이름", now=302.0
        )["node_label"]
        self.assertEqual(before, after)

    def test_display_order_is_durable_and_scope_move_releases_manager(self):
        arranged = arrange_conversations(
            self.store,
            conversation_keys=[WORKER, MANAGER],
            scope_id="bct.rcc",
            now=400.0,
        )
        self.assertEqual([WORKER, MANAGER], arranged["conversation_keys"])
        self.assertEqual(
            {MANAGER: 2, WORKER: 1},
            conversation_display_order_directory(
                self.store, conversation_keys=[MANAGER, WORKER]
            ),
        )
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="다른 대화망",
            role_tags=["Manager", "병목 분석"],
            now=401.0,
        )
        arrange_conversations(
            self.store,
            conversation_keys=[WORKER, MANAGER],
            scope_id="bct.rcc",
            moved_conversation_key=MANAGER,
            now=402.0,
        )
        directory = conversation_scope_directory(
            self.store, conversation_keys=[MANAGER, WORKER]
        )
        self.assertEqual("bct.rcc", directory[MANAGER]["scope_id"])
        self.assertCountEqual(["병목 분석"], directory[MANAGER]["role_tags"])
        self.assertTrue(configured["scope_id"].startswith("network."))

    def test_scope_editor_releases_manager_when_moved_or_unassigned(self):
        configured = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="Manager 이동 규칙",
            scope_name="원래 대화망",
            role_tags=["Manager", "검토"],
            now=450.0,
        )
        moved = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="Manager 이동 규칙",
            scope_name="새 대화망",
            role_tags=configured["role_tags"],
            expected_role_tags_sha256=configured["role_tags_sha256"],
            now=451.0,
        )
        self.assertEqual(["검토"], moved["role_tags"])
        reassigned = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="Manager 이동 규칙",
            scope_name="새 대화망",
            role_tags=["Manager", "검토"],
            expected_role_tags_sha256=moved["role_tags_sha256"],
            now=451.5,
        )
        unassigned = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="Manager 이동 규칙",
            scope_name="",
            role_tags=reassigned["role_tags"],
            expected_role_tags_sha256=reassigned["role_tags_sha256"],
            now=452.0,
        )
        self.assertEqual(["검토"], unassigned["role_tags"])

    def test_reorder_rejects_scope_mismatch_without_partial_write(self):
        other = configure_conversation_scope(
            self.store,
            conversation_key=MANAGER,
            display_name="오류 병목 감시 측정기",
            scope_name="다른 대화망",
            role_tags=[],
            now=500.0,
        )
        with self.assertRaisesRegex(ConversationNetworkError, "ORDER_SCOPE_MISMATCH"):
            arrange_conversations(
                self.store,
                conversation_keys=[MANAGER, WORKER],
                scope_id="bct.rcc",
                now=501.0,
            )
        self.assertEqual(other["scope_id"], conversation_scope_directory(
            self.store, conversation_keys=[MANAGER]
        )[MANAGER]["scope_id"])
