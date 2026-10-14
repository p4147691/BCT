# BCT MCP tunnel latency closeout

Status: `COMPLETE / NO_BCT_CODE_DEFECT / HOSTED_E2E_ACCEPTED`.

## Scope

This investigation separated one Hosted ChatGPT tool call into the observable path
`ChatGPT/OpenAI control plane -> tunnel-client -> BCT MCP/Core -> tunnel-client -> OpenAI control
plane`. It did not replay an existing mutation, restart the tunnel, change RCC, or weaken operation
ID, resource-claim, UNKNOWN/no-retry, or exact-SHA deployment rules.

## Exact E2E evidence

The pre-created read-only work `BCT-MCP-LATENCY-ROOT-E2E-20261014` allowed one unique operation:

- operation: `bct-mcp-latency-root-e2e-read-01`
- target: `D:\BCT\source\pyproject.toml`
- durable result: `FINISHED / APPLIED`
- observed SHA-256: `c008513eff613c09d8737e685c18f89a080621dcc9e705a543bc6c3da0d87292`
- Hosted ChatGPT tool boundary: `1.816 s`

For that operation, the exact tunnel request was correlated through the debug-only identifiers
`request_id=cmd_ad5d81ac_b0e5_4f50_b635_54953c1ba4b0` and
`tunnel_request_id=req_d3f0611ced0f4f6595d04ab746c4a2be`. Debug logging was enabled only for
the bounded measurement and restored to `info` immediately afterwards.

| Observable stage | Duration | Evidence |
| --- | ---: | --- |
| Tunnel poll completion to local MCP response | 23.057 ms | `09:11:34.6986644` to `09:11:34.7217212` |
| BCT ASGI request total | 21.706 ms | live `MCP_TIMING`, trace `b28e869d1c404975af7984a844d598dc` |
| BCT tool handler | 15.517 ms | same live `MCP_TIMING` trace |
| Local response received to control-plane POST completion | 397.753 ms | `09:11:34.7217212` to `09:11:35.1194745` |
| Tunnel poll completion to final response delivery | 420.810 ms | exact tunnel events above |
| Hosted boundary not visible in the local poll-to-post span | about 1.395 s | `1.816 s - 0.420810 s`; arithmetic residual, not a separately traced stage |

The BCT ASGI span was about 1.2% of the Hosted tool boundary. The response upload alone was about
398 ms and was roughly eighteen times the complete BCT ASGI span. The remaining roughly 1.395 s is
outside the locally observed poll-to-response interval. Installed tunnel-client 0.0.14 cannot split
that residual into OpenAI enqueue/poll scheduling, product orchestration, and response handback.

The cumulative metric snapshot changed by five `tools/call` requests during the measurement
window. Those aggregates were used only as a consistency check, not attributed to this single
operation. Exact per-request tunnel events and the durable operation timestamp are the acceptance
evidence.

## Version boundary

The installed client is `0.0.14+0f870e50` and exposes privacy-safe request IDs plus aggregate
`command_end_to_end_latency_milliseconds`, `commands_age_seconds`, and HTTP client duration metrics.
Its released wire contract has neither `resp_timing` nor `trace_context`. Public release v0.0.15
also lacks those fields and the `mcp.forward_trace_context` setting. The current upstream `master`
documents optional response timing and trace-context forwarding, but those features are not in the
latest public release inspected on 2026-10-14.

References:

- <https://github.com/openai/tunnel-client/blob/v0.0.14/docs/protocol.md>
- <https://github.com/openai/tunnel-client/blob/v0.0.15/docs/protocol.md>
- <https://github.com/openai/tunnel-client/blob/master/docs/protocol.md>
- <https://github.com/openai/tunnel-client/releases>

## Decision

No BCT Core latency defect was reproduced. A BCT code change or service restart would target the
wrong layer and is therefore not performed. PR #70's privacy-safe `MCP_TIMING` instrumentation is
sufficient for the local server boundary. PR #72's bounded batch read remains the correct available
optimization for independent reads with the same safety and approval boundary.

Do not install an unreleased tunnel-client build merely to obtain timing fields. Reconsider a
tunnel-client upgrade only after an official release contains `resp_timing` and/or opt-in trace
forwarding, then verify checksums, configuration compatibility, secret redaction, request-ID
correlation, response deadlines, health discovery, and one Hosted ChatGPT E2E before adoption.

There is no runtime rollback because this investigation changed no runtime code or configuration.
The only temporary runtime change, log level `debug`, was restored to `info`.
