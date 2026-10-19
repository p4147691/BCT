# BCT Issue #82 passive pre-tool boundary correlation

Status: `COMPLETE / LIVE VERIFIED`.

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
- PR #242 exact head `9befb1bb4ffea034ce965ae7f38386cea41cb3f5` passed all required CI and merged as
  `4b523ff597e5e8c1d528bb23d0d0e0fe2f6be7ab`.
- Durable deployment `issue82-passive-boundary-deploy-4b523ff-20261020-01` finished `APPLIED`.
  LIVE generation 154 is READY on that exact SHA with 43 MCP tools. No tunnel restart or RCC reload
  occurred.

## Hosted canary evidence

Three identical read-only `bct_status(compact=true)` calls and three same-length no-tool controls ran
in one exact idle ChatGPT tab. The status reply returned the server trace ID, so each Hosted call was
joined exactly to Core timing rather than selected by timestamp proximity.

| Sample | Generation start to Core ingress | Core ingress to response complete | Core response to assistant complete | Assistant generation |
| --- | ---: | ---: | ---: | ---: |
| status 1 | 5,266 ms | 161.771 ms | 3,390 ms | 8,817 ms |
| status 2 | 3,903 ms | 185.076 ms | 3,145 ms | 7,233 ms |
| status 3 | 4,921 ms | 186.672 ms | 4,794 ms | 9,901 ms |
| median | **4,921 ms** | **185.076 ms** | **3,390 ms** | **8,817 ms** |

No-tool controls produced the exact same 32-character answer in 3,342, 3,753, and 4,362 ms of
assistant generation (median 3,753 ms). The status path therefore added 5,064 ms at the median, but
only 185 ms was inside Core. The remaining 4,879 ms includes the Hosted pre-tool phase and second
model pass; this experiment cannot split context loading, queueing, reasoning, tool selection,
argument construction, or the Hosted-to-local tunnel before Core ingress.

The original 8.196-second pre-tool observation is therefore not a BCT Core processing delay. Its
internal OpenAI sub-phases remain `UNOBSERVABLE` in the consumer ChatGPT surface.

## Tool catalogue analysis

The public BCT catalogue is unchanged at 43 tools and 32,542 canonical JSON bytes. Functional
definition weight is led by Desktop (19 tools, 16,189 bytes), Git/deploy (8, 5,194), file/command
(4, 2,825), inspect/monitor (3, 2,062), orchestration (2, 1,932), Core/general (4, 1,819),
validation (2, 1,704), and RCC (1, 773); array framing accounts for the remaining bytes. After
removing schema titles and descriptions, 37 capability wrappers share one structural input schema.
This proves a strong consolidation opportunity, but not that catalogue size caused the observed
latency.

The minimum causal follow-up is an isolated second MCP endpoint that keeps the full endpoint intact
while exposing four general tools plus one generic capability dispatcher. Run randomized full-versus-
minimal Hosted canaries with the same model, reasoning level, prompt, and fresh conversation. Do not
replace the compatibility endpoint until that A/B shows a repeatable reduction.

OpenAI's current API guidance supports the direction but does not prove the consumer ChatGPT cause:
tool search can defer definitions and may reduce token use/cost, but the documented Responses API
support starts with GPT-5.4; prompt-cache reuse also depends on stable tool names, descriptions,
schemas, and ordering. A future API A/B should inspect `usage.input_tokens_details.cached_tokens`
rather than infer caching from wall time. References:

- https://developers.openai.com/api/docs/guides/tools-tool-search
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics
