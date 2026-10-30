# Bounded verification

If an existing connector still caches the old tool list, call `bct_test` with
`arguments.operation="verify"` and the same steps. This routes to exactly the same
verify capability, permissions, digest and receipt; it does not grant verification
through test-only scope. New catalogues expose `bct_verify` directly.

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

Then retrieve `bct_operation_get(work_id, operation_id, wait_seconds=25)`. An
unverified measurement is `MEASUREMENT_UNVERIFIED`: discard its finding, fix the
observation path, and continue normal work. It creates no resource Claim and
must not become a global stop gate. Measurements can be repeated with a fresh
observation ID because they do not execute an external mutation. For a real
state-changing operation, inspect the original Operation and external state
before deciding whether re-execution is safe. A receipt alone is not current
health, CI approval, or proof that a target failed. See
`docs/MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md`.

Each prepared step is also stored in the SQLite `operation_steps` journal before the first
child is dispatched. `bct_operation_get` returns this as `step_journal`, including the stable
step request digest, `PENDING/RUNNING/FINISHED/SKIPPED` state, outcome, bounded evidence and
timestamps. A process loss can therefore distinguish completed steps from the exact in-flight
step. It does not make that in-flight effect safe to retry: `RUNNING` without a terminal
checkpoint remains unresolved until capability-specific reconciliation proves the effect.

## Fixed recipes

Versioned recipes use the same `verify` capability, policy checks, claims, worker and receipt.
They are server-owned plans rather than caller-defined control flow. V1 exposes:

- `local-python-validation` version `1`: one bounded batch metadata read followed by one
  existing `py_compile` or `unittest` step.
- `pr-readiness` version `1`: one exact-head required-check observation/wait.

Submit a fixed recipe with `recipe_id`, exact `recipe_version`, and `inputs` instead of
`steps`. Unknown recipe names, versions and input fields fail before an operation is recorded.
The normalized plan receives a stable SHA-256 `plan_digest` in its final evidence.

```json
{
  "recipe_id": "local-python-validation",
  "recipe_version": 1,
  "inputs": {
    "paths": ["D:\\project\\module.py"],
    "cwd": "D:\\project",
    "kind": "py_compile",
    "targets": ["module.py"],
    "timeout_s": 60
  }
}
```

Recipes do not support arbitrary YAML, loops, conditions, nested recipes, writes, Git
mutations, merge or deployment. Those remain separate capabilities with their existing
approval and exact-effect contracts.

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
