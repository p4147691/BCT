# BCT Durable Orchestration V1

Status: ACTIVE / FIRST_LIVE_E2E_QUARANTINED / RECOVERY_FIX_LOCAL_ACCEPTED / GITHUB_AND_LIVE_PENDING.

## Objective

Turn the current collection of durable BCT operations and RCC-controlled ChatGPT
conversations into one recoverable manager/worker flow. A user gives one bounded
goal to one front door. BCT persists that goal, lets a manager assign work to
workers, records acknowledgements and results, replaces unavailable nodes, and
continues until the acceptance criteria are met.

The user authorized implementation, tests, GitHub main integration, exact-SHA
LIVE deployment, and a real chained E2E using the already open RCC conversations.
Ordinary implementation choices and in-scope failure recovery do not require
additional confirmation.

## Preserved contracts

- Work scope outlives a browser tab or model turn and is not silently widened.
- Node display names and roles do not grant technical authority.
- Operation-ID idempotency, atomic resource claims, exact-SHA deployment, and
  UNKNOWN no-retry remain unchanged.
- A lost response may be read again; a delivered external effect is not replayed.
- A problem with one resource quarantines that resource and its dependants, not
  unrelated work.
- Deletion, credential or privilege changes, paid resources, and irreversible
  data loss remain outside automatic authority.
- Existing Durable Recipe V1 is reused. This project does not introduce arbitrary
  YAML, a general workflow language, or concurrent repository writers.

## Current verified baseline

- GitHub main, local source, and LIVE Core release before this recovery patch:
  `548e78669db72d4989562ea1bcd9aa4f35f0c88e`.
- Core was ready and the MCP catalogue exposed 24 tools.
- The first LIVE orchestration session and its seven unresolved claims are
  retained as quarantined historical evidence.
- All MCP calls currently use principal `bct-mcp-local`.
- Existing whole-work handoff refuses any work with an active operation or
  unresolved resource claim.
- Durable Recipe V1 persists step journals but intentionally has no automatic
  orchestration resume.

## V1 architecture

### Durable session

A session persists the user's objective, bounded roots/actions, acceptance
criteria, current plan revision, manager epoch, state, and terminal summary.
Authority is derived from the parent BCT work and can only be delegated as a
subset. Replacing a connection or node does not create or expand authority.

### Nodes and attachments

Logical nodes are registered independently of RCC browser attachments. An
attachment identifies an exact RCC instance/session/tab/conversation generation.
Multiple tabs for one conversation do not create multiple workers. Presence is an
observation, not proof that a model is alive or that a task is still executing.

### Assignments and mailbox

The manager creates a durable assignment with one request digest, delegated
scope, dependencies, attempt generation, and acceptance contract. Mailbox
messages record dispatch, acknowledgement, progress, result, consumption, and
cancel/replace intent. Delivery may be retried with the same message identity;
the assignment's external work is never replayed merely because delivery or
response acknowledgement was lost.

### Manager and worker fencing

Only one manager epoch may create new assignments. Manager failover increments
that epoch atomically; stale managers may submit historical evidence but cannot
schedule new work. Worker replacement creates a new assignment generation only
after the old generation is proven not dispatched/not applied or the remaining
task is a distinct safe continuation.

Manager ownership is separate from operation/resource ownership. An unresolved
operation blocks only its claimed resource and dependent assignments; it does not
prevent a new manager from coordinating unrelated work.

### Reconciliation

Recovery first inspects durable receipts and observable effects. It reuses
FINISHED evidence, continues from verified checkpoints, and quarantines
ambiguous external effects as UNKNOWN. Reconciliation never rewrites the
historical receipt or converts absence of a heartbeat into proof of non-execution.

## Delivery sequence

1. Add additive SQLite schema and models for sessions, nodes/attachments,
   assignments, mailbox messages, manager epochs, and reconciliation decisions.
