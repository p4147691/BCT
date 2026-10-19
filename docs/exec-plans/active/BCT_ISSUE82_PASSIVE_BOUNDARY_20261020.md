# BCT Issue #82 passive pre-tool boundary correlation

Status: `ISOLATED IMPLEMENTATION / NOT LIVE`.

## Goal

Correlate existing RCC browser-generation timestamps with BCT MCP ingress and completion without
recording prompts, response bodies, authentication, or browser content. This narrows repeated
ChatGPT canaries into these observable boundaries:

1. RCC generation start to BCT MCP request ingress.
2. BCT MCP request ingress to response completion.
3. BCT MCP response completion to RCC generation completion.

These spans do not reveal OpenAI-internal context loading, model reasoning, tool selection, or
argument construction. Those remain `UNOBSERVABLE` unless the owning OpenAI host exposes request
usage and trace data.

## Design

- Add `observed_at_unix_ms` to every privacy-safe `MCP_TIMING` event so it can be compared directly
  with existing RCC `generationStartedAt` and `generationFinishedAt` values.
- Emit a `request_ingress` event for authenticated MCP POST requests immediately after bearer
  authentication and trace allocation. Persistent/read-only GET transport requests do not add noise
  to the bounded timing ring.
- Emit `handler_done` for `bct_status` and `bct_capabilities`, which previously exposed only the
  enclosing ASGI completion timing.
- Return the current server-generated opaque trace ID in `bct_status` so the Hosted tool result and
  the local timing stages can be joined exactly rather than by timestamp proximity.
- Preserve the bounded in-memory ring, INFO logging, no-body/no-header/no-token rule, and existing
  trace ID correlation.
- Do not change MCP tool names, descriptions, input schemas, operation semantics, Claims, RCC,
  tunnel, Supervisor, or LIVE configuration.

## Verification order

1. Focused trace tests and Python compilation in this independent worktree.
2. Full local unit suite if the focused checks pass.
3. Existing project VTL Fast validation only if the project-owned scenario covers this server-only
   change; otherwise record it as not applicable rather than dispatching GitHub Actions.
4. One PR and exact-head required CI through the single deployment owner.
5. Only after merge, deploy the exact main SHA and run a small read-only hosted canary set. No RCC
   reload or tunnel restart is required for this Core-only observability change.

## Acceptance

- Every authenticated MCP request produces one timestamped `request_ingress` and one timestamped
  `response_complete` with the same random trace ID.
- Status/capability calls include a timestamped `handler_done` tool kind.
- `bct_status` returns the same 32-hex server-generated trace ID used by its local timing stages.
- Tests prove logged events contain no request body, prompt, credential, or caller-supplied trace ID.
- The existing 43-tool catalogue and all public schemas remain byte-for-byte unchanged.

## Isolated evidence

- Focused compile and trace/MCP integration: 7 tests PASS after the final POST-only ingress filter.
- CI-equivalent local Core shards: 82 + 165 + 180 + 201 = 628 tests PASS.
- Full and candidate MCP catalogues both contain 43 tools, 32,542 canonical JSON bytes, and exact
  SHA-256 `6319e28a1f231e48ee131c0f20512e5d66069a8cfd14402a518e83154d98e4ae`.
- VTL/browser validation is not selected because the diff changes only Core timing metadata and its
  tests; no RCC, browser, Desktop Agent, selector, scenario, or VTL runtime file changes.
- No GitHub Actions dispatch, PR, merge, deployment, service restart, tunnel change, or RCC reload has
  occurred yet.
