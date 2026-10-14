# BCT Durable Orchestration V1

Status: COMPLETE / BOUNDED_V1_LIVE_ACCEPTED.

## Current gate (supersedes historical checkpoints below)

PR #107 exact-head/main CI and exact-SHA Core/RCC deployment passed, followed by
one fresh manager/worker gate and one two-worker/manager-takeover/synthesis chain.
The chain session is FINISHED/APPLIED, with 3 dispatches, 3 results, two consumed
worker results and zero new unresolved claims. All 26 historical claims remain
unchanged. Full evidence and limitations are in
`../completed/BCT_RCC_CANONICAL_TEXT_AND_ORCHESTRATION_ACCEPTANCE_20261014.md`.
The remainder of this plan is historical design/recovery context, not a request
to rerun acceptance. Existing references to this path are preserved.

### Historical promotion checkpoint (superseded by acceptance above)

Latest explicit user clarification authorizes verified PR/CI/main, exact-SHA
deployment and RCC reload for this correction, superseding the brief LIVE hold.
It does not authorize CLI updates or Chrome restart. Preserve all UNKNOWN/claims
and resume only staged acceptance on fresh unclaimed targets. Issue #106 remains
deferred; no broader monitor work is added.

Feature scope is frozen. Single roundtrip and durable receipt retrieval passed
on the PR #105 payload; the single manager/worker gate is not accepted. Do not
run the multi-worker or manager-takeover chain until the preceding gates pass.

PRs #103/#104 corrected node-sync prevalidation and the real RCC registration
wire field. The exact, message-free run04 resolver succeeded and released only
that node-sync claim. All other historical UNKNOWN operations stay quarantined.

The subsequent fresh bootstrap succeeded with RESULT_PERSISTED, but run06
returned ORCHESTRATION_TARGET_BUSY before dispatch. Its worker retained the
bootstrap content record at submitted. The existing reload-recovery helper
could retire that state, but beginRelayExecution only invoked it for completed
records. The previous isolated test exercised the helper, not this entry path.

RCC 1.0.18 adds receipt-only retirement at the actual begin entry. Exact relay,
sender tab, durable conversation, terminal receipt/hash, unchanged local record
and unchanged route are required. A page-local retired-ID fence prevents late
collectors from resurrecting the old record. No prompt/result replay, queue
drain or claim release is performed by this path. The new entry-path regression
failed before the fix and passes after it, with missing/mismatched receipt,
route/record races and late-collector negative cases.

PR #105 promotion and the first two gates passed. The fresh single-manager
attempt again failed during response capture. Only READ-only diagnosis and
evidence documentation followed; speculative patch/deploy loops are stopped.
Monitor grouping remains out of scope.

Explicit continuation checkpoint: RCC 1.0.19 now has an isolated tree/selector
fixture exercising the real routed-turn entry and actual injected direct
recovery function. Both fail on 1.0.18 and pass with the bounded correction:
remove only a span[aria-hidden=true] containing exactly the ellipsis character
immediately following a data-search-result-target sibling. No submitted-text
trimming or equality relaxation is added. Literal ellipses, unknown decoration,
changed text, wrong conversation and ambiguous turns remain fail-closed.
The v12 content/background markers are aligned and regression-checked. This
candidate still requires full local/CI/main validation and exact RCC deployment
before one fresh manager/worker gate on an unclaimed target. Prior successful
roundtrip/recovery tests are reused as evidence, never resent. Historical
UNKNOWN resources stay quarantined. No CLI upgrade or monitor implementation.

### PR #105 staged acceptance evidence (2026-10-14)

- Exact head `8f0baba944a654923c4d81d0065eb33e21494681`: PR CI
  `38556925764` PASS. Merge `6a6d4182950455f505534779bf24edc3f02a51bf`:
  main CI `38557517486` PASS. Local acceptance: 184 Python tests, compileall,
  all 18 RCC JavaScript test programs, and diff checks PASS.
- Core deploy `rcc-v11-deploy-core-6a6d418` was APPLIED at that exact SHA.
  RCC 1.0.18 source/payload hashes were checked; deployment backup is
  `D:\BCT\data\deployments\BCT-RCC-V11-6A6D418\backup`.
