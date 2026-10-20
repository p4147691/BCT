# BCT Desktop UIA Expand UNKNOWN 공유 Claim — 원인 및 격리 복구 후보

상태: ISOLATED SOURCE CANDIDATE / LIVE_NOT_APPLIED / OPERATOR_APPROVAL_REQUIRED

## 원본 증거

- Work: `BCT-MONITOR-LIVE-SVG-BADGE-E2E-20261020-01`
- Operation: `monitor-live-reload-menu-expand-20261020-01`
- capability/target: `desktop_uia_element_action` / `expand:desktop-uia`
- FINISHED / UNKNOWN, error:
  `DESKTOP_SESSION_AGENT_EFFECT_UNKNOWN:DESKTOP_UIA_ACTION_CHANGED_FOREGROUND`
- request digest:
  `a259ceadef2cbc8316d34a8d81683190e872295a93778714aced22940f557e62`
- current shared fence: `desktop-control:interactive-session`
- VTL Desktop Session Agent source: `VtlDesktopSessionAgent.cs`, `ActOnDesktopUiaElement`.
  After helper executes, foreground comparison finds a change. `action.invoked=true`
  yields `InputEffectUnknownException`. This is NOT proof of no effect.
- Fresh read-only agent status: responsive, control.lease=null,
  emergencyStop.active=false. This does NOT retroactively prove whether
  the menu expanded on the original call.

## Why generic reconcile is forbidden

Existing `claim_reconcile` accepts only provable no-effect operations
(read, system_inspect, github_pr_status, execute-before-CreateProcess).
The original UIA action may have happened. Neither stale age, lease expiry,
foreground observation nor another successful action may change its
UNKNOWN outcome to APPLIED/NOT_APPLIED.

## New optional exact operator quarantine

The proposed `claim_reconcile` mode `quarantine_uia_expand` requires:
- Same original Work and principal, with original UIA action permission.
- Original FINISHED/UNKNOWN exactly, capability and target exactly equal to
  `desktop_uia_element_action` / `expand:desktop-uia`.
- Original error exactly CHANGED_FOREGROUND, exact request digest, and
  operation finished at least 120 seconds ago.
- Explicit `ACK_UNKNOWN_UIA_EXPAND_EFFECT_NO_REPLAY` operator acknowledgement.
- Fresh desktop-session `control_status` (<=30 seconds), no active lease,
  no emergency stop, interactive input desktop available.
- Atomically verify old unresolved global fence is exactly one resource,
  move that fence to
  `desktop-control:quarantined-uia-expand:<original_operation_id>`,
  then persist a distinct OPERATOR_QUARANTINED event and resolver receipt.
- The old Operation outcome/error/receipt remain **UNKNOWN** and cannot
  be retried. The total unresolved Claim count need not drop; only the
  global blocking fence becomes an exact historical quarantine.
- Any wrong evidence/active lease/duplicate/digest mismatch fails closed.
  No direct SQLite updates, no manual forced Claim release.

## Validation / deployment boundary

All changes must run on disposable SQLite fixtures, never operational
`D:\BCT\runtime\state\state.sqlite`.
Do NOT execute quarantine mode on LIVE until approved deployment
and explicit operator acknowledgement at the time of action.
No RCC reload, Desktop Window automation retry or Claim mutation in this PR.
A successful PR/CI is NOT LIVE recovery.
