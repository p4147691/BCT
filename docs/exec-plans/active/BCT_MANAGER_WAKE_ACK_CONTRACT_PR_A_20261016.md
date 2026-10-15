# BCT Manager Wake ACK contract — PR A

Status: PR A implementation candidate. **Not merged, not deployed, and not an end-to-end acceptance.**

## Purpose and boundary

PR A separates three facts that were previously collapsed in the live manager-wake path:

1. RCC accepted and submitted the wake text (`host:ack`, `submitted=true`).
2. A holder of the exact one-time consume capability reached the BCT persistence boundary.
3. A current Manager atomically consumed the RESULT, committed one decision, and created follow-up outbox intent.

Only the first fact is produced by the existing RCC call. PR A adds the persistence primitive needed to prove the second fact during PR B. It does not implement the third fact, add a public MCP consume operation, create assignments/outbox rows, or claim a complete browser E2E.

The existing `orchestration_manager_wakes.acknowledged_at` values and Issue #111 receipts retain their historical bytes and historical meaning. They are not changed, reinterpreted as new Manager-consumption proof, or backfilled. New `host:ack + submitted=true` transitions write `DELIVERED` and `delivered_at` only.

## Additive persistence contract

`orchestration_manager_wake_capabilities` is empty on upgrade and has no startup backfill. One row is keyed by the existing canonical manager-wake `event_id` and binds:

- exact `session_id` and `manager_epoch`;
- exact `attachment_id` and `attachment_generation`;
- an immutable wake-envelope schema version (schema 2 for new rows);
- a high-entropy bearer token plus its digest;
- lifecycle `ISSUED -> SPENT` or `ISSUED -> REVOKED`;
- the future deterministic `decision_id` for which it was spent.

The token and immutable envelope schema are created in the same SQLite transaction that first creates a new `PENDING` wake, before its first delivery claim. A confirmed non-submit retry reuses the same token, schema and deterministic delivery identity so the immutable RCC request does not change. A capability-less historical `PENDING` wake is never backfilled: its retry reproduces the byte-exact schema-1 wake envelope already associated with its deterministic RCC request ID. Such a legacy wake cannot prove Manager consumption through this PR-A boundary; PR B must require a new current-epoch event or a separately audited migration rather than silently upgrading it. A future renderer must add a new persisted schema value rather than changing schema-2 bytes in place. `DELIVERED` means only submit confirmation. A post-send `UNKNOWN` is never retransmitted; if the original Manager actually received the wake, that exact token remains eligible for PR B. Manager takeover atomically revokes all still-issued capabilities from the prior epoch before any successor wake is created. Attachment staleness also revokes the event's still-issued capability in the same transaction.

The raw token is persisted only because an exact confirmed-non-submit retry must reproduce the identical wake payload. It is never returned in operation output, snapshot, event data, or ordinary receipt evidence. This makes the SQLite file and its backups a credential-bearing boundary that requires independent ACL, backup, redaction, and log review before deployment.

## Transaction-only PR B interface

PR A exposes no new MCP operation. Its sole handoff is:

```python
OrchestrationService.spend_manager_wake_consume_capability(
    db,
    *,
    work,
    session_id,
    event_id,
    manager_epoch,
    attachment_id,
    attachment_generation,
    consume_capability,
    decision_id,
)
```

The caller must already hold the single SQLite write transaction. The method revalidates current Work ownership, session epoch, canonical wake, live exact manager attachment and token, then performs one conditional `ISSUED -> SPENT` update. Reuse, including reuse for the same `decision_id`, stale epoch, takeover, wrong attachment, wrong generation and wrong token fail closed. A rollback leaves the capability unspent. PR B must therefore check for and return an already committed deterministic decision before attempting to spend the token; after a commit/response-loss replay it must not invoke this primitive a second time. That replay ordering and a response-loss test are mandatory PR-B gates.

Spending the capability alone is deliberately **not** Manager ACK evidence. It does not update manager-wake `acknowledged_at`, legacy mailbox `consumed_at`, PR1 consumption receipts, a decision, assignment, or outbox.

## Threat model and known limitation

- Capability possession under the common MCP principal proves possession of the delivered bearer value; it does not independently authenticate a particular Manager browser tab.
- A token exposed through the chat DOM, extension, process memory, SQLite file, backup, screenshot, log, or compromised same-principal caller can be stolen and raced.
- Exact event/epoch/attachment/generation fences prevent a token from being redirected to a different durable identity, but they do not prove the human/model identity behind the tab.
- Takeover revokes the old epoch atomically, but a capability legitimately spent before takeover remains historical evidence and must be reconciled by the PR B decision transaction.
- A wrong recipient that obtains the exact token before takeover is within this bearer-token limitation. Independent tab authentication or a browser-held signing key is a separate security boundary and is not claimed here.
- Tokens have no wall-clock expiry in PR A. Database ACLs, backups and logs must be treated as credential-bearing, and expiry or caller-bound proof must be resolved before exposing the PR-B operation beyond the current internal boundary.

These limitations require independent security review before merge and again before exposing the PR B MCP operation.

## PR B exact responsibility

PR B must use one SQLite write transaction to:

1. verify/acquire the current lease and current Manager epoch;
2. validate the exact source RESULT and current consumer assignment;
3. derive deterministic `decision_id`, request digest, follow-up assignment IDs and delivery IDs from the immutable request;
4. return the exact already-committed decision before spending on an identical replay; otherwise spend the PR A capability through the transaction-only interface;
5. commit PR1 consumption receipts and the decision;
6. create the follow-up assignment attempt and PR2 outbox intent;
7. commit all of the above together or none of it.

The current PR1 helper opens its own transaction, so PR B must extract or add a transaction-aware inner helper rather than nesting transactions. It must retain exact replay idempotency, lease/epoch fencing, and the PR2 rule that a send with an unknown external effect is never automatically resent. Only a committed transaction containing capability spend plus consumption decision/receipts may become Manager consumption evidence. Browser submission, capability issuance, or capability spend in isolation must not become `ACKNOWLEDGED` or full E2E PASS.

## Protected state

This PR must not modify RCC, Browser Bridge, LIVE, Chrome, HKCU, Issue #111 rows, historical UNKNOWN/Claim records, or legacy mailbox `consumed_at`. The shared source checkout and the PR3-o uncommitted worktree remain outside this worktree.
