# BCT deployment/service V1

## Objective

Provide one bounded path from a verified BCT `main` commit to an immutable local release
and an exactly owned, health-verified BCT service without changing ACT, MCP, RCC, or the
Chrome profile.

## Implemented

- Named deployment profiles with exact files and fixed source/runtime/service settings.
- Clean-main and exact-source-commit fencing.
- Per-file SHA-256 manifest, atomic immutable release creation, and current pointer.
- Durable deployment and service ownership receipts.
- Exact PID, executable, creation marker, fingerprint, generation, and instance checks.
- Idempotent deployment and operation replay.
- Start, status, stop, and exactly verified restart.
- Whole-operation rollback to the previous release and service on failed readiness.

## Verification

- Focused deployment/service tests: 4 passed.
- Full BCT regression: 23 passed.
- Python compile and `git diff --check`: passed.
- Tests cover duplicate deployment/restart, stale source/current state, dirty source,
  fingerprint tampering, immutable releases, and a broken release rollback.

Live acceptance evidence is recorded in `PROJECT_HANDOFF.md` after the merged source is
deployed to `D:\BCT\runtime`.
