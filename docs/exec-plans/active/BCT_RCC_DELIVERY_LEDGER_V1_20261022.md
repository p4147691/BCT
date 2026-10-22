# BCT RCC delivery ledger V1

Status: `CHANGE_FREEZE / READ_ONLY_AUDIT_COMPLETE / STATE_MACHINE_CONTRACT_LOCKED / THIN_PATH_LIVE_ACCEPTED / PHASE7_READY`

## Why this reset exists

The current relay product has two independently evolved paths for the same
external effect:

- Simple Relay V0 resolves two conversation UUIDs and performs a small
  Manager-to-Worker send plus a later Worker-to-Manager return.
- Durable orchestration adds session nodes, attachments, generations, binding
  receipts, assignments, mailbox rows, wakes, leases, outbox rows, attempts,
  reconciliations, Core operations and Claims around the same ChatGPT UI send.

The second path is not merely stronger validation around the first path. It is
a separate control model with separate commands and receipt stores. The LIVE
Project Run failures prove that the two models can disagree: the Core continued
to require `conversation-bind` and `send` after the RCC legacy-pruning policy
had removed or blocked those contracts.

The installed RCC payload, the LIVE Core, Chrome and existing conversations
were frozen during phases 1-5. The accepted source is local/remote main
`9f35125516cf2f841aeed75ab53a9a5a02cc5a48`; the Phase 6 LIVE acceptance below
is the first authorized runtime change after that freeze.

## Observed call graph (read-only audit)

```text
caller / Project Run
        |
        | bct_orchestrate or bct_relay_browser
        v
BCT Core feature
  features/orchestration.py              features/rcc.py
  command=conversation-bind/send/result  simple-relay-bind/send/return
        |                                      |
        +------------ NamedPipeRelayClient ----+
                         exact RCC instance pipe
                                      |
                                      v
RCC Native Host (RelayNativeHostV2.cs)
  requestId -> originating pipe client; otherwise a transparent command bridge
                                      |
                                      v
RCC background command policy + handler
  legacy/command_policy.js
  domain/readonly_diagnostics.js
      | Simple Relay V0             | orchestration relay
      v                             v
  simple_relay_service.js       orchestration_relay_service.js
      |                             |
      +---- browserGateway.sendWithReceiver(exact tab id) ----+
                                                             v
RCC content router
  relay:simpleExecute / relay:simpleReadReply
  relay:orchestrationExecute
                                                             |
                                                             v
ChatGPT DOM adapter
  exact conversation UUID -> empty composer -> exact user turn -> new reply
```

The Native Host is not the business workflow. It authenticates and transports
one request/response between BCT and the extension. Chrome window/tab IDs are
observations used to reach a page. The durable address is the ChatGPT
conversation UUID.

## Active commands and policies

### Native commands currently allowed by RCC

| Policy class | Commands | Decision |
| --- | --- | --- |
| new relay | `delivery-start`, `delivery-status`, `delivery-return`, `simple-relay-bind`, `simple-relay-send`, `simple-relay-return`, `new-chat-send` | the three `delivery-*` commands are the replacement; keep new-chat separate; retire the three Simple Relay commands only after acceptance |
| conversation | `rename-conversation`, `conversation-bind` | keep rename; retire persisted relay binding after replacement acceptance |
| orchestration | `send` | replace with the single delivery contract |
| read-only | `delivery-manager-status`, `ping`, `state`, `result`, `rename-receipt`, `probe`, `probe-tabs`, `diagnose-activity`, `diagnose-composer`, `diagnose-conversation-ui`, `api-probe`, `main-capture-get` | keep; consolidate diagnostics later without blocking delivery |
| maintenance | `reload-extension` | keep behind the existing explicit maintenance gate |

Blocked legacy mutations remain blocked. In particular, this reset does not
restore `send-wakeback`, `recover-pending`, `register`, `manager-promote`,
`reload-workers`, `send-to-tab` or `send-to-created-tab`.

### Content messages actually reachable

- product effects: `relay:simpleExecute`, `relay:simpleReadReply`,
  `relay:orchestrationExecute`, `relay:newChatExecute`,
  `relay:renameConversation`;
- recovery/status: `relay:recoverExecution`, `relay:newChatStatus`,
  `relay:probe`, `relay:activityProbe`;
- orchestration-only background callbacks:
  `relay:orchestrationAuthorize`, `relay:orchestrationResult`.

The delivery replacement will reuse the existing exact-turn DOM functions.
It will not create a second content-script implementation.

## State and receipt inventory

### BCT SQLite

The source schema adds one replacement table, `relay_deliveries`. It is now
present in the LIVE Core after the accepted Core deployment. The LIVE database
also contains the general audit tables `operations`,
`resource_claims`, `operation_effect_stages` and `operation_steps`, plus:

