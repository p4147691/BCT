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

## Live acceptance

- PR #6 exact-head Windows CI: run `38244408181`, passed.
- GitHub merge: `5ac41fd61636a5c6a4486d84702ba22069c65c96`.
- Runtime root: `D:\BCT\runtime`.
- Manifest: `ae95acec3d830e19d6392e4676a03212c13e9bdeba744f969fb46854680d745a`.
- Exact source/release hash mismatches: zero.
- Initial start: PID 10672, generation 1, health OK.
- One controlled restart: pre PID 10672, post PID 19344, generation 2, health OK.
- Duplicate deploy and duplicate restart: original receipts returned; no second effect.
- Existing ACT, MCP, RCC, Chrome profile and bindings: untouched.
