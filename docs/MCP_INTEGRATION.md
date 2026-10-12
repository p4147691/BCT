# BCT MCP integration

## One catalogue, one implementation

The MCP endpoint is part of the existing BCT core service. It does not launch or own a
second BCT service. At process start, `build_mcp()` reads the exact capabilities already
registered in `OperationCoordinator` and creates one `bct_<capability>` tool for each.
The catalogue therefore cannot advertise a capability with no executor.

Three management tools are added:

- `bct_capabilities`: return the exact runtime capability/tool mapping.
- `bct_work_create`: create or recover one exact work record.
- `bct_operation_get`: retrieve an operation receipt for the owning work.

Every capability tool accepts `work_id`, `operation_id`, `arguments`, and an optional
`approval_ref`. It delegates to the same policy, work ownership, resource claim, duplicate
operation, precondition, and outcome code used by direct BCT calls.

Capability execution runs outside the ASGI event loop so a long Python, PowerShell, test, or
model operation cannot make `/health` and MCP transport appear dead.  The two operations that
can replace the BCT process itself (`deploy` and `service_control`) use a durable one-shot worker:
the server first records the exact operation and resource claim, writes an immutable job/launch
receipt, and returns `RUNNING`; the worker performs the already-fenced operation exactly once.
After a restart, callers retrieve the same operation receipt instead of dispatching again.  A
worker crash leaves the operation and claim unresolved and therefore fails closed.

## Transport and authentication

- Standard transport: MCP Streamable HTTP.
- Endpoint: `http://127.0.0.1:18790/mcp`.
- Network boundary: loopback only.
- Authentication: bearer token generated once at `D:\BCT\runtime\mcp.token`.
- Codex configuration name: `bct`.
- Codex obtains the token from the `BCT_MCP_TOKEN` user environment variable; it is not
  stored in Git, `bct.toml`, the Codex TOML file, SQLite receipts, or logs.

The service health endpoint reports MCP readiness, endpoint, and tool count. The normal
deployment process verifies those fields together with the exact service PID/fingerprint,
release, manifest, generation, and instance.

Codex approval configuration intentionally follows the user-facing risk boundary:

- automatic: capability discovery, work creation/recovery, operation receipt, file read,
  and GitHub PR status;
- prompt: write, test/process execution, Git commit, GitHub mutations, deployment, and
  service control, and RCC browser control.

The prompt is a Codex safety notice for a real side effect. BCT still performs its own exact
work, operation, path, SHA, resource ownership, and duplicate-effect checks after approval.

## Failure and restart behavior

MCP is served by the same process as BCT health and control. A service restart therefore
cannot leave a stale MCP endpoint owned by another BCT process. The stable URL does not
change across releases. Existing ACT MCP configuration is preserved during migration.

Adding the Codex MCP entry is a one-time client configuration change. A running Codex task
does not acquire newly configured tools retroactively; a new Codex task/session loads the
entry. This was verified with a fresh ephemeral Codex process that created a BCT work and
read a repository file through the configured MCP server.
