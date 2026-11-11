# Exact-UUID stale watch identity audit — isolated follow-up to PR #471

## Candidate boundaries
- Base PR #471 SHA f6e8a3dd74da8c8ef31939f9afd22787170c4479 (full CI #42937777114 SUCCESS).
- PR #473 SHA d3eb60ba2c2ec0c0d6edcc5da57be5ceef27c0ba is exactly ONE child commit above PR #471. Verified merge-base equals f6e8a3dd... and rev-list count 1; changed paths are AGENTS.md, BATCH_DEFAULT_EVIDENCE_20261111.md, docs/MCP_INTEGRATION.md, src/bct/data/component-library.json, src/bct/mcp_server.py, tests/test_read_batch_default_contract.py. It is NOT an independently mergeable batch-only change onto main.
- This candidate is a separate isolated worktree based on PR #471; no PR #471 or #473 source was changed. No measurements repeated. No N39/N40 branch, source main, LIVE, receipt, RCC installation, MCP tool registration or browser effects changed.

## Reproduction and minimum repair
- In PR #471 _response_for reuses watched_session_id, watched_tab_id and watched_window_id indefinitely. RCC extension modules/rcc/extension/domain/tab_group_service.js getLatestAssistantMessage returns a NOT_APPLIED READ_LATEST_ASSISTANT_IDENTITY_MISMATCH for a moved tab; stale session can yield TAB_GROUP_SESSION_ID_MISMATCH.
- A new isolated test first failed: old candidate observed only the old tab [101], where the same UUID's independently verified new tab [102] should be re-read. This is a mocked proof of one reachable stale watch path, NOT confirmation of a physical user incident.
- Minimal fix: on ONLY those explicit RCC identity mismatch observations, _response_for invokes existing _locate(instance, exact same UUID). It requires one unique live match, otherwise returns a read-only diagnostic. The new route is used for ONE new read and remembered in a per-watch in-memory override keyed by task/generation/instance/UUID. Durable watch baseline/receipts remain unmodified. No text send, operation replay, generic read error retry or recovery-role change.
- Every ordinary read still uses fastpath with one request. On a proved identity mismatch one bounded global discovery and one read-only retry are added. After restart the in-memory override is lost, but future mismatch can be safely re-resolved.

## Tests / known limits
- New tests: same UUID tab move and cached subsequent poll; session reconnection; generic unavailable no discovery; timeout no retry; unresolvable ambiguous target no fallback. Existing fastpath and delayed-send regression preserved.
- Does not automatically recover from opaque exceptions/unknown transport timeouts. No inference from absent answers to failed message delivery, no UNKNOWN replay. No claim of improvement in live p50/p95 from mock tests.
- ThreadPool read-only helper remains existing PR #471 behavior, not expanded.
- Exact SHA CI / separate independent source review required before integrating candidate.

## N23 Supervisor-only review route — design only, NOT implemented
- Current Chain Recipe NEW_TASK enforces authenticated live Manager+Worker+global Supervisor identities, matching Manager/Worker network. N23 exact global Supervisor UUID 6aeed472-62d8-83ee-b86d-16cd79d48132 cannot be relabeled Worker or assigned a fictitious Manager. Original direction-2d92684d9caa4551b89bd728 was saved without assessment, NOT_PLANNED; parent-linked HOLD direction-pr471-pr473-review-hold-20261111 preserves the blocker. PR #474 adb8602f... prevents new unbound USER NEW_TASK writes but does NOT enable Supervisor-only sends.
- Proposed minimum separate contract: a distinct supervisor_readonly_review mode must bind exact existing Supervisor UUID and Work/parent Direction/PR+SHA evidence; require fresh Node Info/RCC session/tab and same-principal authorization; explicitly assert no Manager/Worker election or network updates, no effects beyond one independently receipted bounded review instruction, no retry of UNKNOWN, and return evidence/approval via the exact return binding. Add a route-specific contract schema and mock tests for role mismatch, stale UUID/tab, duplicate/UNKNOWN, response association and independently authored approval.
- No implementation, send, or approval occurred here. Independent native read review in progress elsewhere must not be called N23 approval.

## Release gate
Exact candidate SHA CI + independent review + explicit approval before main/LIVE; do not change RCC installation or MCP refresh.
