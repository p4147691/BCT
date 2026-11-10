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

## Automatic Core Check/Recheck, before manual fallback

The BCT Core background thread continuously inspects current Work-linked
A/B/C/S nodes from existing active Chain Watches, unacknowledged Manager
returns, and active or ready Direction relationships. A Direction saved
before the first Watch provides original A and S identities; an individual
Worker is added only after its child Direction is marked CHAIN_STARTED,
not while its send is merely planned. Completed Worker returns never
cause a second Worker recovery or replay. It does not ask a Manager, Worker, Supervisor or user to start.
For each exact UUID, Check/Recheck evidence is stored in the existing
NodeRecoveryLedger (one case per Work and assignment epoch). Healthy nodes
and long GENERATING turns are left untouched. A Worker already finished in
MANAGER_RECOVERY_PENDING, or present only in a completed return checkpoint,
is never considered an unfinished node requiring automatic re-execution. If BCT cannot obtain a fresh
RCC/Node Info snapshot it marks the sensor UNKNOWN, never the node dead.
Two consistent failure observations create RECOVERY_NEEDED; repeated identical
signals do not grow the same ledger indefinitely. When the original UUID
reappears with fresh confirmed readiness, the case becomes RECOVERED,
and existing delayed-send Watch/SELF and Manager-return mechanisms continue.
Core restart reuses the existing recovery case and original Task/Generation.

This stage is **automatic observation and same-UUID restoration only**, not
an assertion that arbitrary missing conversations can be opened or replaced.
A missing verified successor UUID must never be invented; replacement requires
the existing exact identity, durable send receipts, role/epoch transfer,
and E2E evidence. Until those mechanisms are implemented the case stays
RECOVERY_NEEDED instead of introducing a user confirmation barrier or
claiming successful recovery.

## Automatic formal Manager transfer reconciliation

When an actual BCT conversation-network Manager transfer has already been
committed, the Core scans original Work-linked Watch and return checkpoints,
reads the latest immutable manager-transfer receipt, and verifies the
successor's current actual UUID, Node Info Manager role, network scope and
positive RCC connection. Only then does it atomically rebind all active
Watches and unacknowledged returns to the proven successor without any
new user prompt. A missing connection, role conflict, stale superseded
transfer or inconsistent predecessor identity cannot elect a successor.
The newest Manager transfer is checked inside the same SQLite transaction
as the rebinding to avoid a time-of-check/role-change race. Any DELIVERING or
UNKNOWN external effect stays unresolved and is never replayed as a fresh
message. This does not create new Chat conversations automatically; that
physical provisioning capability and replacement E2E remain unfinished.

## Automatic finalization of a proven, previously prepared B/C/S replacement

When Node Recovery has already recorded REPLACEMENT_PREPARED, the BCT Core
automatically resumes the last safe stage after a restart. It reuses the exact
actual successor UUID, fresh Node Info evidence and the original inheritance
Task, rather than creating a second tab or replaying the initial instruction.
A successor must have produced a durable observed response from the intended
Work's inheritance Watch before the original atomic NodeRecovery.commit_replace
is called. A bare WATCHING reservation is not proof of a sent instruction.

The predecessor must remain unavailable, and any UNKNOWN or DISPATCHING
original-task Watch holds the automatic role transfer for reconciliation.
If the original node comes back, no replacement occurs. Worker and S
replacement use the existing role/scope transfer, do not create a backup S,
and resume the prepared replacement without asking the user for IDs or a
second approval. If global S still has active Watch/return bindings across
other Work, this narrow stage reports SUPERVISOR_GLOBAL_REBIND_REQUIRED and
preserves the prepared case/role. Global S role transfer must not silently
strand other networks; full cross-Work atomic rebinding remains separate.
Manager A is intentionally excluded from this role-only path
because its Work Epoch and Watch/Manager-return binding must be fenced
atomically through Manager succession. A Manager cannot be promoted by merely
giving it a role tag.

This only completes already-prepared replacements. The full unattended
creation/first-send/exact UUID discovery for all roles still needs integrated
RCC/Node Recovery testing and must not be claimed as complete.

