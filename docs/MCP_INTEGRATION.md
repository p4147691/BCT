# BCT MCP integration

## One catalogue, one implementation

The MCP endpoint is part of the existing BCT core service. It does not launch or own a
second BCT service. At process start, `build_mcp()` reads the exact capabilities already
registered in `OperationCoordinator` and creates one `bct_<capability>` tool for each.
The catalogue therefore cannot advertise a capability with no executor.

Five management tools are added:

- `bct_capabilities`: return the exact runtime capability/tool mapping.
- `bct_status`: return a read-only Core release/health, Monitor, RCC and active process-session snapshot without creating a work.
- `bct_work_create`: create or recover one exact work record.
- `bct_operation_get`: retrieve an operation receipt for the owning work.
- `bct_conversation_network_get(project="표시 이름")`: read one registered conversation-network project
  by its display name (an exact project ID is also accepted) without invoking
  Monitor, RCC, Chrome, or relay delivery. It returns display names, advisory tags, activity, literal
  Monitor labels, observation states, and Monitor-only rows; route UUIDs are not returned.

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

`bct_orchestrate` is the bounded durable manager/worker entry point. It stores a
session objective and acceptance contract under one existing work, maps exact RCC
conversation attachments to logical nodes, dispatches immutable assignment envelopes,
and persists acknowledgements and terminal result envelopes in SQLite. A manager
takeover uses its own compare-and-swap epoch and therefore does not require whole-work
handoff or release unrelated claims. A worker replacement creates a new assignment
generation only when the prior receipt proves the message was not dispatched/applied;
late results from the old generation are retained as evidence but cannot become current.
`chain-run` performs two to six bounded worker assignments and one synthesis assignment
inside one background operation. Delivered or UNKNOWN messages are never replayed.
If a worker result is unresolved, synthesis is withheld until `chain-resume` has reconciled
every planned worker. `reconcile` is restricted to a single-assignment operation so it cannot
release a chain's sibling claims. `recover-not-dispatched` closes a crashed outer operation
only when SQLite proves that no dispatch reservation or message exists; otherwise the claim
remains quarantined. A terminal assignment/session may be adopted after an outer receipt loss
without sending to RCC again.

`tool-build-request` is a bounded `dispatch` specialization for an immediately needed,
small tool. It requires a named worker, exact attachment, explicit `read`, `write`, and
`test` actions, a short problem statement, one to five required behaviors, and acceptance
criteria. The worker may implement, test, and use the tool only under the Work's existing
authority; the command grants no new capability and never deploys by itself. Completion leaves
`PENDING_USER_REPORT`; `tool-build-report` returns the tool identity, assignment state, and
worker summary so the user can later choose to keep, change, or retire it.

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

### Desktop and smartphone ChatGPT ingress

The existing private ChatGPT App and OpenAI tunnel reuse this one authenticated MCP endpoint.
A connected ChatGPT conversation on a desktop or smartphone must reach the same Work/Policy
and token checks: **do not gate by phone IP, mobile carrier, LAN membership, User-Agent,
or browser tab**. A ChatGPT account sign-in alone is not BCT authority; the configured
App connection and exact BCT bearer token are required. All authenticated connections
currently map to the shared MCP Principal (`bct-mcp-local`); device, chat UI, and
ChatGPT account details are not independently verified BCT identities. A normal smartphone ChatGPT
conversation does not depend on RCC. A phone-side BCT tool call must still be proved by
an actual read-only mobile `bct_status` smoke test before claiming mobile E2E accepted.
No direct smartphone-to-PC listener, new token, second tunnel, or RCC path is added.
See `docs/BCT_MAINLINE_TRUST_BOUNDARY.md` for the accepted personal-desktop threat model.

The service health endpoint reports MCP readiness, endpoint, and tool count. The normal
deployment process verifies those fields together with the exact service PID/fingerprint,
release, manifest, generation, and instance.

Codex approval configuration follows the user's operating policy:

- automatic: capability discovery, work creation/recovery, operation receipt, file read,
  system inspection, one-shot Python/PowerShell/argv execution, persistent process sessions,
  monitor state and GitHub PR status;
- prompt: file write, tests that can execute project code, Git commit, GitHub mutations,
  deployment, service control, and RCC browser mutation.

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
