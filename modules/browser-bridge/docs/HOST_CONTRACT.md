# Browser Bridge host security and orchestration boundary

## Native launcher preflight

The standalone bridge launcher is **not** RCC. The signed or otherwise separately approved bridge-owned staging process must set these variables **before** launching Chrome's Native Messaging integration:

- `BCT_BRIDGE_PYTHON_EXE`: an existing, absolute, canonical Windows `.exe` path to a separately approved Python runtime. PATH resolution, relative paths, and implicit `python` are forbidden. Approval must bind the absolute path and executable SHA-256 to the test manifest/receipt; the launcher enforces runtime file SHA-256 as well as path shape and existence.
- `BCT_BRIDGE_PYTHON_SHA256`: mandatory 64-character SHA-256 of the approved runtime file; launcher computes file hash and fails closed on mismatch.
- `BCT_BRIDGE_EXTENSION_ORIGIN`: exactly `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/`. Both C# and Python require ordinal equality.
- `BCT_BRIDGE_MCP_URL`: isolated HTTP loopback `/mcp` URL, never port 18790.
- `BCT_BRIDGE_TOKEN_PATH` and `BCT_BRIDGE_WORK_ID`: isolated test-only credentials and least-privilege work.

The configured runtime and host script are separate assets. Never use the user's general Python installation without explicit executable approval. No host registration, Chrome installation, tokens, or Core resources are created by this package.

## Error and receipt contract

| Case | Outcome | May retry same operation? |
|---|---|---|
| Input shape or capability rejected locally | INPUT_DENIED | No dispatch occurred; correct input and use a **new** operation |
| Missing/rotated host authorization | AUTH_DENIED | No automatic resend |
| Runtime path invalid or host cannot start | Process exit 5 / no dispatch | Resolve configuration, no implicit retry |
| Host connection/initialization failed before Core call | CONNECTION_FAILED | No automatic resend |
| Core returns an error receipt | RECEIPT_ERROR, preserve original payload | Do not infer success or resend |
| Core reports UNKNOWN / FAILED / BLOCKED / DENIED | Preserve Core outcome and receipt | Consult Core receipt; no automatic resend |
| Transport fails during Core tool invocation | UNKNOWN, DISPATCH_RESULT_AMBIGUOUS_NO_RETRY | **Never** retry original operation |

Receipt lookup is read-only. Failed receipt lookup must not be interpreted as lack of an earlier effect. A timeout after dispatch is ambiguous even if no response was received. The request ID must remain associated with the exact operation/receipt.

## Durable orchestration boundary (PR2/PR3)

This PR does not implement completion observation or message delivery. Proposed **future** APIs (not implemented): `bridge_completion_report`, `bridge_result_get`, `bridge_delivery_request`, `bridge_delivery_receipt_get`. Completion events must bind session, assignment, generation, node, result digest and unique event ID; retrieval must not consume a result. Targeted delivery must fence target identity and connection generation and distinguish accepted / sent / ACK / UNKNOWN receipts.

PR1 owns atomic result-consumption and manager decision, PR2 owns durable orchestration/wake/outbox contracts, and PR3 will own authorized browser completion/delivery integration once separately approved. No SQLite consumption logic, manager epochs, RCC internals or browser DOM control are added here.

## Test boundary

The Python subprocess tests exercise framed Host input/output, authorization denial, origin rejection, and receipt mapping without Chrome, Core or token creation. C# source-contract checks inspect the launcher code. **C# executable integration (launcher → Python framing) has not been demonstrated** on a machine without the .NET SDK; do not claim real-launcher E2E PASS until a separately approved controlled SDK/build environment can compile and run the launcher, followed by tests using an approved absolute Python executable. No SDK downloads are authorized by this task.
