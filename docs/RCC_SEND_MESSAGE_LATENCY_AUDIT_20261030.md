# BCT send-message latency audit — 2026-10-30

## Scope and safety
- Existing Work: `BCT-SEND-MESSAGE-LATENCY-OPT-20261030-01`
- Branch: `feat/send-message-latency-opt-20261030`
- One canonical `send-message` public route. No added message retry, browser mutation, or weakening of exact-target/receipt guards.
- Passive, bounded numerical evidence only; message content, conversation UUID, and user text are excluded from latency fields.
- Previously ambiguous mutation receipts and historical Claims are preserved, not promoted to performance gates.

## Instrumentation
`src/bct/features/rcc_latency.py` normalizes only observed nonnegative bounded millisecond values. `rcc.py` records:
1. `preflight_state`: the existing required RCC state read, immediately before reserving the send Operation.
2. `host_request`: measured Native Host request duration. For existing-tab `send-to-tab`, this is also `submit_ack` wait because the host returns a submission ACK, not a final model reply.
3. `readback` and `readback_attempts`: only when a created-tab submission enters the existing `SUBMIT_UNKNOWN` terminal-result recovery branch and a terminal receipt is proven.
4. `submit_to_conversation` / `conversation_to_response`: elapsed intervals already supplied by the RCC created-tab result's own `stageTiming`; clock subtraction is only inside that host's timestamp domain.

An exact submission-ACK timestamp for `send-to-created-tab` is **not** provided by the existing RCC contract, so this measurement is intentionally absent rather than fabricated. `host_request` for created tabs is **not** incorrectly labelled ACK time.

## Previous real E2E host observations
Historical successfully persisted created-tab/window receipts showed these intervals (ms):

| Receipt | submit → conversation | conversation → response | Observed host phase total |
| --- | ---: | ---: | ---: |
| PR #372 new tab | 3262 | 2018 | 5280 |
| Follow-up new tab | 3507 | 1140 | 4647 |
| PR #373 new window | 2702 | 2577 | 5279 |

The observations identify the **conversation-creation and response path**, not a proven avoidable Core state read or ACK overhead. They cannot distinguish model generation, page navigation, and fixed polling from one another. Thus no polling interval, security validation or transport retry is changed without separate proof.

## Acceptance
- Existing RCC integration regression: 77/77 PASS.
- New latency and duplicate/idempotency tests: 5/5 PASS.
- Additional MCP/source-baseline regression: 15/15 PASS.
- No extra state read or message dispatch is introduced.
- Explicit runtime deployment manifest includes the new `rcc_latency.py` module.

## Optimization decision
Instrumentation accepted; **no unproven latency reduction claimed**. Review read-only live measurements after deployment. If one avoidable stage consistently dominates, optimize only that stage under a new isolated regression and physical acceptance.
