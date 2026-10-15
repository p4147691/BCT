# Durable Manager Recovery — PR 1 receipt / event / consumer contract

Status: PR 1 boundary contract (schema/API + isolated tests only). This is **not** an active browser delivery, manager wake, scheduling, or live migration implementation.

## End-to-end target (future PRs)

A worker running as an ordinary ChatGPT browser tab completes an assignment. Its result must be durably accepted exactly once at the server ingress boundary, without depending on the chat manager's context. The server makes a manager-wake event recoverably available; a current-epoch manager loads the persisted result, atomically commits *that consumer assignment's* consumption receipts plus one decision, and only then enqueues follow-up instructions via a separately receipted dispatch outbox. Manager replacement must be able to resume after a crash without reapplying an old decision. Wake delivery is **at least once**, not an exactly-once browser action.

## PR 1: implemented, immutable data boundaries

- **Result source:** existing `orchestration_mailbox` RESULT row keyed by `message_id`, scoped to `session_id`, carrying `message_digest`. Before consumption, PR 1 verifies the source assignment belongs to the same session, the exact generation and attempt exist and are current/terminal, the sender matches that attempt's worker, and the parsed payload matches both the assignment's terminal result and the stored digest using the existing orchestration canonical `_digest` helper. Missing/mismatched provenance or late results fail closed. Source assignment is deliberately **not** required to equal the consumer assignment. PR 1 does not create, deliver, ACK, retry or mutate this row. `consumed_at` retains its legacy meaning and is neither rewritten nor backfilled.
- **Consumer identity:** `(session_id, consumer_assignment_id)`, with the consumer assignment required to belong to the same session. Different consumer assignments may independently consume the *same* RESULT.
- **Consumption receipt identity:** `(session_id, consumer_assignment_id, result_message_id)`. Its `result_digest`, `manager_epoch` and `decision_id` are immutable. One consumer cannot silently switch that RESULT to another decision.
- **Decision identity:** globally unique `decision_id` plus immutable `request_digest`, canonical `decision_json`, consumer identity and `manager_epoch`. Here `request_digest` is an opaque caller-supplied **consumer-decision idempotency key**, not proof of the Worker's original request or dispatch payload. PR 1 checks its stable replay value but does not authenticate its origin; PR 2 must bind it to the authorized dispatch/consumer assignment. The decision is *persisted intent*, **not evidence that a browser message or next assignment has been delivered**.
- **Atomic API:** `commit_consumption_decision(store, *, session_id, consumer_assignment_id, manager_epoch, decision_id, request_digest, decision, results)` in `bct.core.consumption`. `results` contains nonempty, unique `(result_message_id, digest)` pairs. The API validates every result against the stored RESULT and the current session epoch, then inserts decision and every receipt in **one SQLite transaction**. Any conflict, stale epoch, bad digest or SQL failure rolls back the entire call; no partial receipt/decision is exposed.
- **Replay contract:** exact same decision ID, digest, canonical JSON and exact result set returns `idempotent=True` without new writes. Reusing the decision ID with a changed request/payload/epoch, changing a RESULT digest, or reassigning a consumed RESULT to another decision produces a conflict. Result-set order does not change the decision. A distinct consumer assignment can commit its own decision for the same result.
- **Fencing:** `manager_epoch` must equal the current `orchestration_sessions.manager_epoch` at commit time while the write lock is held. A deposed manager may read data, but cannot commit fresh consumption at its old epoch.
- **Backfill:** new tables are created empty. Existing mailbox rows, including Issue #111-like history, are **never** interpreted as automatically committed by startup, migration, or PR 1.

## Future event and transport adapter — specified, NOT implemented

The browser-facing ingress should hand in a stable `session_id`, worker `assignment_id` and generation, result `message_id`, digest and immutable result payload. It must return a persisted-result receipt with the canonical message ID/digest; a Chrome DOM observation or successful send action alone cannot be treated as a durable RESULT.

After persistence, an independent durable wake/outbox producer should generate a wake record keyed to `(session_id, manager_epoch, assignment_id, generation, result_message_id)` with `result_digest`. Its states should explicitly distinguish **PENDING**, **DELIVERED**, and **ACKNOWLEDGED**. A transient Chrome/RCC failure must keep a recoverable wake, not fabricate a consumption receipt. Existing manager-wake tables and browser transports are out of scope for PR 1 and are **not modified**.

A manager consumer must verify the stored digest, claim current epoch, compute a deterministic `decision_id` and `request_digest`, and call the atomic API. Only after successful commit may a future dispatch adapter look up that durable decision and prepare the next assignment in a separate idempotent, receipted outbox. A commit is not proof of dispatch; a dispatch ACK is not proof of next worker completion. If a crash occurs after decision commit but before dispatch, replay must re-read that decision rather than re-consume with a different ID.

## Integration invariants / failure matrix

| Failure or repeat | Durable outcome / future adapter responsibility |
|---|---|
| Browser completes but transport unavailable | No accepted RESULT until persisted ingress receipt; retry with stable identity, avoid duplicate payload |
| Result persisted; wake delivery fails | RESULT remains; wake stays recoverable/pending |
| Wake delivered twice | Same consumer/digest/decision replays as idempotent; do not interpret wake count as consumption count |
| Old manager races replacement | Atomic API rejects stale epoch; successor must form a new current-epoch decision according to orchestration rules |
| Multi-result batch has missing/mismatched digest | Neither decision nor any receipt commits |
| Process dies inside SQLite transaction | SQLite rolls back decision and receipt together |
| Process dies after decision commit, before next dispatch | Durable decision available; future outbox resumes exact next command |
| Existing legacy RESULT with consumed_at NULL | No auto-created receipt/decision; requires explicit future assignment-scoped call |

## Implementation separation

PR 1 **owns only** additive receipt/decision tables, the atomic API, and isolated tests. It does **not** alter orchestration chains, `orchestration_manager_wakes`, Chrome extension, Native Host, RCC, the LIVE DB, Issue #111, UNKNOWN or Claims. No browser automation, runtime side effect, wake retry, external dispatch, schema backfill, or merge/deploy is authorized here.

A follow-up PR must separately design durable wake scheduling + outbox/dispatch idempotency, manager recovery rehydration, and an end-to-end acceptance test covering browser RESULT → durable ingress receipt → wake → atomic consumption → follow-up instruction. None of these later steps may infer success from PR 1's receipt alone.
