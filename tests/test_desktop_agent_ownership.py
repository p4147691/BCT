from __future__ import annotations

import unittest

from bct.desktop_agent_ownership import AgentDecision, AgentObservation, decide_agent_recovery


EXPECTED = r"D:\BCT\runtime\releases\candidate\VtlDesktopSessionAgent.exe"


class DesktopAgentOwnershipTests(unittest.TestCase):
    def decide(self, kind, *, pid=19644, old_session=1, current=2, actual_session=None,
               executable=EXPECTED):
        return decide_agent_recovery(
            endpoint_pid=19644, endpoint_session=old_session,
            current_session=current,
            observation=AgentObservation(
                kind=kind, pid=pid, session_id=actual_session, executable=executable
            ),
            expected_executable=EXPECTED,
        )

    def test_previous_session_agent_absent_can_be_considered_for_recovery(self):
        result = self.decide("ABSENT")
        self.assertEqual((AgentDecision.ABSENT, "ENDPOINT_PID_CONFIRMED_GONE"),
                         (result.state, result.reason))

    def test_live_previous_session_agent_is_not_stopped_or_replaced(self):
        result = self.decide("PRESENT", actual_session=1)
        self.assertEqual(AgentDecision.HOLD, result.state)
        self.assertEqual("LIVE_FOREIGN_SESSION_AGENT", result.reason)

    def test_inspection_access_denied_is_not_absence(self):
        self.assertEqual(AgentDecision.HOLD, self.decide("UNKNOWN").state)

    def test_pid_reuse_or_wrong_pid_is_not_absence(self):
        self.assertEqual(AgentDecision.HOLD, self.decide("ABSENT", pid=777).state)

    def test_live_same_session_exact_path_ready(self):
        result = self.decide("PRESENT", old_session=2, actual_session=2)
        self.assertEqual(AgentDecision.READY, result.state)

    def test_different_executable_is_not_trusted(self):
        result = self.decide("PRESENT", old_session=2, actual_session=2,
                             executable=r"C:\Temp\VtlDesktopSessionAgent.exe")
        self.assertEqual(AgentDecision.HOLD, result.state)

    def test_process_endpoint_session_conflict_fails_closed(self):
        self.assertEqual(AgentDecision.HOLD,
                         self.decide("PRESENT", old_session=2, actual_session=1).state)

    def test_missing_os_session_proof_fails_closed(self):
        self.assertEqual(AgentDecision.HOLD,
                         self.decide("PRESENT", old_session=2, actual_session=None).state)

    def test_malformed_endpoint_identity_fails_closed(self):
        result = decide_agent_recovery(
            endpoint_pid=0, endpoint_session=1, current_session=2,
            observation=AgentObservation("ABSENT", pid=0), expected_executable=EXPECTED,
        )
        self.assertEqual(AgentDecision.HOLD, result.state)


if __name__ == "__main__":
    unittest.main()