- Existing-tab send `rcc-v11-single-roundtrip-send-01` was submitted exactly
  once, FINISHED/APPLIED, SUBMITTED_CONFIRMED, RESULT_PERSISTED. Reply was
  `{"ok":true,"nonce":"RCC-V11-SRT-01"}`; result SHA256 was
  `9e829d7394872933f8e427d19b07bf95ec004797ea7f80762502421792f7dd14`.
  Repeated BCT and RCC reads agreed. `ackState=UNACKED` is result-consumption
  ACK, not a missing submit ACK; submit had consumed-lease/delivery evidence.
- `rcc-v11-single-roundtrip-receipt-reload-01` performed one controlled RCC
  reload. The same persisted reply/hash/identities were recovered after the
  new session without a resend. This proves post-reload receipt recovery,
  not interruption at every possible in-flight crash point.
- Target: tab `594833020`, conversation
  `6acf5db0-38ec-83e8-920b-a6fdb7357fda`, node `worker-capture-v10b`.
- Single-manager operation `single-manager-worker-dispatch-6a6d418-07`
  (work `BCT-SINGLE-MANAGER-WORKER-LIVE-6A6D418-07`) is FINISHED/UNKNOWN;
  assignment `single-worker-acceptance-6a6d418-07` is UNKNOWN. RCC relay
  `orch.send.40e780fac604b3bc2b76ac3c595c7cb8` confirmed submission, then
  persisted a failure: FINAL_DOM_VALIDATION,
  `RELAY_FINAL_DOM_NOT_READY:ROUTE_TURN_NOT_RESOLVED`, `net::ERR_ABORTED`.
  The screen contains a matching result envelope, but no accepted result is
  inferred from screen visibility alone.

### Confirmed canonical-text mismatch and remaining uncertainty

The exact durable prompt is 1,244 characters. Both nested diagnostic user-unit
wrappers produce 1,245 characters, with the first difference at index 1,244.
The message ends in `[/BCT_ORCHESTRATION_ASSIGNMENT_V1]`; the wrapper adds `…`.
READ-only DOM inspection locates the extra character in a sibling
`<span aria-hidden="true" class="block">…</span>` outside the actual message
body, next to a collapsed `aria-expanded="false"` more button. The original
1,244-character message body is intact. These nested wrappers are not evidence
of two sends.

`content.js::messageUnitText` / `turnUserText` includes this UI decoration;
`submittedPromptMatchesTurn` then fails exact equality and `resolveRoutedTurn`
cannot select the submitted turn. Direct background recovery also uses cloned
user-wrapper text and needs the same regression coverage. This is a confirmed
explanation of the final DOM matching failure, not proof of what originally
caused the separate network abort signal.

The persisted timing proves exact draft validation before click. Later
READ-only inspection found an empty composer, no send/stop button, terminal
pending=false, and activeExecution=null. The historical editor replacement
instant was not captured and must not be invented. No failed message was
resent, and no screen result was imported through an ad-hoc reconciliation.

At this checkpoint, all 24 protected preexisting claims were unchanged. The
two new claims are retained:

- `orchestration-attachment:att-e752ccb1ddda49ab9ea49f6a`
- `orchestration-run:single-manager-worker-live-6a6d418-07:single-worker-acceptance-6a6d418-07`

No multi-worker/manager-takeover chain ran. Do not rerun either successful gate.
The next bounded correction must first reproduce collapsed/expanded long
messages in isolation, distinguish UI ellipsis from literal user text, preserve
inline code/newlines/Unicode, reject wrong or ambiguous turns, and cover both
normal and direct-recovery entry paths. Do not simply strip a trailing `…` or
relax exact turn identity. Only a proven correction may be proposed as one PR.

Metadata follow-up: background reports recovery-v11, but content.js still has
the recovery-v10 build string. Source and installed content SHA agree, so this
is a stale marker, not evidence of a different installed file. Include marker
consistency in the next bounded regression; no separate deployment was done.

### Separate READ-only status follow-ups

