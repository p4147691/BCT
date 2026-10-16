# BCT Durable Orchestration — PR B

Status: implementation candidate. Draft only; not merged, deployed or enabled.

## Boundary

PR B connects the PR A receipt-only Manager Wake contract to the existing PR1
consumption receipt and PR2 lease/outbox contracts. BCT Core remains the only
authority. RCC supplies one exact `RESULT_PERSISTED` receipt; it does not own
assignments, decisions, retries or orchestration state.

Schema 2 remains disabled by default. When disabled, no recovery thread is
started and every new Wake retains schema 1 behavior. Enabling schema 2 in an
installed runtime remains prohibited until isolated E2E and the Named Pipe ACL
gate are separately approved.

## Decision contract

The Manager response is exactly one JSON object between
`[BCT_ORCHESTRATION_MANAGER_DECISION_V1]` and its matching closing marker.
No non-whitespace content is allowed outside the markers. The only top-level
fields are:

- `schema`: exact string `BCT_ORCHESTRATION_MANAGER_DECISION_V1`;
- `event_id`, `session_id`, `manager_epoch`, `result_message_id`,
  `result_digest`: exact Wake bindings;
- `kind`: `COMPLETE` or `FOLLOW_UP`;
- `summary`: non-empty, at most 2,000 characters;
- `successors`: empty for `COMPLETE`, or 1–8 entries for `FOLLOW_UP`.

Each successor has exactly `target_node_id`, `attachment_id`, `instruction`,
`roots`, `actions`, `acceptance` and `dependencies`. IDs, collection sizes,
instruction size, acceptance size, roots and actions are bounded and validated
fail-closed. Duplicate JSON keys, non-finite numbers and type substitutions are
rejected. The response never carries authority. Exact current Work owner and
assignment epoch, session scope, Manager epoch, durable lease and Manager and
worker attachments are re-read at commit time. Successor actions are also
rechecked against the current BCT Policy; a prior session's action scope cannot
override a later policy restriction.

The RCC `resultHash` is not embedded in the response because that would create
a circular hash. BCT recomputes it over RCC's ordered bounded payload and binds
it out-of-band to the exact Wake, deterministic decision ID and persisted Wake
row. The shared decision fixture is
`modules/rcc/extension/fixtures/manager_decision_v1.json`; the existing shared
result-hash fixture continues to verify JS/Python byte equality.

## Atomic commit and recovery

`ManagerDecisionConsumer.consume_receipt` is the single Core boundary for both
poll recovery and a future trusted event trigger. The separate
`manager_decision_recovery.py` adapter verifies the trigger's current lease and
then calls that boundary. Core verifies the exact relay,
Manager attachment, tab, conversation, external session, binding receipt,
attachment generation, worker RESULT digest and RCC hash before entering one
SQLite write transaction.

That transaction revalidates current ownership and lease, creates deterministic
successor assignments, commits the PR1 consumption receipt and decision, creates
the PR2 immutable outbox and records the Wake's decision/result hash. A valid
`COMPLETE` commits with zero successors and zero outbox rows. Exact replay is
idempotent; conflicting replay, takeover, stale Work, attachment rotation or
expired lease fails closed.

The bounded recovery loop reads only schema-2 `RCC_RESULT_POLL_V1` rows in
`DELIVERING`, `DELIVERED` or `UNKNOWN`. It never calls `send` or
`send-wakeback`; UNKNOWN is evidence lookup only. An already-live exact-epoch
lease is renewed only when relevant receipt work is near expiry. A persisted
keyset cursor advances across every bounded candidate, so missing RCC results
cannot permanently hide later completed results and restart resumes the fair
scan. RCC outage or delayed results leave decision and outbox state unchanged.

A separate singleton recovery lease elects one Core poller. Its owner/token is
revalidated inside the same decision transaction, so an expired poller cannot
commit after a replacement starts. After a long Core outage, the replacement
first fences the old poller and may then rotate only an expired durable lease
whose Manager node and epoch still exactly match the current session. The old
token is recorded by digest in the event ledger. A stale Manager epoch is never
revived, which preserves takeover fencing while allowing restart recovery.

After the SQLite commit, BCT sends the deterministic `result-ack`. A lost ACK
response leaves `result_ack_state=PENDING`; restart retries only that ACK. The
same RCC ACK is idempotent. No second decision or outbox row is created.

## Dispatcher follow-up boundary

PR B creates the existing immutable PR2 outbox rows, but it does **not** wire a
runtime Dispatcher that sends those rows to the next Worker. Consequently a
successful FOLLOW_UP in this PR proves durable assignment/decision/outbox
creation only, not successor delivery or an end-to-end autonomous chain.

The follow-up Dispatcher must reserve the existing outbox with the current
Manager epoch and lease, send through the approved transport, preserve the
existing deterministic delivery identity, and record DELIVERED/UNKNOWN and the
recipient ACK through the PR2 state machine. It must never reinterpret or
automatically resend UNKNOWN, and it must not introduce a second scheduler,
decision engine or state ledger.

## Event-first boundary and security gate

`handle_receipt` is the trigger-neutral entry point. Polling calls it now. A
future trusted RCC event may call the same method, but no immediate RCC event
transport is implemented or claimed by this PR. There is no second decision
engine, task manager, HTTP listener, Challenge or authentication server.

Deployment remains blocked until the installed Named Pipe ACL is proven to
restrict access to the intended Windows user/service identity. Logical RCC
instance matching is not an operating-system ACL. The runtime manifest now
includes `rcc_result.py`, `consumption.py`, `durable_pr2.py`,
`manager_decision.py` and `manager_decision_recovery.py`; source-only tests are
not deployment evidence.

## Protected state

PR B does not enable schema 2, merge itself, deploy LIVE, restart a service,
operate Chrome/RCC, resend Issue #111, rewrite UNKNOWN/Claim or historical
`consumed_at`, or modify Browser Bridge PR3-o work.
