# BCT RCC delivery ledger V1

Status: `CHANGE_FREEZE / READ_ONLY_AUDIT_COMPLETE / STATE_MACHINE_CONTRACT_LOCKED / THIN_PATH_NOT_IMPLEMENTED`

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

Current development candidate `f573961d8d10ea6cd44b123022d388f91746c848`,
the installed RCC payload, the LIVE Core, Chrome and existing conversations are
frozen during this reset. No reload, deploy or message send belongs to phases
1-5.

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
| new relay | `simple-relay-bind`, `simple-relay-send`, `simple-relay-return`, `new-chat-send` | keep new-chat separate; integrate the three Simple Relay commands |
| conversation | `rename-conversation`, `conversation-bind` | keep rename; retire persisted relay binding after replacement acceptance |
| orchestration | `send` | replace with the single delivery contract |
| read-only | `ping`, `state`, `result`, `rename-receipt`, `probe`, `probe-tabs`, `diagnose-activity`, `diagnose-composer`, `diagnose-conversation-ui`, `api-probe`, `main-capture-get` | keep; consolidate diagnostics later without blocking delivery |
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

The LIVE database currently contains the general audit tables `operations`,
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
`newChatReceiptsV1`.

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