- project directory/run: `conversation_network_projects`,
  `conversation_network_memberships`, `persistent_project_runs`;
- orchestration identity: `orchestration_sessions`,
  `orchestration_session_nodes`, `orchestration_manager_epochs`,
  `orchestration_attachments`, `orchestration_rcc_instance_sessions`;
- work/result flow: `orchestration_assignments`,
  `orchestration_assignment_attempts`, `orchestration_dependencies`,
  `orchestration_mailbox`;
- wake/decision flow: `orchestration_manager_wakes`,
  `orchestration_consumption_receipts`,
  `orchestration_consumption_decisions`, `orchestration_durable_wakes`,
  `orchestration_durable_wake_attempts`;
- lease/recovery/dispatch: `orchestration_durable_leases`,
  `orchestration_durable_lease_revocations`,
  `orchestration_manager_recovery_leases`,
  `orchestration_dispatch_outbox`, `orchestration_dispatch_attempts`,
  `orchestration_reconciliations`.

Read-only snapshot on 2026-10-22: 20 orchestration sessions (11 ACTIVE), 28
assignments (11 NOT_APPLIED, 9 APPLIED, 7 UNKNOWN, 1 FAILED), one acknowledged
dispatch-outbox row, six Manager-wake rows, and 25 unresolved exact-resource
Claims. These historical rows are evidence and are not modified by this work.

### RCC extension local storage

Current keys are `settings`, `registrations`, `pending`, `results`, `processed`,
`operations`, `relayResultReceiptsV1`, `renameReceiptsV1`,
`bindingSubmitLeasesV1`, `simpleRelayV0Binding`, `simpleRelayV0Receipts` and
`newChatReceiptsV1`. The replacement adds one bounded mirror,
`deliveryLedgerMirrorV1`; it is now present in the installed RCC and contains
the two accepted LIVE delivery rows.

### Page/extension session state

- endpoint session: `rccEndpointSessionIdV1`;
- exact active page effect: `relayActiveExecutionV1`;
- retired deferred queue: `relayDeferredQueueV1`;
- page telemetry: `dwActTelemetryV1`.

The endpoint session and tab/window IDs are reconnect metadata. They are not a
second delivery identity and must not permanently block a delivery after a
normal same-ID reload.

## Keep, integrate, retire

### Keep

- Named-pipe process/session/SID/DACL authentication;
- exact RCC instance selection at transport time;
- exact conversation UUID and unique-open-tab resolution;
- content-script sender validation, empty-composer check, exact submitted user
  turn verification and exact new assistant reply selection;
- the Conversation Network as the user-facing project/address book;
- BCT's generic operation audit, but only as an outer audit record rather than
  another relay state machine;
- read-only diagnostics, rename, new-chat and maintenance as separate products.

### Integrate

- Simple Relay send/return and orchestration `send` into one delivery ledger;
- Manager and Worker role bindings into two explicit conversation UUID fields
  on that delivery; no global role registry is required for the thin path;
- RCC `pending`, `relayResultReceiptsV1` and `simpleRelayV0Receipts` into one
  bounded RCC mirror keyed by the same `delivery_id`;
- `relay:simpleExecute`, `relay:simpleReadReply` and
  `relay:orchestrationExecute` onto the existing exact-turn DOM adapter.

### Retire only after the thin roundtrip is accepted

- Project Run's relay dependence on `conversation-bind`, binding receipt,
  attachment generation and relay role;
- orchestration `send` as a second send protocol;
- `simple-relay-bind` and the separate send/return operation IDs;
- Manager-wake, consumption, durable-wake and dispatch recovery loops for this
  Project Run path;
- dead implementations behind already blocked legacy mutation commands;
- legacy RCC keys only after static and LIVE caller counts are zero.

Retirement first means making these paths unreachable and read-only. Historical
tables and receipts are retained until a separate, verified migration proves
that they are no longer required for audit.

## Single delivery state machine

One logical Manager-to-Worker-to-Manager roundtrip owns exactly one
`delivery_id`.

```text
NOT_SENT --worker exact user turn proven--> SENT_WAITING
SENT_WAITING --new exact worker reply stored--> REPLY_CAPTURED
REPLY_CAPTURED --manager exact user turn proven--> RETURNED

NOT_SENT --pre-submit rejection proven--> NOT_APPLIED
SENT_WAITING --exact worker turn failed/interrupted--> FAILED
any nonterminal --effect boundary cannot be proved--> NEEDS_REVIEW
```

Rules:

1. `delivery_id`, Manager UUID, Worker UUID and outbound text hash are immutable.
2. The RCC session, tab ID and window ID may change and are audit observations.
   Every action reacquires the exact UUID and a unique open tab.
