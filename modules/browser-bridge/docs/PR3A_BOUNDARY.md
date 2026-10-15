# Browser Bridge PR3-a — isolated durable boundary

Base: canonical main `1b9f3e4d06846d41960509e610eac484017d9c9f`.

## Scope and source of truth

This patch adds **internal Python adapter functions**, not an externally exposed MCP/Chrome endpoint. Invocation is permitted only by a future explicitly authorized Core capability with verified caller identity and work scope; this change does **not** permit arbitrary web pages or native hosts to invoke it. PR1 owns atomic consumption receipts/manager decisions; PR2 owns authoritative wake, manager epoch lease, immutable outbox reservation, attempt state, and delivery ACK. The adapter calls PR2; it does not reproduce those stores or change legacy `consumed_at`.

The additive `browser_bridge_completion` table must be provisioned explicitly by `install_bridge_schema`; this patch does not auto-migrate a live database. Only a **pre-existing Core-validated** mailbox RESULT with an assignment attempt and matching source/generation/digest can be registered as an idempotent completion event; a browser assertion does not create a RESULT or supersede Core result authority.

## API/adapter contracts

- `completion_report`: requires unique event ID plus session, assignment, generation, source node, result message ID, digest; checks persisted Core provenance. Same ID+same payload -> duplicate; conflicting ID -> rejection. Registration does not wake manager itself; PR2 `create_wake` owns durable Wake.
- `result_get`: read-only, event-scoped immutable mailbox body with digest check; does not consume RESULT. A future caller-facing API must additionally enforce principal/session authorization.
- `delivery_request`: read-only exact identity check against **PR2-created** immutable outbox; verifies session/target node/attachment generation/assignment generation; never constructs or rewrites outbox or sends.
- `delivery_receipt_get`: read-only PR2 recovery projection for a session/delivery; a future endpoint must enforce principal/session authorization. Status PENDING/RESERVED/DISPATCHING/DELIVERED/UNKNOWN/ACKNOWLEDGED cannot be conflated.
- `fake_send`: deterministic non-Chrome transport. Calls PR2 reserve/attempt; confirmed pre-send abort returns to PENDING. After SEND_STARTED, no proof of delivery -> UNKNOWN and **no automatic retry**. A confirmed transport send means SENT, **not recipient ACK**.
- `recipient_ack`: receiver command ID is **SHA-256 of** `delivery_id + ':' + SHA256(canonical PR2 payload_json)`. Exact target node, attachment ID+generation and payload are checked before calling PR2 fenced, idempotent `acknowledge_delivery`; duplicate command with same ACK digest returns duplicate, different digest conflicts. No separate command table or second ACK state machine.

Idempotency keys: `event_id` (completion), existing PR1 `decision_id` and consumer assignment, PR2 immutable `delivery_id`, deterministic `command_id`, PR2 `ack_digest`. Source provenance is the existing Core mailbox message/assignment attempt; target provenance is PR2 outbox and attachment/assignment generations. Epoch and lease token are checked by PR2. The adapter accepts no arbitrary browser-originated credential on its own.

## What fake E2E proves / does not prove

Fixture-only SQLite verifies completion duplicate/conflict, result retrieval after reopening Store, PR2 Wake reservation, atomic consumer decision+outbox, exact target, pre-send abort, uncertain post-send, no-auto-retry, stale epoch/token and recipient ACK idempotency. No real Chrome/DOM/extension/native host, no real network delivery, no production registration/token/Core or LIVE DB access occurs. A separate later PR is required to expose capability-specific authenticated Core tools, bind browser node identity and Origin to an authorized session/work, verify DOM completion authenticity, implement a recipient with persisted ACK evidence and handle user Chrome E2E. CI PASS is not proof of real Chrome delivery.
