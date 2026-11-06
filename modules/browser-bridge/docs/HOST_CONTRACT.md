# Browser Bridge host security and orchestration boundary

## Native launcher preflight

The standalone bridge launcher is **not** RCC. The signed or otherwise separately approved bridge-owned staging process must create a restrictive-ACL `bridge-runtime.json` beside the `launcher` directory. The launcher reads it directly, so an already-running Chrome process does not need to inherit new environment variables. The file contains exactly these fields and rejects unknown fields, malformed JSON, comments, and trailing commas:

- `extension_origin`: exactly `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/`.
- `python_exe`: an existing, absolute, canonical Windows `.exe` path to a separately approved Python runtime.
- `python_sha256`: mandatory 64-character SHA-256 of that runtime file.
- `mcp_url`: an absolute loopback HTTP URL whose path is exactly `/mcp`.
- `token_path`: an absolute, canonical path to the Bridge-owned token file. The token value is never stored in the JSON file.
- `allow_live_core`: JSON boolean. It must be `true` for the LIVE Core boundary.
- `work_id`: optional string; use an empty string when the caller will provide the Work explicitly.

After validation, the launcher passes the resolved values only to its child Native Host process. Environment-variable provisioning remains a CI/test fallback only when `bridge-runtime.json` does not exist:

- `BCT_BRIDGE_PYTHON_EXE`: an existing, absolute, canonical Windows `.exe` path to a separately approved Python runtime. PATH resolution, relative paths, and implicit `python` are forbidden. Approval must bind the absolute path and executable SHA-256 to the test manifest/receipt; the launcher enforces runtime file SHA-256 as well as path shape and existence.
- `BCT_BRIDGE_PYTHON_SHA256`: mandatory 64-character SHA-256 of the approved runtime file; launcher computes file hash and fails closed on mismatch.
- `BCT_BRIDGE_EXTENSION_ORIGIN`: exactly `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/`. Both C# and Python require ordinal equality.
- `BCT_BRIDGE_MCP_URL`: exact HTTP loopback `/mcp` URL. Port 18790 is rejected unless trusted staging explicitly sets `BCT_BRIDGE_ALLOW_LIVE_CORE=1`.
- `BCT_BRIDGE_TOKEN_PATH`: path to the current local BCT MCP bearer, held only by the Native Host with a restrictive ACL. The current Core maps it to `bct-mcp-local`; Work scope, capability policy and operation fences remain the authorization boundary for every generic tool call.
- `BCT_BRIDGE_WORK_ID`: retained for schema-v1 read compatibility only. Generic schema-v2 calls carry the exact arguments required by the registered MCP tool, including Work and Operation IDs where applicable.

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

## Generic BCT tool boundary

Schema v2 supports `tool_list` and `tool_call`. The Host obtains the live MCP tool list on the same authenticated session and rejects names that are not registered. It does not translate a tool call into shell text, broaden Work permissions, invent missing IDs, retry UNKNOWN effects, or treat a transport response as stronger evidence than the Core result.

Ordinary Chat integration is an automatic transport for exact `chatgpt.com/c/<uuid>` conversations. It does not use a per-tab or per-conversation permission gate. Its assistant marker is only a request envelope; it is not authority. The Bridge credential, Core principal, Work, capability policy and operation/resource fences remain authoritative.

## Durable orchestration boundary (PR2/PR3)

The Bridge does not create a second completion or delivery ledger. Chain Message, delayed sends, browser delivery, completion observation and return-to-Manager use the corresponding registered BCT tools and their existing Core ledgers.

PR1 owns atomic result-consumption and manager decision, PR2 owns durable orchestration/wake/outbox contracts, and PR3 will own authorized browser completion/delivery integration once separately approved. No SQLite consumption logic, manager epochs, RCC internals or browser DOM control are added here.

## Test boundary

The Python subprocess tests exercise framed Host input/output, authorization denial, origin rejection, and receipt mapping without Chrome, Core or token creation. C# source-contract checks inspect the launcher code. The Windows GitHub CI builds the real C# launcher and runs launcher → Python Host framing, wrong-Origin, runtime-path, runtime-SHA, strict config-file and auth-denial tests without Chrome, registry, Core or token creation. The local workstation lacks the .NET SDK, so local tests do not independently establish the compiled launcher path. No SDK downloads are authorized by this task. Trusted staging must provision `bridge-runtime.json`, its parent directory and the referenced token with restrictive ACLs. The launcher verifies the configured path and file digest, but those checks alone do not eliminate TOCTOU replacement or guarantee the trustworthiness of staging.

## Core receipt acceptance

Only a structured Core operation receipt with matching operation_id, valid state (RECORDED/RUNNING/FINISHED), known outcome, dictionary evidence and boolean duplicate may be accepted. A finished APPLIED bridge_read additionally requires output.text as a string. A finished APPLIED receipt_lookup returns the full validated receipt. Pending receipts remain PENDING (never success); FAILED, NOT_APPLIED and UNKNOWN retain their Core outcome. Missing IDs, unknown outcome, wrong types, empty data, conflicting terminal state and unexpected shape are RECEIPT_ERROR, not success. Receipt lookup is read-only and never consumes the result.
