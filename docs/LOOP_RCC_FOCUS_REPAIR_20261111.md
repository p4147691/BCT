# Loop Recipe RCC same-UUID existing-tab focus repair — isolated candidate

Date: 2026-11-11 (KST)
Originating Work: `bct-loop-recipe-20261111`
Direction: `direction-6fdb6878f4484275aafd37b3`
Loop PR: #470 (candidate `7d0dc3e1b82ac79b3d99b31198c32c34b4de123f` at work start)

## Current task/watch ownership
- The saved Chain Direction remains `NOT_PLANNED`, with no `chain_task_id`, `chain_operation_id`, or `chain_send_operation_id`; do not fabricate a Watch or an active Task.
- A separate actual RCC E2E Work `bct-loop-rcc-isolated-e2e-20261111` owns the existing-tab test. Test UUID `6af3b353-a5fc-83ee-8b1f-d662094a1ee4`, tab `594839360`, window `594839359`, session `5ac9207ab96e419e8939a128ab4da2ec`. This is disposable test identity, not a production Loop Work binding.
- First bootstrap send `loop-rcc-test-first-send-20261111-01`: `APPLIED` and `LOOP_RCC_E2E_TURN1_OK`.
- Existing-tab send `loop-rcc-test-second-send-20261111-01`: `NOT_APPLIED`, `RELAY_SUBMIT_NOT_ACTIVATED:RELAY_EDITOR_FOCUS_OR_CARET_INVALID`.
- Single follow-up `loop-rcc-test-second-send-confirmed-retry-20261111-02`: same confirmed `NOT_APPLIED`; do not replay.
- Separate reviewer Work `bct-loop-independent-review-20261111`, original send `loop-reviewer-first-exact-send-20261111-01`: `UNKNOWN` / `RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH`. An observed reviewer response is not permission to resubmit the original Operation.
- N39 Manager and N42 contract/measurement node are active. Do not touch either node's Work, Watch or owned files.

## Root-cause hypothesis and scoped patch
The error originates from `modules/rcc/extension/content/simple_relay_executor.js` in `ensureCurrentEditorFocusAtEnd` before any submit activation. The current 3 immediate attempts, zero timeout, can exhaust before a React/ProseMirror focus transition settles. No proof yet establishes this as the sole actual failure mechanism. The existing-tab editor is observable and idle, but an invalid caret/focus returned before activation.

Only change `modules/rcc/extension/content/simple_relay_executor.js` and `modules/rcc/extension/test_editor_rebind_submission_v1.js` in an isolated branch. Expand bounded reacquisition to at most 6 attempts with 40 ms gaps (~200 ms total) and keep exact draft text, current connected editor, focus and end-of-draft caret fences. Catch transient detached selection errors rather than treating them as permission to submit. Do not add any send retry, keyboard fallback, alternate destination, or change in the RCC Operation contract.

**File ownership boundary:** N42 owns RCC public input arguments/schema, contract and latency instrumentation; specifically do NOT modify `src/bct/features/rcc.py`, command catalog, core operation receipts, or telemetry source. This patch owns only the two content-script + regression test files named above. The shared live/installed extension is NOT changed.

## Test and release boundary
- Focused editor-rebind JS PASS; add regression for focus becoming valid only on the fifth bounded attempt and reject mutated drafts.
- Existing simple-relay submission-fence / route adapter / simple-relay-v0 tests PASS.
- Exact SHA PR CI and independent review remain prerequisites.
- Actual two or more messages in the same UUID with the PATCHED extension have NOT been proven. Re-running the existing LIVE extension would not test this candidate; do not claim live E2E success.
- Never merge the patch or Loop PR into main, deploy, or reload operating RCC without exact SHA approval and protected integration.

Next: inspect the source/contract conflict with N42, review this diff, verify CI exact SHA, perform isolated patched-extension physical E2E if an independent environment is available, then request an independent Supervisor acceptance.
