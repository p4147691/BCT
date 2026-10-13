# BCT tunnel health metadata reconciliation

Status: `LOCAL_ACCEPTED_PR_PENDING`.

## Problem

The production tunnel process continued to forward ChatGPT commands, and its exact PID-owned
loopback endpoints returned `live` and `ready`, but the configured health URL file had disappeared.
`tunnel-client runtimes status` therefore reported `healthy=false / starting`. The BCT supervisor
treated that metadata loss as process failure and repeatedly attempted a duplicate connect, which
failed because the original tunnel was still running.

The tunnel log identifies the collision: an isolated diagnostic instance used
`config_source=profile:act-control`, the same production health URL file, a dummy tunnel ID, and a
different MCP target. It overwrote the discovery file at startup and removed it when the diagnostic
process stopped. This was metadata interference, not a production dispatcher failure.

## Change

- Separate exact process identity from health metadata state.
- Never start a second tunnel when the exact executable, tunnel ID, and MCP target are running.
- When only the health URL file is missing, inspect listeners owned by the exact PID.
- Require exactly one loopback endpoint with `/healthz=live` and `/readyz=ready`.
- Restore the configured file atomically, then require normal `runtimes status` health.
- Fail closed as `BCT_TUNNEL_DEGRADED` when the probe is missing or ambiguous.
- Require development probes to use a different profile directory, alias, and health URL file.

## Acceptance

1. Isolated recovery test recreates a missing file from an exact process-owned health listener.
2. Existing module and full regression tests pass on Windows CI.
3. The exact merged source script is installed atomically with a rollback copy.
4. Restart only the supervisor host; do not stop or restart the working tunnel process.
5. Verify the tunnel PID and creation time are unchanged, status is healthy, reconnect failures stop,
   and one read-only ChatGPT-to-BCT E2E succeeds.

## Local evidence

- Focused module and recovery tests: 8 PASS.
- Recovery from one exact PID-owned endpoint: PASS.
- Two valid listeners owned by the same PID: fail closed with no file written.
- Full regression: 113 PASS in 120.790 seconds.
- Python compile and `git diff --check`: PASS.
