# BCT Persistent Project Run bridge

Status: `SLICE_2_SOURCE_IMPLEMENTED / CI_PENDING / LIVE_NOT_APPLIED`

## Problem confirmed on 2026-10-22

The Conversation Network implementation successfully provides one user-facing
conversation scope (called a project or a conversation network), durable
display aliases, ordering, and advisory role tags.  Its `Manager` tag is
deliberately not an authority.  Durable orchestration separately owns Work,
orchestration session, attachment identity, manager epoch, dispatch outbox,
receipt, and recovery.

There is no durable bridge between those two models.  Therefore selecting a
Manager in the BWM UI does **not** start a Core manager epoch, attach a
particular ChatGPT tab, send a relay message, wake a worker, or fail over a
slow conversation.  Treating UI metadata as though it did would be an unsafe
and misleading legacy shortcut.

## Single concept, small execution record

- `conversation_network_projects` remains the one user-facing scope.  No new
  `network_id` registry or second project hierarchy is introduced.
- A `persistent_project_run` is not a second project.  It is one bounded
  execution instance of an existing scope: selected Manager conversation,
  objective, current Core Work/session, and exact RCC attachment generation.
- A run starts `PLANNED`; planning creates no Claim and performs no browser or
  RCC effect.  It becomes `READY` only after the scope's explicitly selected
  Manager UUID is proven equal to the active Core session-node and RCC
  attachment.  Titles, N labels, Chrome window IDs, and role names cannot
  substitute for this proof.
- Multiple `Manager` role tags remain allowed.  Starting a run requires the
  caller to choose one tagged conversation explicitly; there is no first-node
  election or hidden privilege.
- Only one nonterminal run may control one scope.  That prevents duplicate
  wake-up loops while allowing unrelated scopes to proceed.

## Delivery slices

1. **Bridge foundation (this change):** schema, identity-checked planned run,
   exact Core/RCC attachment binding, read model, and isolated regressions.
2. **Supervisor checkpoint:** an explicit scoped command creates a Work and
   run, syncs exact RCC attachments, and sends one structured Manager planning
   request.  It is idempotent and records submit/result receipts.  No periodic
   free-running poller is introduced.
3. **Manager/Worker cycle:** reuse the existing durable orchestration outbox
   for Manager decisions and Worker results.  Wake only on a persisted result,
   an explicit deadline, or an observed health transition; never on a timer
   alone.
4. **Degraded handoff:** first record health evidence and mark the run
   `DEGRADED`.  A Manager decision selects a successor from the same scope and
   creates a fenced new manager epoch.  Silent replacement based on a title,
   slow page, or a single timeout is prohibited.
5. **Legacy retirement:** inventory callers first.  Old relay entry points may
   be isolated only after the bridge covers their contract and actual callers
   are zero.  No deletion is bundled with a new control path.

## Browser Bridge first use

The existing `Browser Bridge` scope is the first candidate run.  The current
UI Manager is advisory until slice 2 binds its exact UUID to a newly synced
Core attachment.  The first external command must be bounded: ask the Manager
for a structured project checkpoint and a short next-action plan; it must not
create tabs, send a second relay message, or mutate LIVE systems implicitly.

## Explicit non-goals of this change

- no RCC/Chrome/Native Host reload, deploy, or message send;
- no Browser Bridge WRITE/EXECUTE integration;
- no automatic promotion of a different chat merely because a page is slow;
- no conversion of historical UNKNOWN into a completed result;
- no Monitor responsibility for scheduling or execution authority.

## Verification required before slice 2

- manager tag remains advisory until explicit selected-run creation;
- a scope permits multiple tagged Managers but has only one active run;
- a foreign UUID, inactive attachment, stale attachment generation, inactive
  session node, different Work, or different Core manager cannot bind;
- binding is idempotent for the same Work/session and automatically advances
  to a newer active attachment generation of the same exact conversation;
- a stale inactive generation is rejected at bind/send time without making
  the run permanently unusable;
- project-scope reads never create a run, Claim, or browser side effect.

## Slice 2 source integration

The existing public `bct_orchestrate` capability now exposes three bounded
operations rather than adding a new transport or public tool:

- `project-run-plan`: records the selected tagged Manager and objective for
  one existing conversation scope. It performs no RCC/Chrome effect.
- `project-run-bind`: binds that run to an already active orchestration
  session and its exact Manager attachment. Rebinding the same conversation
  to its latest active generation is supported after reload or tab reattach.
- `project-run-status`: returns the run bridge and scope members without
  contacting RCC or Monitor.

Focused verification: `5` Project Run tests and `53` orchestration tests pass,
including the public capability path and generation advance regression.
The next step is exact-head CI, followed by local-main integration and an
explicitly bounded LIVE Manager checkpoint on the Browser Bridge scope.
