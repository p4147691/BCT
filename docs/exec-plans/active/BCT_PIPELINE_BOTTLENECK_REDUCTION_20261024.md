# BCT pipeline bottleneck reduction — 2026-10-24

Status: PR EXACT-HEAD CI PASS / CLEAN LOCAL-MAIN INTEGRATION PENDING

## Goal

Reduce repeated CI and coordination delay without introducing another control
plane that can stop independent work.  Preserve `D:\BCT\source` local `main` as
the source authority and keep LIVE deployment and browser state unchanged.

## Architecture decision

- Do not create permanent CCT/DCT-style copies of BCT Core.  Development and
  validation already scale through linked worktrees, GitHub-hosted matrix jobs,
  and temporary isolated Core/SQLite fixtures.  Additional permanent Cores
  would split authority for the same local main, runtime database, LIVE service,
  and browser resources.
- Do not repurpose or extend Project Run for source integration.  Project Run
  remains a conversation-orchestration feature and is outside this change.
- Allow preparation and validation in parallel.  Serialize only the exact local
  main ref mutation and the exact LIVE target cutover.  Existing expected-HEAD
  fences and narrow resource claims remain authoritative.
- Do not add a mandatory registry, queue, or cache.  Timing history is optional;
  missing or invalid history falls back to a bounded seed and then to static
  estimates.  Existing manual workflows remain available.

## Implemented changes

1. Core CI is assigned at individual test granularity.  The slowest 40 observed
   Windows tests provide a bounded first-run seed; successful main shards publish
   full timing artifacts and save optional history for later runs.
2. The independent experimental transport module's Windows E2E runs only when
   that module or its exact baseline contract changes.  Ordinary Core, RCC,
   desktop, and unknown source changes no longer select it.
3. A long `github_pr_status` wait uses a read-specific resource keyed by exact
   repository, PR, and expected head.  It no longer owns the PR mutation or base
   branch resource while polling.  Merge still owns exact PR and base resources.
4. VTL is not duplicated as hosted unit-test theatre.  Direct immutable VTL
   validation remains the preferred local path when a change affects GUI,
   browser, desktop-agent, selector, or project scenario behavior.

## Verification

- Focused planner/GitHub tests: 19 PASS after the isolation correction.
- Windows named-pipe isolation module: 8 PASS in one serial unit.
- Final UTF-8-forced four-process local run: 885 unique tests PASS.
- GitHub-calibrated seed wall clock: 227.852 seconds; shards 219.572 /
  225.245 / 208.083 / 168.179 seconds.
- Seed-only wall clock: 247.567 seconds; shards 232.590 / 237.709 /
  244.258 / 234.594 seconds.
- Prior no-history test-granularity run: 267.356 seconds.
- Full measured-history run: 222.046 seconds; shards 219.229 / 205.348 /
  217.449 / 217.593 seconds.
- `compileall` and `git diff --check`: PASS.
- PR #329 exact-head CI run `40091211509` at
  `59ccd7c554b3da14008c1ea384020606ec079cd6`: PASS.  All four Core shards,
  scope, preflight, and duration-history passed; the unrelated experimental
  transport E2E was correctly skipped.  The optional duration cache was saved.

The first PR #329 run found one correctness boundary that local runs had not
exposed: real named-pipe ACL tests from the same module were executing in
different hosted Runner processes.  One disposable fake server did not reach
its expected EOF and left its EXE open.  Only that OS-resource module is now an
atomic serial scheduling unit.  The failed run's timing artifacts are scheduling
evidence only; they never count as validation success.

## Deferred deliberately

- PR-to-main full-CI result reuse is not implemented.  Recent local merge
  commits have an exact tree equal to the already-tested second parent, so reuse
  is technically possible.  The public personal repository currently has no
  branch protection, ruleset, or repository-scoped self-hosted runner, and an
  earlier accepted plan requires protected provenance before skipping a suite.
  Until that boundary is designed, main push retains full CI.
- Permanent extra BCT servers and Project Run integration are rejected for this
  optimization.  Reconsider only if separate deployment targets with separate
  state and ownership are introduced.

## Remaining acceptance

Integrate into local main only from a clean authority worktree, publish that
exact main, and confirm main CI.  The authoritative worktree currently contains
the unrelated untracked Monitor native build output
`modules/monitor/native/1.9.20.175-cross-window-preview/`; its owning work must
resolve it.  Do not delete, move, ignore, or bypass that output merely to merge
this PR.  No Core deployment is required because runtime behavior is unchanged.
