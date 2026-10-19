# BCT Chrome exact-tab selection

Status: COMPLETE — EXACT-MAIN DEPLOYED / HISTORICAL UNKNOWN RECONCILED / LIVE SWITCH-RESTORE PASS.

## Goal

Add one bounded live-host Chrome mutation after the completed read-only semantic
inventory: select an exact existing tab by its observed ordinal and exact Unicode
title under the already-bound exact Chrome Window Lease. The default path must
remain background-only and must not launch, close, navigate, focus, or inject
keyboard/mouse input into Chrome.

## Contract

- BCT exposes `desktop_chrome_tab_select` with `lease_id`, `ordinal`, and
  `expected_title`; the Work ID is the Lease owner and the normal desktop-control
  resource serializes the effect.
- VTL Agent 1.9.1 revalidates Lease owner/ID, HWND/PID/process birth, Session,
  current virtual desktop and emergency stop before and after the helper.
- A separate action helper requires the same ordinal and exact title, sends a
  bounded client-window mouse message to the exact leased HWND, then proves
  exactly one selected tab. It must not call UIA `SelectionItem.Select()` because
  Chrome translates that call into foreground activation.
- The foreground root HWND must remain unchanged. A helper timeout, response
  ambiguity, postcondition mismatch, foreground change, or lease loss after an
  invocation is `UNKNOWN` and is never automatically retried.
- The active-tab no-op (`alreadySelected=true`) is the first host acceptance.
  A real switch is accepted only with a non-foreground Chrome window, exact
  before/after inventory, exact restoration, and preservation of every
  pre-existing Chrome PID/process-birth/HWND fingerprint.
- A changed-foreground UNKNOWN is released only by
  `desktop_chrome_tab_reconcile` after two no-Lease/no-stop control snapshots and
  one exact window fingerprint/active-tab inventory prove the compensated state.
  Reconcile is read-only and never repeats the tab effect.

## Final validation

- PASS: .NET 4 compilation of inventory helper, action helper, and Agent.
- PASS: focused BCT desktop tests (35 tests), compileall, diff check.
- PASS: authenticated MCP integration catalogue test.
- PASS: strict UTF-8/base64 helper input with a Korean expected title while the
  machine locale setting remains irrelevant.
- PASS: the first LIVE attempt returned UNKNOWN when UIA Select activated the
  target. Read-only inventory proved ordinal 2 selected; a distinct compensation
  restored ordinal 1 and foreground HWND 132482. The Lease then expired normally.
- PASS: the replacement client-message helper switched ordinal 1 to 2 and back
  while foreground HWND 132482 remained unchanged throughout.
- PASS: VTL corrective PR #35 merged as
  `3ecebf6476ffe2e875f515966a818f2128e01633`; its main validation and runtime
  sync runs passed, `D:\TOOLS\VTL\current.json` points to that exact release,
  and the persistent Session 1 Agent is version 1.9.1.
- PASS: BCT corrective PR #219 merged as
  `075b74a15af0af2a8871fb036e329220f51570d5`. PR CI run `39199773462` and
  exact-main CI run `39200269200` passed every required scope, preflight, four
  core shards, and browser-bridge job.
- PASS: authenticated `bct_deploy` installed that exact BCT main as generation
  135 with manifest
  `14420b4f87876d4de0e03726026e19c01b6a8f8569236dbb5f7e1c2530591400`;
  health is READY and the MCP catalogue exposes 36 tools.
- PASS: the original `chrome-tab-live-select-2` UNKNOWN was not retried. After
  the separately compensated ordinal/foreground state was freshly proved,
  `chrome-tab-live-reconcile-changed-foreground-2` released only that exact
  unresolved claim. Final status contains no unresolved operation claim.
- PASS: authenticated LIVE operation `chrome-tab-bg-live-select-ordinal2-1`
  changed background HWND 197932 from ordinal 1 to 2, and
  `chrome-tab-bg-live-restore-ordinal1-2` restored 2 to 1. Both receipts report
  `foregroundPreserved=true`; foreground HWND 132482, the original Chrome root
  process births, and Agent PID/process birth remained unchanged.
- PASS: the final active tab is ordinal 1, the target window remains background,
  the Lease is null, and emergency stop is inactive.

## Operational lessons

- Never restore the first UIA `SelectionItem.Select()` implementation. Chrome
  promoted the target window even though the semantic tab selection succeeded.
- Chrome's accessibility titles append a changing memory figure. Consume the
  exact title immediately after a fresh inventory. A reconciliation attempt
  with an older full title failed safely with
  `DESKTOP_CHROME_TAB_RECONCILE_TAB_MISMATCH` and performed no mutation.
- Once another tab becomes active, the top-level Chrome window title changes as
  well. A restore inventory must not retain the previous active-tab text as a
  top-level `title_query`; use the exact HWND plus a stable tab substring and
  `tab_scope=any`, then consume the freshly returned full title.
- Helper envelopes remain strict UTF-8/base64 and all Python validation used
  process-local UTF-8. The Windows system-locale UTF-8 checkbox is not a runtime
  dependency and was not changed.