GitHub #82 remains the improvement ledger. Its RCC projection note records the
full-state/1-second monitor budget, existing cached Native Host `presence`
command, and stale global stop-selector/probe-fallback paths. Routine presence
would require exact instance/session and observation-age checks, with explicit
STALE/UNKNOWN rather than fail-open IDLE. User-reported multi-second full-state
wall times include MCP overhead and are not internal RCC timings. These are
separate candidates, not the confirmed routed-turn mismatch above. No monitor,
presence or generation-state implementation changed in this checkpoint.

The supplemental report's Core transition from generation 80 to 81 is accounted
for by PR #105 deployment; RCC session changes occurred during the controlled
deployment reload and persisted-receipt recovery test. No unrelated task was
interrupted and no rollback was performed.

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

After RCC 1.0.10 deployment, four new bootstrap operations all returned
`APPLIED`, but the next chain immediately and safely returned both assignments
as `NOT_APPLIED / ORCHESTRATION_TARGET_BUSY`; it sent no worker message and
released its claims. Probe evidence showed each new tab retained a completed
bootstrap record whose conversation key was the transient `local-chatgpt`
route while the final tab URL already had a durable UUID. RCC 1.0.11 excludes
that provisional route in the shared identity parser and makes fresh-tab
bootstrap wait for the durable key. This addresses the source of the stale
record rather than weakening the 1.0.10 busy-target fence.

The first 1.0.11 chain attempt (`durable-orch-live-chain-e25a451-v5`) ended
`FINISHED / FAILED` with every claim released and no submitted worker turn.
SQLite receipts distinguish two pre-dispatch causes: the latency worker's
exact draft was present but ProseMirror exposed its single inserted newline as
paragraph layout spacing (`RELAY_EDITOR_TEXT_MISMATCH`), and the recovery
worker retained a completed bootstrap record although the background already
held its exact durable result (`ORCHESTRATION_TARGET_BUSY`). RCC 1.0.12 adds
paragraph-aware draft comparison and exact durable-receipt cleanup. Both paths
remain fail-closed when the text, tab, conversation, or receipt does not match.

The first fresh 1.0.12 bootstrap returned `APPLIED`, but direct read-only UI
evidence showed its content record still at `submitted` even though the
background already held the exact terminal result. The next chain was not
started. RCC 1.0.13 therefore applies the same exact receipt, tab, and durable
conversation proof before clearing either a `submitted` or `completed` local
record. No prompt or result is replayed.

The original implementation acceptance proved 174 Python tests, all 15 RCC
JavaScript test programs, Python compileall, JavaScript syntax, and
`git diff --check`. Independent API, SQLite/recovery, and RCC audits all
concluded `BLOCKER_NONE` before the first GitHub integration. Recovery-fix
acceptance proves 178 Python tests, all 15 RCC JavaScript test programs, Python
compile checks, JavaScript syntax, and `git diff --check` before GitHub
integration.

The RCC 1.0.12 candidate acceptance proves 180 Python tests, all 15 RCC
JavaScript test programs, Python compile checks, JavaScript syntax, and
`git diff --check` before GitHub integration.

After the RCC 1.0.17 route-capture correction, a fresh single-manager gate
exposed a separate Core ordering defect: `node-sync` could update an RCC role
binding before detecting that the conversation already belonged to another
active logical node. The deterministic ownership conflict then became UNKNOWN
and retained the global RCC-instance claim. The bounded correction prevalidates
all requested conversation owners before any RCC call. A dedicated
`recover-node-sync` operation is limited to the exact legacy UNKNOWN error,
exact claim, assignment-free session, and the persisted active binding set; it
restores only matching open tab/conversation registrations, verifies readback,
then atomically marks the original FAILED and releases its claim. It never sends
a ChatGPT message. Candidate acceptance proves 184 Python tests and all 17 RCC
JavaScript test programs before GitHub integration.

The first LIVE recovery attempt stopped before mutation because the isolated
relay double represented state registrations with the bind-ACK field
`instanceId`; real RCC state uses `transportInstanceId` while bind ACKs use
`instanceId`. READ-only comparison proved every tab, conversation, role, and
stored receipt otherwise matched. The state-side validator and test double now
use the real wire contract; the failed resolver released only its own recovery
claim and left the original UNKNOWN claim intact.

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
