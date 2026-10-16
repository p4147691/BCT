# BCT Manager Wake receipt contract — PR A

Status: PR A implementation candidate. **Not merged, not deployed, and not an end-to-end acceptance.**

## Purpose and boundary

PR A separates three facts:

1. RCC accepted and submitted the Manager wake (`host:ack`, `submitted=true`).
2. RCC later persisted the Manager response as an exact `RESULT_PERSISTED` receipt.
3. BCT atomically consumed that receipt, committed one decision and created any follow-up outbox intent.

Only the first fact is completed by PR A. Submission writes `DELIVERED` and
`delivered_at`; it never writes or reinterprets Manager-consumption evidence.
PR B owns facts 2 and 3.

The abandoned bearer capability, HTTP event, Challenge and MCP caller-identity
designs are not part of this contract. No secret is placed in a ChatGPT message,
RCC fingerprint, SQLite row or MCP response.

## Versioned wake contract

`orchestration_manager_wakes` gains two additive columns:

- `envelope_schema`, default `1` for every pre-existing row;
- `receipt_mode`, default `LEGACY_RETURN_V1` for every pre-existing row.

New rows are created with `envelope_schema=2` and
`receipt_mode=RCC_RESULT_POLL_V1`. The schema-2 envelope contains only exact
event, session, Manager epoch, attachment generation, assignment generation and
RESULT identity. Its RCC `returnToRole` is empty, so RCC persists the Manager
response but does not send a second Manager message. `returnOnAck` remains true
only so BCT can distinguish confirmed submission from an unknown external
effect.

Schema 1 retains its existing bytes, deterministic relay ID, fingerprint and
return role. Unknown schema/mode pairs fail closed. Existing Issue #111 rows,
historical `acknowledged_at`, mailbox `consumed_at`, UNKNOWN effects and Claims
are neither backfilled nor reinterpreted. A post-send `UNKNOWN` is never resent.

Wake claim re-reads the current SQLite Work owner and assignment epoch, current
Manager epoch and exact active attachment. Completion re-reads the current Work
owner/epoch, Manager epoch, versioned wake contract and exact claimed delivery.
A stale caller-owned Work object, takeover or attachment rotation cannot
authorize a new dispatch, and handoff cannot let a stale caller finalize it.

## RCC resultHash contract

RCC hashes the UTF-8 bytes of `JSON.stringify(boundedRelayResultPayload(result))`.
Property order is part of the contract:

1. `failureEvidence` (`phase`, `networkError`, `domError`, `networkSignal`) or null;
2. `ok`;
3. `reply`;
4. `error`;
5. `ambiguous`.

Python must not use sorted keys. The shared fixture
`modules/rcc/extension/fixtures/result_hash_v1.json` is executed by both the
production JavaScript helper and the Python recomputation helper. Unsupported
types and oversized replies fail closed.

The PR-B decision parser must accept one bounded
`BCT_ORCHESTRATION_MANAGER_DECISION_V1` object only. It must bind schema,
event/session/Manager epoch, source result message/digest and a decision kind of
either `COMPLETE` or `FOLLOW_UP`. `FOLLOW_UP` carries a bounded list of successor
assignment specifications; `COMPLETE` carries none. Missing, duplicate,
conflicting or additional authority-bearing fields fail closed. This response
schema is not an authorization token: authority still comes from current
Work/Policy/epoch/lease/attachment checks at commit time.

## PR B internal poll contract

PR B may add one bounded recovery loop inside the existing BCT runtime. It must
not add an HTTP receiver, signing key, authentication server or public Manager
consume MCP operation.

The implementation must satisfy all of the following:

1. **Single ownership and restart lease.** At most one active poll owner may
   schedule reads. Poll ownership is operational only; the authoritative commit
   is still fenced by the current durable Manager epoch/lease. A restart may
   resume an unexpired exact lease or acquire an explicitly defined recovery
   lease, but may not silently revive an expired or revoked Manager lease.
2. **Bounded scope.** Select only schema-2 `RCC_RESULT_POLL_V1` wakes in a
   bounded batch. A missing result, RCC outage or delayed receipt causes backoff
   without changing Wake state or resending the wake. Schema-1 rows are excluded.
3. **Authoritative source.** Obtain decision text only from the exact RCC
   `RESULT_PERSISTED` receipt. Caller-supplied decision text, tab ID or
   conversation ID is not authoritative.
4. **Receipt verification.** Recompute `resultHash` using the versioned contract
   and compare relay ID, message/result digest, binding receipt, instance,
   external session, tab, conversation and attachment generation with the
   persisted Wake.
5. **Current fencing.** Before committing, re-read Work owner/state/assignment
   epoch, Policy authorization, Manager epoch/lease and active exact attachment.
6. **Replay first.** Derive the decision request digest and deterministic IDs,
   then return an exact already-committed decision before attempting new writes.
   A conflicting replay fails closed.
7. **One SQLite transaction.** Any successor assignment, consumption receipt,
   decision and immutable outbox rows commit together or not at all. A valid
   terminal decision with no successor creates no assignment or outbox and is
   still a successful atomic decision.
8. **Commit before ACK.** Call RCC `result-ack` only after SQLite commit. Lost
   ACK responses retry the same relay ID/resultHash ACK; they never recompute the
   decision or enqueue another outbox item.
9. **UNKNOWN discipline.** Polling may read an existing UNKNOWN wake's exact RCC
   result, but it never resets or retransmits the wake. External-effect UNKNOWN
   outbox attempts retain the existing no-auto-resend rule.
10. **Named Pipe security gate.** Before deployment, verify that the installed
    pipe is restricted to the intended Windows user/service identity or add an
    explicit ACL. Exact logical instance validation alone is not an OS access
    control proof.

## Non-goals and protected state

PR A does not implement the poller, dispatcher, decision parser, successor
assignment transaction or `result-ack` recovery. It does not install/reload RCC,
operate Chrome, change LIVE/HKCU, merge the PR, restart services or touch PR3-o,
Issue #111, UNKNOWN/Claim records or existing `consumed_at` values.
