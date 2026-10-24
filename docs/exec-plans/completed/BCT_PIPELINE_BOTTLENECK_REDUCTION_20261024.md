# BCT pipeline bottleneck reduction — 2026-10-24

Status: COMPLETE / MAIN CI PASS / CORE LIVE

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
- Final PR #329 head `7843ecd5957963b604939d91788068e575541261`
  passed CI run `40092411261`; GitHub recorded the PR as merged by local-main
  merge commit `af619b09a3dbc4ad32b1b955434b708a9a3aa0ca`.
- Exact merged-main CI run `40097722529`: PASS.  Scope, preflight, all four
  Core shards, and duration-history completed successfully.

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

## LIVE closeout

- The unrelated untracked Monitor native output was preserved by an atomic
  same-volume move, then restored byte-for-byte to its original path after the
  deployment.  Four files / 1,488,896 bytes remain user-owned and untracked.
- The first deployment operation
  `pipeline-bottleneck-core-deploy-af619b0-20261024-01` stopped before any
  effect with `NOT_APPLIED / DEPLOYMENT_SOURCE_NOT_CLEAN`; it was not retried
  under the same operation ID.
- Deployment operation
  `pipeline-bottleneck-core-deploy-af619b0-20261024-02` applied exact main
  `af619b09a3dbc4ad32b1b955434b708a9a3aa0ca`, manifest
  `bd600fdb62fc1741d346c458732a503191f0ef0eac92c53a94641babc9f1073b`,
  as Core generation 220.  Post-deploy health was `OK`.
- Fresh authenticated LIVE operation
  `pipeline-bottleneck-live-pr329-status-01` returned `APPLIED`, observed the
  merged PR, and verified all seven requested checks as successful through the
  deployed `github_pr_status` path.
- Functional integration and the deployed Core resolve to
  `af619b09a3dbc4ad32b1b955434b708a9a3aa0ca`.  Subsequent closeout-only
  documentation commits do not change the deployment profile and therefore do
  not require another Core deployment.

No Project Run, RCC, Chrome session, or browser message delivery was changed.
