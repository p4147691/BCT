# BCT adaptive CI and VTL gate — 2026-10-19

Status: IMPLEMENTING

## Goal

Reduce BCT pull-request wait time without reducing regression coverage. Run the
743-test BCT suite once across four deterministic hosted-runner shards, keep the
browser-bridge boundary separate, and add a bounded VTL read-only desktop smoke
check only when the desktop boundary or CI machinery changes.

## Change boundary

- `.github/workflows/ci.yml`
- `scripts/ci_scope.py`
- `scripts/ci_test_shard.py`
- `scripts/vtl_readonly_smoke.py`
- `tests/test_ci_acceleration.py`
- this execution plan and the final handoff record

This change does not deploy or restart BCT Core, replace the Desktop Session
Agent, inject input, acquire a desktop Lease, or modify GitHub runner identity.
The VTL check may create one capture evidence file through the existing Agent;
it does not upload the screen image or window titles to GitHub.

## Safety model

- Unknown non-document paths fail closed to the broad core and browser suites.
- Every discovered `tests/test*.py` module is assigned to exactly one shard.
- Exact duplicate unittest IDs created by imported `TestCase` re-exports are
  collapsed only when the class and test method identity are also identical.
  Ambiguous duplicate IDs fail closed. Every unique test ID runs exactly once.
- Sharding changes scheduling only; it does not select individual test cases out
  of a selected suite.
- VTL validation is read-only: status, bounded screen capture and bounded window
  catalogue validation. It runs on the existing Session 1 interactive runner.
- Exact-tree CI result reuse is deferred until protected-main provenance can be
  proved automatically. A missing proof never skips a suite.

## Acceptance

1. Scope and shard planner unit tests pass.
2. The four local shard manifests have no overlap and their union equals normal
   unittest discovery.
3. All four shards, browser-bridge checks, compileall and diff-check pass.
4. The PR shows parallel core shards. The exact PR head is then dispatched to
   the private VTL repository's read-only workflow, whose repository-scoped
   `VTL-WINDOWS-01` runner validates Session 1.
5. The PR exact head merges without a LIVE deployment because runtime code is
   unchanged.

## Expected effect

Recent hosted CI spent about 579 seconds in the serial 743-test suite. Four
balanced shards should reduce that section to the slowest shard plus setup time,
while retaining the same test population. Desktop-independent changes do not
wait for the VTL runner, and documentation-only changes keep only the scope job.

Local discovery after adding the planner regression tests produced 751 test
instances but only 567 unique IDs. The remaining 184 were identical imported
`TestCase` re-exports (some repeated six times). Exact class, method and instance
state equality is required before collapsing them; all 567 unique tests passed
across the four shards. Observed local shard times were approximately 131, 78,
53 and 54 seconds.

`VTL-WINDOWS-01` is registered only to the private VTL repository; BCT has no
self-hosted runner and no cross-repository Actions secret. Therefore a BCT PR
job cannot be assigned to it. The VTL repository owns the dispatch workflow and
checks out this public BCT repository at one exact SHA. Fully automatic
cross-repository dispatch is intentionally deferred until the user approves a
BCT-specific runner registration or a least-privilege GitHub credential.
