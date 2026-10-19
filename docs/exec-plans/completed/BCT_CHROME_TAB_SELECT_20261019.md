# BCT Chrome exact-tab selection

Status: LIVE FOREGROUND DEFECT COMPENSATED / BACKGROUND FIX AND RECONCILE IMPLEMENTED / CI PENDING.

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

## Validation state

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
- Pending: corrective PR CI in VTL and BCT, merges, exact-main deployments, and
  authenticated MCP LIVE acceptance followed by a null Lease/unlatched stop.