3. Duplicate observations are idempotent. A backward or skipped transition is
   rejected.
4. `NOT_APPLIED`, `FAILED`, `NEEDS_REVIEW` and `RETURNED` are terminal for that
   ID. A deliberate retry uses a new `delivery_id`.
5. `NEEDS_REVIEW` never holds a global Claim and never blocks an unrelated
   delivery.
6. There is no receipt-of-a-receipt. BCT stores the authoritative state; RCC
   keeps only the bounded mirror required to prevent a duplicate UI submit
   across extension/page recovery.
7. The Monitor displays this state but does not grant or revoke execution.

## Delivery sequence after this contract passes

1. Persist `NOT_SENT` in BCT.
2. Resolve the Worker UUID to exactly one open ChatGPT tab.
3. Ask the existing DOM adapter to submit once and prove the exact user turn.
4. Persist `SENT_WAITING`; wait/read without resubmitting.
5. Capture the exact new Worker assistant reply and persist `REPLY_CAPTURED`.
6. Resolve the Manager UUID, submit that captured reply once, and prove the
   exact Manager user turn.
7. Persist `RETURNED`.

## Thin-path implementation boundary

The source implementation is intentionally three calls over one logical ID:

- `delivery-start`: creates the authoritative BCT row, resolves both exact
  conversation UUIDs, submits to the Worker once and records `SENT_WAITING`;
- `delivery-status`: reads only the exact Worker turn and records
  `REPLY_CAPTURED`; a reply that is still generating remains pending;
- `delivery-return`: submits the stored reply to the exact Manager tab and
  records `RETURNED`.

Each outer BCT operation uses the exact resource
`rcc-instance:<instance>:delivery:<delivery_id>`. It never reserves the whole
RCC instance. An ambiguous boundary records `NEEDS_REVIEW` and releases that
exact execution Claim; the immutable ledger row is the warning/audit record.
No Project Run, wake, failover, attachment generation or orchestration mailbox
code calls this path yet.

Wake-up, role failover, multiple Workers and autonomous scheduling are forbidden
until this sequence succeeds twice, including one normal reload/disconnection
recovery, without duplicate turns.

## Acceptance gates

- state-machine unit tests pass before transport code is changed;
- one Manager and one Worker, exact UUIDs, one delivery ID;
- two consecutive LIVE roundtrips with no duplicate user turn;
- one reload or temporary pipe disconnect resumes by delivery state and UUID;
- no new global Claim and no dependency on a stable attachment generation;
- only then may wake-up, role transition and multiple Workers be designed;
- legacy callers must reach zero before code/storage retirement.

## RC5 source receipt

The thin path is packaged as `RCC_REBUILD_V2_RC5` at source commit
`1cd3eb1b063786c2ebd8c6e5ee3c2596c2c847fd`.

- extension version: `1.0.28 · Delivery Ledger V1`;
- candidate inventory: 52 files, aggregate
  `10b85114421b7e5ce33da8cc00c027f8b278d7bddf87308de59aac60f326f998`;
- preserved rollback baseline: 51 files, aggregate
  `ff672173ffbf087833da6fe744f2135c9aa8a866666dfcfa20530b61c4105a5f`;
- focused Python/package regression: 45 PASS;
- complete RCC extension JavaScript suite: PASS;
- release-candidate inventory verifier and `git diff --check`: PASS.

## Phase 6 LIVE acceptance receipt

- exact main: `9f35125516cf2f841aeed75ab53a9a5a02cc5a48`;
- main CI: run `39699667585`, all required jobs successful;
- installed RCC: 52 files, aggregate
  `10b85114421b7e5ce33da8cc00c027f8b278d7bddf87308de59aac60f326f998`;
- exact pre-cutover backup: 51 files, aggregate
  `ff672173ffbf087833da6fe744f2135c9aa8a866666dfcfa20530b61c4105a5f`;
- RCC instance remained `6174664e1c1b4e6db1d4729c841db3c9`; deployment reload
  changed the session from `167c955ef5434ea9b235524a33631f4d` to
  `79d06def83014472acac2f33c36a5991`;
- exact Manager: `6ad7f5b6-c834-83e8-9c00-ff70bab4204d`, tab `594834821`;
- exact Worker: `6ad7ff62-fa64-83ee-a485-1138f1538e53`, tab `594834925`;
- delivery `dlv-live-20261022-a` reached `RETURNED`; response length 22 and
  SHA-256 `3e45566c6e014bc02618e1eb58eabdf28e418c6ae5e536a6594388131d771923`
  exactly match `RCC-DLV1-OK-20261022-A`;
