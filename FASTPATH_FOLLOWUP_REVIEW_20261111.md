# Fastpath follow-up — isolated candidate evidence

## Boundary
- Existing Work: bct-rcc-roundtrip-latency-isolated-20261111
- Previous candidate: 335b679c1436b42c9bb5ac1b51f331a82615b927
- Worktree: D:\BCT\worktrees\rcc-roundtrip-fastpath-20261111
- Base local main 76e5cb1c333a2a22cd0765e729af71ded10612d9; main/LIVE/RCC/MCP install untouched.
- N40 owns same UUID second-send focus fix, N39 owns Chain recovery/E2E. No edits to their branches/files. Shared src/bct/features/rcc.py was modified ONLY in prior isolated 335b679 contract commit; not modified in this follow-up. src/bct/send_delayed_message.py is the only production file modified now.

## Connected callers
- SendDelayedMessageService.prearm(): existing verified _locate result is passed directly to latest(), removing duplicate global discovery.
- SendDelayedMessageService._response_for(): uses durable watched_session_id/tab_id/window_id when complete; legacy watch with no exact binding retains old discovery route.
- Optional read_timing_sink forwards measurements. No changes to _send_for() effect, N40 focus handling, core claims or UNKNOWN reconciliation.

## Timing/measurement boundary
- Existing latest() sink exposes discovery_ms, rcc_roundtrip_ms, total_ms, direct_read_call_count, discovery_call_count. Server processing and on-wire transport are not independently measured by this sink.
- Controlled no-effect benchmark: tests/benchmark_rcc_read_fastpath.py alternates baseline/fastpath in same Python process, 60 iterations each, simulated 5ms discovery + 3ms RCC request. Measured baseline p50 9.019ms, p95 9.163ms; exact target p50 3.515ms, p95 3.714ms. THESE ARE SYNTHETIC MOCK WALL TIMES, NOT PHYSICAL RCC SPEED IMPROVEMENT.
- Production p50/p95 and source breakdown require authoritative equal-target read-only live trace, common trace_id across tool discovery/preflight/Core ASGI/RCC relay/DOM/receipt. Do not attribute the existing 31s/25.6s/5.3s/0.202s anecdotes to a cause.

## Integration and release boundaries
- Core source needs integration + deployment of exact approved SHA to activate both contract metadata and fastpath; not done.
- Existing MCP bct_browser generic-object schema remains unchanged. No new MCP tool; refresh only needed for MCP surface changes (none here), but reconnect/verify catalogue reflects new Core when deployed.
- RCC extension wire commands unchanged; no extension installation required for this candidate. The physical target’s RCC release compatibility must be checked by requester before enablement.
- Shared AGENTS.md unchanged. A user-facing quick guide could be updated only after owner review. No runtime directives or common declaration changed.
- PR #471, CI run #42936475113 for 1a2c2d83 failed scope/STALE_COMPONENT_LIBRARY before Core tests. Root cause: shipped component-library source hashes were stale after rcc.py and send_delayed_message.py changes. Rebuilt the generated bundle in isolation after checking input provenance; diff is only bundle fingerprint and two source hashes, no manual content or unrelated source changes. A new exact SHA CI run is required.
- PR/CI and independent Supervisor review must cite exact SHA. No main/LIVE/RCC install/MCP refresh without later approval.
