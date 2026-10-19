# BCT Chrome exact-tab selection

Status: IMPLEMENTED / LOCAL_FOCUSED_TESTS_PASS / PR_CI_PENDING.

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
- VTL Agent 1.9 revalidates Lease owner/ID, HWND/PID/process birth, Session,
  current virtual desktop and emergency stop before and after the helper.
- A separate UI Automation action helper requires the same ordinal and exact
  title immediately before `SelectionItemPattern.Select`, then proves exactly one
  selected tab after the call.
- The foreground root HWND must remain unchanged. A helper timeout, response
  ambiguity, postcondition mismatch, foreground change, or lease loss after an
  invocation is `UNKNOWN` and is never automatically retried.
- The active-tab no-op (`alreadySelected=true`) is the first host acceptance.
  A real switch is accepted only with a non-foreground Chrome window, exact
  before/after inventory, exact restoration, and preservation of every
  pre-existing Chrome PID/process-birth/HWND fingerprint.

## Validation state

- PASS: .NET 4 compilation of inventory helper, action helper, and Agent.
- PASS: focused BCT desktop tests (35 tests), compileall, diff check.
- PASS: authenticated MCP integration catalogue test.
- PASS: strict UTF-8/base64 helper input with a Korean expected title while the
  machine locale setting remains irrelevant.
- Pending: exact-head PR CI in VTL and BCT, merges, exact-main deployments, and
  authenticated MCP LIVE acceptance followed by a null Lease/unlatched stop.
