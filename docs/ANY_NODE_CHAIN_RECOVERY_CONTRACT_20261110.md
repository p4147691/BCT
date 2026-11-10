# Any-node Chain Recipe recovery entrance — design contract (not implemented)

Status: REVIEWED DESIGN DRAFT. No operational behavior is changed by this document.

## Automatic-first requirement

BCT Core must autonomously observe and heal A/B/C/S chain nodes and reconcile
durable Work/Watch/return records before any user asks for help.
A user asking A/B/C/S to restore the network is **manual recovery fallback**
only after unattended recovery did not resolve the issue. User-supplied raw
Work IDs, UUIDs, approval step names and internal operations are not required
when BCT has sufficient evidence; an internal step is not a new user gate.
Node roles stay unchanged. Normal SELF tasks continue during unrelated recovery.

The first isolated implementation of automatic Manager failover safety:
- GENERATING and missing RCC telemetry UNKNOWN cannot trigger takeover;
- actual positive DISCONNECTED/ORPHANED signals require elapsed observation
  and a fresh final recheck before an epoch transition;
- an ordinary Worker cannot be silently promoted to Manager;
- all active Chain Watches and unacknowledged Manager returns rebind in
  one SQLite transaction with predecessor proof, no first-100 truncation.
This does NOT yet create replacement A/S/Worker nodes automatically. Full
auto restoration remains incomplete until exact-target provisioning,
network role transfer, durable send, Watch return, reboot and crash E2E pass.

## User command / primary guarantee
A user may tell the Manager A, or any available B/C/S node:
"문제가 생긴 노드를 확인하고 기존 체인 복구 후 하던 일을 계속해."
The receiving AI node is an **intake and coordinator** (not the acting replacement Manager).
It should inspect BCT state/receipts and run the already defined Recover Node R and Watch·Alarm Continuation R; it must eventually return to its own original Direction/Task/generation. User must not need to provide Work IDs, UUIDs, operations, role tokens or special approvals for ordinary recovery.

## Recovery scope and routing
1. Start with bct_status, current Node Info and durable conversation network directory; infer the original Work/Direction/Task/generation from existing watches, directions, execution plans and return checkpoints. Prefer explicit context already in the receiving conversation over mere recent timestamps.
2. For unique, evidence-backed target, use existing Check Node R → Recheck Node R. If the node is GENERATING or making progress, WAIT; never replace due only to elapsed time.
3. Also read the exact target's last assistant turn via the existing RCC read-latest-assistant capability, when the exact UUID, session/tab/window and response are confirmed. Last completed answer is *evidence*, not proof of current health. An inaccessible RCC is an observation failure, not automatically a dead node.
4. Reuse the same UUID, tab/session if recovery or reattachment succeeds. Only after confirmed unavailability and an authorized user recovery instruction should Replace Node R create/bind a successor with its **actual** conversation UUID, preserving existing identity receipts.
5. Before external sends, persist exact instruction/delivery identities and source evidence. Watch·Alarm Continuation R must keep the current pre-arm, immutable receipt, UNKNOWN no-replay and SELF/MANAGER semantics. A future common recovery Inbox can be a read-only projection over existing ledgers, not an independent competing message store.
6. Reconcile **all** original Work-linked active watches, pending/checkpointed worker returns and delivery operations (no silent first-100 truncation); fence old A at the Manager binding/epoch before successor A can author the next Direction. Rebinding across tables must not leave silent partial success. Preserve original task history, return payloads and old A's audit trail.
7. Recovered A reads original Work context, pending returns and each exact receipt; acknowledges receipt review before issuing its own new Chain Recipe Direction. An intake B/C/S does not write A's decisions. Then B/C/S resumes its own previously saved plan and next incomplete step, rather than spawning a second chain.
8. S remains the single global integration/CI/E2E Supervisor. S failure uses the **same** Check/Recheck/Recover/Replace primitives. An extra standby S is not a prerequisite; no special Supervisor authority is conferred by role tags.

## No artificial gate
These are **internal steps the agent/tool performs**, not questions for the user. Receipt/epoch/Work identity are continuity checks, not new permission grants. If user asked for recovery, ordinary reversible diagnosis and recovery steps should proceed without a second approval. If a target cannot be unambiguously identified, show natural project/node choices, not raw internal IDs.

Only genuine external-effect uncertainty, different plausible targets, policy-protected irreversible action, or inability to prove exact recipient may stop an effect. That pause must not block unrelated active work and must report the single concrete reason and next safe action. UNKNOWN is recorded, reconciled against the original receipt, and never retried under a new ID. Do not silently close user tabs or override human-changed Node Info.

## Failure-injection acceptance
- User asks A to restore B, or B/C/S to restore A; same exact Work and original task continuity without extra Manager privileges or manual IDs.
- A is generating for >300s: does not takeover or demote A.
- RCC disconnected but browser alive: retry observation/rebind, no premature replacement.
- A missing, B MANAGER return completed: return stored before send, recovered A consumes once; original B task not replayed.
- Multiple Worker returns and >100 watches/checkpoints: full cursor-based reconciliation, no truncation claimed as success.
- A and S both unavailable while Core/storage alive: durable pending records preserved; next available node can coordinate the same recovery; no mandatory backup S.
- Core crash before/after durable write / pre-arm / RCC send / alarm / successor role transfer / ACK: recover from durable ledger; no UNKNOWN resend and no dual Manager.
- Replacement receipt UNKNOWN: preserve original and stop only the unsafe external mutation; permit unaffected SELF branches.
- B/C/S intake returns to its own previously bound Task and plan after recovery (not reassigning itself as A).
- Recovery must not add a mandatory role/scope/approval gate beyond existing Core principal capability, exact target and UNKNOWN safety fences.

## Existing baseline, not new systems
BCT: bct_chain_recipe, bct_check_node, bct_recheck_node, bct_replace_node, bct_reset_node,
DurableWatchLedger, ChainManagerRecoveryLedger, ChatInputQueue, RCC read-latest-assistant.
The current manager_succession_recovery has timeout-based takeover eligibility for GENERATING and includes WORKER candidates: this behavior needs isolated safety review before promoting unattended auto-recovery.

## Scope of this document
Planning contract only. No new public command, message dispatch, background watcher, authority, LIVE behavior or source implementation is asserted.
