# RCC canonical-text correction and staged orchestration acceptance

Status: LIVE_ACCEPTED / BOUNDED_V1_CHAIN_PASS.

## Verified release

- PR [#107](https://github.com/p4147691/BCT/pull/107), exact head
  `f68822cd6b8a069c4564fcb106019479da2a969c`.
- PR CI [38560663441](https://github.com/p4147691/BCT/actions/runs/38560663441):
  PASS, 185 tests (263.494 seconds), compileall PASS.
- Merge/main/LIVE: `30b91df169401300eabe97ed9d87219677d0281d`.
- Main CI [38561373094](https://github.com/p4147691/BCT/actions/runs/38561373094):
  PASS. Local full suite: 185 tests in 159.688 seconds; all 19 RCC JavaScript
  test programs, compileall and diff checks PASS.
- Core deploy `rcc-v12-deploy-core-30b91df`: FINISHED/APPLIED, health OK/ready.
  Receipt: `D:\BCT\runtime\deployments\30b91df169401300eabe97ed9d87219677d0281d.json`.
- RCC 1.0.19, content and background recovery-v12. Only background.js,
  content.js and manifest.json were installed; all exact source/payload hashes
  match the baseline in `modules/rcc/PROVENANCE.md`.
- One reload: `rcc-v12-reload-30b91df`, FINISHED/APPLIED. Exact-instance state
  and all four acceptance target probes confirmed v12 and open original tabs.
- Rollback bytes: `D:\BCT\data\deployments\BCT-RCC-V12-30B91DF\backup`.
  Four original payload files were backed up and SHA-verified before install.
  No CLI upgrade, Chrome restart, old message replay or manual claim release.

## Defect and bounded correction

The prior run07 prompt had 1,244 actual characters. A collapsed-message UI
ellipsis sibling added a 1,245th character to cloned wrapper text. Exact prompt
matching therefore could not route to the submitted user turn. The new rule
removes only a `span[aria-hidden="true"]` containing exactly `…`, immediately
after a sibling with `data-search-result-target`. Literal ellipses and unknown
layouts are not stripped. Exact prompt, conversation and ambiguity fences stay.

The isolated tree/selector fixture executes the real content routed-turn entry
and actual background injected response-recovery function. Both fail on the
old source and pass on the correction. Negative coverage includes unknown
decorations, literal hidden content, wrong/ambiguous turns and wrong
conversations; positive coverage includes expanded/collapsed text, nested
wrappers, Unicode, newlines and inline code. The original DOM is never changed
by canonicalization. The separate historical network-abort cause remains
unproven; receipt visibility alone was not used to rewrite old UNKNOWN results.

## Staged LIVE gates

The earlier successful single-roundtrip and post-reload persisted-receipt gates
from PR #105 were retained as historical evidence, not rerun. Their operations
are `rcc-v11-single-roundtrip-send-01` and
`rcc-v11-single-roundtrip-receipt-reload-01`, both FINISHED/APPLIED.

### One manager / one worker

- Work: `BCT-SINGLE-MANAGER-WORKER-30B91DF-V12-08`.
- Operation: `single-manager-worker-dispatch-30b91df-v12-08`.
- Assignment: `single-worker-acceptance-30b91df-v12-08`.
- Manager `manager-primary-v3`, epoch 1; worker `worker-recovery-v3`.
- Original existing conversation
  `6acf3783-61cc-83ec-81e6-20f45e68dcc7` had no quarantined UNKNOWN attempt.
- Exactly one DISPATCH and one RESULT; assignment APPLIED; exact supplied SHA
  returned in the result; repeated receipt read matched; new unresolved claims 0.

### Two workers / manager takeover / synthesis

- Work: `BCT-DURABLE-ORCHESTRATION-LIVE-E2E-30b91df-v12-chain09`.
- Session: `durable-orch-live-30b91df-v12-chain09`.
- Operation: `durable-orch-live-chain-30b91df-v12-chain09`: FINISHED/APPLIED.
- Workers: `worker-recovery-v3` and existing auxiliary node
  `manager-primary-v2` acting as the second bounded evidence worker.
- Assignments `live-latency-review-30b91df-v12-chain09`,
  `live-recovery-review-30b91df-v12-chain09`, and
  `live-manager-synthesis-30b91df-v12-chain09`: all APPLIED.
- Manager changed from `manager-primary-v3` epoch 1 to `manager-backup-v3`
  epoch 2 after worker results. The replacement manager consumed both exact
  results and generated the terminal synthesis.
- Exactly 3 distinct DISPATCH and 3 RESULT messages; 2 consumed worker results.
  The initiating MCP client disconnected/reconnected before result observation.
  Duplicate same-operation retrieval returned identical evidence without replay.
- Session FINISHED; new chain unresolved claims 0. Observer elapsed time after
  submit: 44,633.776 ms, one sample, not a throughput or latency distribution.
- Machine-readable report:
  `D:\BCT\data\deployments\BCT-RCC-V12-30B91DF\chain-e2e.json`.

All 26 protected preexisting resource claims were preserved with the same
resource, operation, work and epoch. Unrelated concurrent Issue #95 execution
can add its own claim; equality of the global count is not the preservation
test. No historical UNKNOWN operation was rerun, reconciled or released.

## Actual evidence task and interpretation limits

The two workers analyzed an existing latency receipt and the aggregate/direct
RCC-status discrepancy. The new manager synthesized a bounded recommendation to
correlate existing request identities/timestamps before attributing latency or
declaring host failure. This proves real read-only task delegation, result
transfer and dependent synthesis without human copy/paste.

Worker summaries remain untrusted analysis, not independently verified facts:
the 6,602-ms historical timing sample belongs to the earlier v11 receipt, not a
new v12 speed measurement. Also, the aggregate path does expose the exception
class in its `error` field, although it maps the state to UNAVAILABLE/empty tabs.
A worker's claim that exception types cannot be distinguished is too broad.
No worker recommendation was automatically executed or promoted into policy.

This acceptance uses planned manager takeover and client reconnection, not a
claim that every physical crash/network failure was exercised LIVE. Existing
isolated crash/lease/UNKNOWN tests complement these staged checks. V1 worker
assignments remain bounded read-only evidence tasks; arbitrary autonomous
cross-project mutation is not enabled by this result.

## Deferred non-blocking follow-ups

GitHub #82 remains the existing ledger; no duplicate ledger was created.

- Routine full-state/1-second monitor budget, presence freshness and stale
  GENERATING/probe fallback need their own evidence and focused tests.
- `diagnose-conversation-ui.userUnits.textFull` is raw wrapper text and still
  includes the decorative ellipsis. It is not the corrected capture canonical
  text; use that distinction when diagnosing future equality failures.
- `recoverBootstrapSubmissionAfterTransportLoss` has a separate old wrapper
  extraction path. A collapsed long first message plus lost submit transport
  may need the same bounded rule, but that combination was not reproduced or
  included in this existing-conversation response-capture acceptance. Add an
  isolated regression before proposing a correction; do not replay UNKNOWN.
- CLI Issue #106 stays deferred. No model, CLI, tunnel or monitor update was
  folded into PR #107.

The post-acceptance documentation is published on the existing work branch and
linked from PR #107 / #82. It does not create another runtime-code PR or deploy
loop; the tested official main and LIVE remain the exact merge SHA above.
