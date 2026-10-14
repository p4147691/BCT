# BCT Manager Wakeback V1

Status: LIVE_DEPLOYED / HOSTED_E2E_BLOCKED

## Objective

Turn an already durable, terminal worker result into one fenced notification to
the exact manager attachment currently bound to the session.  The notification
must be persisted before browser delivery, must never replay worker work, and
must fail closed when the manager epoch or attachment changes.

## Scope

- Add a durable manager-wake event containing the result identity, manager
  epoch, exact attachment identity, deterministic event/delivery IDs and
  delivery state.
- Persist a wake intent atomically with a known terminal worker result.
- Dispatch one exact RCC wake only after the intent exists.  Retry only that
  unchanged event after a confirmed non-delivery; do not retry worker work.
- Require current manager epoch, active attachment generation, instance,
  session, tab and conversation identity to match before delivery.
- Cover duplicate, stale epoch, rotated attachment, receiver busy/draft,
  acknowledgement loss and takeover with isolated tests.

## Non-goals

- Do not replay historical UNKNOWN work or release existing claims.
- Do not treat the current scheduled monitor as real-time wakeback.
- Do not change RCC status/presence or stale-GENERATING work tracked by #82.
- Do not claim manager model output is an authenticated next assignment until
  the manager invokes the bounded orchestration API under the current epoch.

## Gates

1. Focused Core/RCC fixtures and full local suite.
2. One coherent PR and exact-head CI.
3. Exact-SHA main/LIVE deployment only after preflight and rollback proof.
4. Fresh harmless manager-worker-manager E2E with one persisted result, one
   manager wake receipt, and one independently authorized next bounded task.

## Delivery evidence

- `python -m unittest discover -s tests -v`: 193 PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- RCC Node/contract tests: PASS, including native wakeback exact-manager-role
  fence and release-payload hash baseline.
- PR #112 exact head `f3f7f0953988b94f12119142c5525621fa9ea53c` passed BCT CI
  run `38616742752` and merged as `cc42b70cfa00abb86d5651ed82cb79fdd8fea549`.
- That merge is the LIVE Core release at generation 85; `/health` reports the
  same release SHA, `mcp_ready: true`, and 22 MCP tools.  After a BCT Control
  refresh, hosted ChatGPT confirmed that `bct_orchestrate` is callable.

The remaining gate is one fresh staged hosted E2E.  The first post-refresh
attempt intentionally created no assignment or browser delivery: it found an
ACTIVE `BCT-ISSUE111-LIVE-20261015` work item and the existing UNKNOWN operation
`rcc-localbridge-rename-tab594833023-20261015-02` holding the shared resource
`rcc-instance:6174664e1c1b4e6db1d4729c841db3c9`.  `node-sync` for a new E2E
would conflict with that instance-wide claim, so the attempt stopped
`HOSTED_E2E_BLOCKED` without touching either record.  Historical UNKNOWN work
and claims remain outside this plan: do not re-run, release, take over, or
reuse them.  Resume only after read-only evidence and the canonical workflow
establish that the active work and shared claim no longer fence a fresh target.
