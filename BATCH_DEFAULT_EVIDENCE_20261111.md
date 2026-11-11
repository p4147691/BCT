# BCT existing bct_read batch default — isolated candidate review

## Authority and boundary
- Base exact PR #471 SHA: f6e8a3dd74da8c8ef31939f9afd22787170c4479; the existing PR and worktree remain unchanged.
- Original Work: bct-rcc-roundtrip-latency-isolated-20261111. Source/benchmark Work is limited to authorized D:\BCT worktrees.
- This candidate updates only the common usage guidance, existing MCP bct_read description, generated component-library hashes, documentation and tests. No new MCP tool, no RCC commands/protocol, no changes to features/files.py.
- Neither N39 nor N40, their worktrees, LIVE Core, source main, UNKNOWN operations or installation were changed.

## Prior dot physical LIVE sample (user-supplied)
- Work dot-bct-roundtrip-speed-20261111; two files pyproject.toml 578 B and docs/MCP_INTEGRATION.md 10,470 B, combined 11,048 B.
- SHA256 ec1654853b3dfc0e045cedbaa93f0390db9b648b28d109ffe38d7dc7ca8e11c3 and 97791395fdbd52e61a172195738bc4c68f486d72662e0d34e738a775b23cddd8.
- Five alternating paired single-two-call totals [10712,11284,25728,10190,13095] ms; batch-one-call totals [4748,4807,4312,7328,6496] ms.
- Linear interpolation: single p50 11284, p95 23201.4; batch p50 4807, p95 7161.6.
- Pair #3 SINGLE is contaminated by one overlapping RCC lookup. Never treat this as clean or generalize as an overall operating improvement.

## Additional quiet physical BCT receipt measurements
- Same two bytes-identical files and hashes, five alternated pairs.
- Individual-two-call totals [4375,4110,10387,4231,4203] ms; batch-one-call [3372,2742,2483,2489,2173] ms.
- Single p50 4231, p95 9184.6; batch p50 2489, p95 3246 (linear interpolation; n=5 per route). Third single outlier (10387 ms) is not assigned a verified cause.
- Unique operation IDs: quiet-rd-single-{1..5}-{0|1}-20261111, quiet-rd-batch-{1..5}-20261111. All outcomes APPLIED, batches COMPLETE 2/2, same two SHA256 digests.
- Five distinct test files: quiet-five-batch-01-20261111 APPLIED/COMPLETE 5/5, 36,070 B, 2,459 ms; quiet-five-single-{0..4}-20261111 APPLIED, same per-file hashes, total 10,012 ms. This is one pair only, not a percentile estimate.
- Twenty distinct test files: quiet-twenty-batch-01-20261111 APPLIED/COMPLETE 20/20, 109,871 B, 3,249 ms; no corresponding serial 20-call comparison was performed.
- All measurements include external MCP/BCT tool round trips; Core execution/serialization/network stages were not independently separated. Limited sample under varying host load, no actual benchmark on a newly deployed candidate.

## Default selection policy (no new server feature)
- One file body: bct_read(operation=file, path=...).
- Independent 2-20 files within the same Work, each <=512 KiB, aggregate <=1 MiB: existing bct_read(operation=batch, items=[{id,operation:file,path},...]) as default.
- Batch sequential inside Core. Unique IDs and normalized targets; items with different Work/permissions, dependent reads or exceeded bounds stay separate. snapshot is metadata, not file bodies.
- Per-item failures: PARTIAL_FAILURE and Outcome.FAILED; never call it COMPLETE. Mid-execution changes can alter observed bytes, and the hash is of exactly the observed file contents, not a preflight snapshot.

## Test / change / release gates
- tests/test_read_batch_default_contract.py: existing MCP list_tools discovery, file compatibility, counts 2/5/20, 21 rejection, 512 KiB and 1 MiB exact bounds/overrun, duplicate ID/target, Work path, partial error, file mutation, and coordinator capability/Work handoff checks.
- Authorization nuance: the current coordinator intentionally permits a separately read-authorized trusted successor to inherit a terminal Work with an epoch increment; wrong owner is not unconditionally rejected. An otherwise identical principal without read capability is denied. No policy change or new permission is introduced here.
- Combined exact quiet repeat: single totals [4375,4110,10387,4231,4203]ms give p50 4231/p95 9184.6; batch [3372,2742,2483,2489,2173] give p50 2489/p95 3246. These are limited external tool wall times, not isolated Core processing.
- Candidate is based on PR #471 SHA f6e8a3dd; it must be submitted as a distinct branch/PR without altering PR #471's approved history or shared rcc.py.
- Existing MCP catalogue/contract tests run in isolation. Component library rebuilt from reviewed source; compare exact changed paths before CI.
- Actual current LIVE bct_read batch already callable before this branch, so no new tool installation or tool list refresh was required to make batch work.
- Proposed descriptive change in mcp_server.py becomes visible from deployed Core's MCP list_tools only after separately approved source integration/deployment and catalogue refresh verification; do not claim it is LIVE now.
- RCC installation is unnecessary for this read-only BCT Core capability. Common AGENTS.md + docs are candidate-only.
- Independent Supervisor prior Direction direction-2d92684d9caa4551b89bd728 is blocked by CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS; no independent approval receipt. No guessed topology.
- Guard: exact candidate SHA full CI and independent Supervisor approval before main/LIVE/RCC installation/MCP refresh.