## Recovery scope and routing
1. Start with bct_status, current Node Info and durable conversation network directory; infer the original Work/Direction/Task/generation from existing watches, directions, execution plans and return checkpoints. Prefer explicit context already in the receiving conversation over mere recent timestamps.
2. For unique, evidence-backed target, use existing Check Node R → Recheck Node R. If the node is GENERATING or making progress, WAIT; never replace due only to elapsed time.
3. Also read the exact target's last assistant turn via the existing RCC read-latest-assistant capability, when the exact UUID, session/tab/window and response are confirmed. Last completed answer is *evidence*, not proof of current health. An inaccessible RCC is an observation failure, not automatically a dead node.
4. Reuse the same UUID, tab/session if recovery or reattachment succeeds. Only after confirmed unavailability and an authorized user recovery instruction should Replace Node R create/bind a successor with its **actual** conversation UUID, preserving existing identity receipts.
5. Before external sends, persist exact instruction/delivery identities and source evidence. Watch·Alarm Continuation R must keep the current pre-arm, immutable receipt, UNKNOWN no-replay and SELF/MANAGER semantics. A future common recovery Inbox can be a read-only projection over existing ledgers, not an independent competing message store.
6. Reconcile **all** original Work-linked active watches, pending/checkpointed worker returns and delivery operations (no silent first-100 truncation); fence old A at the Manager binding/epoch before successor A can author the next Direction. Rebinding across tables must not leave silent partial success. Preserve original task history, return payloads and old A's audit trail.
7. Recovered A reads original Work context, pending returns and each exact receipt; acknowledges receipt review before issuing its own new Chain Recipe Direction. An intake B/C/S does not write A's decisions. Then B/C/S resumes its own previously saved plan and next incomplete step, rather than spawning a second chain.
8. S remains the single global integration/CI/E2E Supervisor. S failure uses the **same** Check/Recheck/Recover/Replace primitives. An extra standby S is not a prerequisite; no special Supervisor authority is conferred by role tags.

## Durable manager returns with or without a working S

For a Direction-linked Worker MANAGER return, BCT persists the exact Task,
generation, response turn, response hash, and return payload *before* any
browser delivery. This does not require a live or designated Supervisor.
If A is confirmed unavailable, S receives only an advisory copy when its
exact endpoint is available. If S is absent, disconnected, or unobservable,
BCT retains a PENDING return and terminates this continuation as
MANAGER_RECOVERY_PENDING without submitting to a guessed destination.
A recovered/successor Manager reads the existing recovery Inbox and ACKs
the precise return; no completed Worker task is replayed.

A resumed Manager rebinds WATCHING, RESERVED, and PAUSED Watch relationships
along with unacknowledged returns in one transaction. PAUSED remains PAUSED.
DISPATCHING/UNKNOWN watches are retained and surfaced as unresolved; they are
not changed and must never be represented as a fully completed network recovery.
No additional user approval, ID prompt, or extra S is required by this rule.

## Automatic restoration of an already-recorded Manager return

The existing BCT delayed-watch Core loop checks PENDING/DELIVERING Manager
return checkpoints without a user request. It only handles exact source
Watches already terminated as MANAGER_RECOVERY_PENDING. It waits while A is
unavailable or GENERATING, and sends one original completed Worker return
envelope when the same or formally rebound Manager is idle.

The exact source Work, Task, Generation, response SHA and active Manager UUID
derive one deterministic BCT browser Operation ID. The checkpoint records
DELIVERING and that ID before any RCC effect. On Core restart the same claim
and Operation receipt are reconciled: APPLIED closes as RETURNED_TO_MANAGER,
UNKNOWN remains UNKNOWN and is never resent under a fresh ID. Submitted is
not the same as Manager-acknowledged. The recovered A must still read and
ACK the original checkpoint before a new Direction.

A concurrent Manager replacement never rebinds an in-flight DELIVERING
checkpoint to a different Manager. It remains explicitly unresolved until
the original external effect is reconciled, without blocking unrelated
Worker SELF work. These are Core-internal identity and continuity checks;
none are extra user authorization steps.

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