- a deliberate recovery reload changed the session to
  `9799625ceafc4dcaa2285b5a073d96fc`; the first delivery replayed as
  `RETURNED` without another submit;
- delivery `dlv-live-20261022-b` then reached `RETURNED`; response length 22
  and SHA-256
  `b128c4f68cfb53c3a1b443f430c05b3201b13bd2430633eeaf97104f8f4bc389`
  exactly match `RCC-DLV1-OK-20261022-B`;
- restarting delivery A with the identical immutable tuple returned the
  existing terminal row with `replayed=true`; no new Worker turn was sent.

Phase 6 is accepted. Wake-up, role failover and multiple Workers may now be
designed on this one ledger. Legacy retirement remains forbidden until their
callers are proven zero and the Phase 7 path is accepted.


## Phase 7A — Manager reply observation (isolated, not LIVE)

The accepted Phase 6 `delivery-return` only proves that the Worker reply was
submitted once to the exact Manager conversation; it does **not** prove that the
Manager produced a new decision. Phase 7A introduces **one read-only command**:
`delivery-manager-status`, keyed by the existing `delivery_id` and original Work.

- A successful `delivery-return` now records the Manager's exact pre-reply
  assistant count in the bounded RCC mirror. No second delivery or wake message
  is sent.
- `delivery-manager-status` reads the **completed response to that exact
  submitted Manager turn** through the existing content DOM adapter. While
  generating, unavailable, or reattaching, the result is pending and no submit
  occurs.
- It returns Manager text and SHA-256/length to the authorized BCT caller.
  The Manager text is **not persisted as a new receipt in RCC storage**; its
  SHA/length are retained only in the existing delivery mirror to detect drift.
- Core verifies the text hash and identity and does **not** change the
  `RETURNED` ledger state. This is observation, not a new state machine.
- Prior Phase 6 deliveries without a Manager baseline cannot be retroactively
  read as a new Manager decision. That is a safe explicit failure rather than
  trying to infer an unbound ChatGPT turn.

Gate: local Python + JavaScript tests, source/manifest compatibility, scoped
CI, exact source deployment and a **fresh** 1:1 Manager response proof before
any automatic Manager decision consumption or next-Worker dispatch.

Phase 7B will validate a structured next-Worker decision against membership
and per-run authority, then create a **new** single delivery id for the next
Worker. No free-form Assistant output is an execution authorization. Legacy
Manager Wake and recovery loops remain outside this thin path.


## RCC maintenance reload — active-effect guard, not ordinary chat generation

The broad `RCC_RELOAD_CHAT_GENERATING` guard introduced at source commit
`a080df72` blocked a reload whenever any ChatGPT tab was generating. That
mistook an ordinary ChatGPT reply on the caller's own N23 tab for an RCC relay
effect and made in-chat maintenance self-blocking.

The revised guard leaves the exact BCT maintenance operation/Claim in place.
A reload is forbidden while an active *nonterminal* RCC operation reserves the
instance or any exact per-delivery/relay resource, and a new exact effect is
forbidden while reload maintenance is reserved. FINISHED UNKNOWN histories
remain records, not perpetual instance locks.

Before the reload side effect, Core reads the exact RCC state/instance/session.
An ordinary generating tab does **not** veto the reload. But a generating Worker
whose exact delivery is `SENT_WAITING`, or a generating Manager whose exact
delivery is `REPLY_CAPTURED`, is an ongoing relay and vetoes the reload.
Only the authoritative `relay_deliveries` rows for this instance provide that
identity; generic Monitor telemetry is not execution authority.

This is a bounded, testable relaxation, not a bypass of tool safety checks,
per-Work authorizations, exact URI matching, state transitions or the
maintenance reservation. The accepted Phase 6 ledger history and the rollback
payload remain unchanged. Tests cover ordinary generation, both active reply
roles, terminal delivery, and races between exact delivery claims and reload.

## Phase 7A original-effect no-resend inspection

The `delivery-recovery-inspect` command is read-only. It reads the exact
original `NEEDS_REVIEW` Delivery mirror, validates Manager/Worker UUIDs,
request SHA-256 and the original relay fingerprint, then probes the Worker
content script's persisted original relay execution record. It requires
matching relay ID, Worker conversation, SHA-256 of submitted text, an exact
unique user turn and a completed non-interrupted assistant reply. The Core
validates reply hash/length, original turn key and receipt identity. The
new BCT Operation receipt stores independent inspection evidence; neither
this command nor its JS handler submits a message, changes original
`relay_deliveries`, or authorizes `delivery-return` of the original UNKNOWN.
Any missing/tampered proof fails closed. A later, separately reviewed
reconciliation/return protocol is needed before a Manager message is sent.
