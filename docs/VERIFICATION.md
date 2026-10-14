# Bounded verification

Create one work allowing `verify` and each requested child (`read`, `test`,
`github_pr_status`). Submit `bct_verify` with a unique operation ID and this shape:

```json
{
  "steps": [
    {"id": "source", "capability": "read", "arguments": {"path": "D:\\project\\module.py"}},
    {"id": "compile", "capability": "test", "arguments": {
      "cwd": "D:\\project", "kind": "py_compile", "targets": ["module.py"], "timeout_s": 60
    }}
  ]
}
```

Then retrieve `bct_operation_get(work_id, operation_id, wait_seconds=25)`. Reconnect and
retrieve the same ID if transport is lost. RUNNING means wait/inspect, not resubmit under
a new ID. FINISHED/UNKNOWN means investigate existing evidence; never retry the effect.
The receipt is a permanent observation, not a current source or CI approval token.

For CI, add a `github_pr_status` step with repository, number, exact expected_head,
required_checks, and optional wait_seconds up to 300. Standalone CI waits use the same
existing capability. A pending check at the deadline is PENDING, not PASS. Verification
stops on it. A later fresh read may use a new operation ID after the prior wait completes.
Merge independently rechecks the exact head and required checks; old receipts cannot
authorize merging a changed PR.

Reads return metadata only in this recipe. Single reads are wrapped in the existing
bounded batch contract. Use `bct_read(operation=batch)` separately for file contents.
Test PASS/FAIL/TIMEOUT, file hashes and CI details are returned together as durable
step evidence. Test output and file bodies are not persisted. Tests execute project
code under the existing test permissions and are not an OS sandbox.

Use `bct_status` for a compact fresh snapshot; `compact=false` returns full bounded
history. Avoid repeatedly looking up completed receipts already present in context.
Do not cache live state, permissions, or deployment preconditions for authorization.

Verification has at most eight steps, one durable operation and the union of the
existing child claims. Steps are sequential and stop on failure; it is not an atomic
rollback transaction and does not claim exactly-once external effects. Tests with
unverified side effects and crashed workers require review rather than automatic retry.
