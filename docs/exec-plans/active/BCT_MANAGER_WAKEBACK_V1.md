# BCT Manager Wakeback V1

Status: LOCAL_VALIDATED / PR_PENDING

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

## Local evidence

- `python -m unittest discover -s tests -v`: 193 PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- RCC Node/contract tests: PASS, including native wakeback exact-manager-role
  fence and release-payload hash baseline.

The remaining gates are exact-head PR CI, exact-SHA LIVE deployment/RCC reload,
and one fresh staged hosted E2E. Historical UNKNOWN work and claims are outside
this plan and must not be re-run or released.
