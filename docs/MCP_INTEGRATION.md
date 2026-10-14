# BCT MCP integration

## One catalogue, one implementation

The MCP endpoint is part of the existing BCT core service. It does not launch or own a
second BCT service. At process start, `build_mcp()` reads the exact capabilities already
registered in `OperationCoordinator` and creates one `bct_<capability>` tool for each.
The catalogue therefore cannot advertise a capability with no executor.

Four management tools are added:

- `bct_capabilities`: return the exact runtime capability/tool mapping.
- `bct_status`: return a read-only Core release/health, Monitor, RCC and active process-session snapshot without creating a work.
- `bct_work_create`: create or recover one exact work record.
- `bct_operation_get`: retrieve an operation receipt for the owning work.

`bct_status(compact=true)` limits each history category to five rows, while preserving
current state, counts and unresolved claims. Use `compact=false` for detailed history.
`bct_operation_get(wait_seconds=0..25)` waits for an existing operation without dispatching
it again. Receipt reuse is appropriate for immutable past results, not fresh health or CI.

`bct_verify` accepts up to eight `{id, capability, arguments}` steps, restricted to bounded
read metadata, existing tests and exact-head GitHub PR status. It requires the work and
principal to allow every child capability and verifies current policy before each step.
All resources are claimed atomically. It stops on the first failed/pending/unknown step;
UNKNOWN retains claims. File content and test console output are not persisted. The
receipt contains ordered evidence and timings, including completed steps before failure.
Use `bct_read` batch when file contents, rather than verification metadata, are needed.
The same tool accepts fixed versioned `local-python-validation` and `pr-readiness` recipes.
Every prepared child is checkpointed in SQLite before dispatch and exposed by
`bct_operation_get.step_journal`; an in-flight step after worker loss remains unresolved and
is never treated as safe to replay merely because earlier steps are complete.

Verification and positive `github_pr_status.wait_seconds` use the existing one-shot worker
and survive MCP disconnect. Polling CI is local to that bounded operation, never a daemon.
Recover results with `bct_operation_get`; do not create a new operation to retry UNKNOWN.

Every capability tool accepts `work_id`, `operation_id`, `arguments`, and an optional
`approval_ref`. It delegates to the same policy, work ownership, resource claim, duplicate
operation, precondition, and outcome code used by direct BCT calls.

Related file and directory inspection can use one `bct_read` call with `operation: "batch"`.
Each item has a unique caller label, an absolute path, and optionally the existing
`directory_tree` depth/limit fields. BCT validates every item before recording the operation,
claims all resources in one SQLite transaction, and returns item evidence in input order. The
batch is bounded to 20 items, 512 KiB per file, 1 MiB total file content, and 2,000 requested
directory entries. File content is returned only in the immediate response and is not persisted
in the receipt; a duplicate operation returns the receipt without replaying the read or restoring
the original content.

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

Codex approval configuration follows the user's operating policy:

- automatic: capability discovery, work creation/recovery, operation receipt, file read,
  system inspection, one-shot Python/PowerShell/argv execution, persistent process sessions,
  decision-model recommendation, monitor state, and GitHub PR status;
- prompt: file write, tests that can execute project code, Git commit, GitHub mutations,
  deployment, service control, RCC browser mutation, and decision-service lifecycle changes.

Python and PowerShell are normal BCT development tools, not privileged escape hatches. They may
run without an extra Codex prompt, but BCT still records the exact work, operation, working root,
PID/fingerprint, timeout and bounded output. A prompt remains for operations whose primary effect
is durable mutation, publication, deployment, service lifecycle change, or browser mutation.

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

Catalogue acceptance checks authenticated server tools/list and a fresh client session after deployment. Already-running clients may retain an older catalogue; this alone does not indicate server registration failure.