2. Add a small orchestration service that validates delegated scope, atomically
   assigns/acknowledges/completes work, fences stale epochs, and selects only
   ready dependency nodes.
3. Expose bounded MCP tools for session start/status, node sync, assignment
   dispatch/result, manager takeover, and reconciliation. Keep existing tools
   backward compatible.
4. Add an RCC adapter that maps exact observed conversations to logical nodes,
   sends an assignment envelope once, and imports an exact result envelope.
5. Add a deterministic manager loop for plan -> dispatch -> collect -> decide.
   It stops only for terminal success, explicit user cancellation, exhausted
   bounded alternatives, or an action outside the stored authority.
6. Add Monitor projection and locate metadata without treating browser presence
   as authority or liveness.
7. Run focused and full tests, open a PR, require exact-head CI, merge, sync
   main, deploy that exact SHA, and perform the LIVE chained E2E.

## Implementation checkpoint

The local implementation now includes the additive orchestration schema,
manager epochs, exact RCC attachments, assignment generations, mailbox/result
consumption, bounded chain execution, manager takeover, proven-safe worker
replacement, Monitor projection, and the `orchestrate` MCP capability.

Recovery is fenced at three independent boundaries:

- the original outer operation is changed to a takeover `UNKNOWN` receipt before
  a resolver reads or continues its effects;
- assignment/session evidence and resolver/original receipts close in one SQLite
  transaction;
- every background operation intent is stored in the same transaction as the
  operation and uses one SQLite executor lease keyed by operation ID and exact
  process fingerprint. Core startup reconstructs missing job files, rebinds the
  worker to the current exact release policy, and restarts only a proven-dead
  executor. A malformed filesystem claim is never sufficient to create two
  executors.

The RCC 1.0.8 path adds an exact pre-submit binding lease, location recheck,
post-click lease consumption attestation, persisted ACK/result identity, and a
global conversation quarantine across RCC instances. It preserves existing ACT
bootstrap and full-result capture contracts.

The first LIVE chain at main/LIVE `548e78669db72d4989562ea1bcd9aa4f35f0c88e`
ended `FINISHED / UNKNOWN` after both worker deliveries exhausted their 900-second
result windows. The historical operation, session, seven claims, two delivery
identities, and exact worker attachments remain quarantined and must not be
retried, released, or reused. Read-only SQLite, RCC, and browser evidence showed
two distinct cases: one worker had produced its assignment result before later
ordinary user turns, while the other worker still had the relay text as an
unsent draft. RCC returned neither exact terminal receipt, so Core could not
distinguish the cases and correctly retained UNKNOWN.

RCC 1.0.9 and the Core adapter address the observed gaps without rewriting that
history. An activation checkpoint separates confirmed `NOT_APPLIED` from
post-activation `UNKNOWN`; opted-in orchestration sends persist ACK in SQLite
before result polling; and completion state is read from the exact routed turn,
not a later user turn. A fresh E2E must use new operation/session/assignment IDs
and fresh conversation attachments.

The first fresh-node bootstrap after 1.0.9 exposed a separate bounded recovery
timing defect. `create-and-send` attempted read-only DOM recovery only once as
soon as the network completed; if the exact turn was not yet stable, later
polling observed only the pending receipt and eventually returned UNKNOWN. The
message was not resent. A distinct reconciliation operation recovered the exact
persisted reply for conversation `6acf2829-a8f0-83ec-87b4-fa8cb99f5787` and
released only that new bootstrap claim. The follow-up fix retries only the
read-only recovery probe with distinct request IDs, bounded exponential spacing,
and no submit path.

Follow-up local acceptance proves 179 Python tests, including a first recovery
probe that fails before a later exact terminal receipt is collected; the test
also proves one submit and two distinct recovery request IDs.

The next fresh chain preflight exposed an acceptance-script identity error, not
a runtime delivery failure: its new session reused the first chain's globally
unique assignment IDs, so Core rejected it before dispatch with
`ORCHESTRATION_ASSIGNMENT_REQUEST_MISMATCH`. The distinct failed chain was
closed by `recover-not-dispatched`, whose receipt proves
`external_effect_excluded=true`; no worker message was sent. The script now
derives all worker and synthesis assignment IDs from the fresh run ID.

The next run-scoped chain then exposed a distinct RCC queue-drain gap. Its first
assignment `live-latency-review-8559977-v3` was durably reserved and RCC stored
it as `deferred=true`, `submittedAt=null`; browser and probe evidence proved the
prompt had not been submitted. The target tab was idle but retained the prior
bootstrap relay as `phase=completed`, while that bootstrap's exact result was
already durable in the background. The deferred queue therefore remained at
depth one. RCC 1.0.10 retries only idempotent delivery of that completed result
receipt before a new exact submit. If the stale record remains, or the target
is generating, the new exact assignment returns confirmed `NOT_APPLIED` and is
not queued. The pre-1.0.10 queued item lacks its exact-binding tuple and is
dropped before submit after reload, while its background evidence remains for
explicit reconciliation. This prevents a late send after the Core timeout. The
current chain identity and claims remain preserved for post-deployment
reconciliation.

The original implementation acceptance proved 174 Python tests, all 15 RCC
JavaScript test programs, Python compileall, JavaScript syntax, and
`git diff --check`. Independent API, SQLite/recovery, and RCC audits all
concluded `BLOCKER_NONE` before the first GitHub integration. Recovery-fix
acceptance proves 178 Python tests, all 15 RCC JavaScript test programs, Python
compile checks, JavaScript syntax, and `git diff --check` before GitHub
integration.

## Failure policy

| Failure | Automatic action |
| --- | --- |
| Delivery acknowledgement lost | Read durable RCC/BCT result; retry only the same delivery identity |
| Worker attachment disappears before dispatch | Reattach or replace worker and keep assignment identity |
| Worker disappears after dispatch | Reconcile result; no automatic work replay |
| Manager disappears | Increment manager epoch and continue from durable session |
| Test or implementation fails | Return evidence to manager and schedule a bounded correction |
| UNKNOWN external effect | Quarantine its resources and continue independent assignments |
| BCT restart | Restore nonterminal sessions from SQLite and reconcile before dispatch |
| Scope or credential requirement expands | Persist BLOCKED evidence and request user authority |

Retries are bounded and categorized. Repeated identical failures open or update a
GitHub issue and do not create an unbounded loop. GitHub Issues remains the
improvement ledger; no second ledger is introduced.

## Test and acceptance matrix

Unit and integration tests must prove:

- scope inheritance can narrow but not widen;
- stale manager and stale assignment generations are rejected;
- dispatch/ack/result duplicates are idempotent;
- out-of-order and duplicated mailbox messages do not duplicate effects;
- two tabs for one conversation resolve to one logical node;
- manager replacement succeeds while another resource remains UNKNOWN;
- restart restores the same session plan and evidence;
- cancellation prevents new dispatch;
- existing operation, Recipe, RCC, GitHub, deployment, and policy tests remain
  unchanged in behavior.

The isolated E2E must prove one manager delegates at least two bounded tasks to
distinct open RCC nodes, consumes both exact results, issues at least one
evidence-driven follow-up, replaces either a manager or worker during the chain,
and produces one terminal session summary without human copy/paste.

The LIVE acceptance uses a fresh session, assignment IDs, and harmless diagnostic
tasks. Existing UNKNOWN operations and claims are never reused or released.

## Completion

V1 is complete only when the exact PR head passes CI, the merge commit passes
main validation, that exact main SHA is LIVE, the chained Hosted E2E passes, and
the final receipts prove:

1. one user entry point;
2. no repeated permission request inside the stored scope;
3. no human relay between participating nodes;
4. safe manager/worker replacement;
5. no duplicate external effect;
6. terminal result returned to the initiating manager/front door.
