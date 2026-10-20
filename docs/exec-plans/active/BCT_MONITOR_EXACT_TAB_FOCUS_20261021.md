# BCT Monitor exact ChatGPT tab focus

## Objective

When the operator double-clicks one BCT node card, move to the desktop that
owns the proven Chrome HWND, restore/focus that window, select the exact
already-observed ChatGPT tab, and verify that the window and tab are active.

## Boundary

- The node card supplies the current RCC `tab_id`, Chrome `window_id`, and
  conversation key.
- The existing current-session Chrome `window_id` to HWND contract remains the
  only authority for the native window and virtual desktop.
- `browser/tab-focus-adapter.js` owns the Chrome API effect and returns
  `monitor.browser.tab-focus.receipt.v1`.
- The adapter rejects a moved tab, a changed conversation URL, non-ChatGPT
  content, or incomplete identity before any effect.
- The older `desktop_chrome_tab_select` capability is not reused here. It is a
  Lease-bound UIA ordinal selector that deliberately preserves foreground;
  this operation is an explicit Monitor UI focus action with exact Chrome IDs.
- No BCT Work, Claim, Desktop Lease, RCC message, navigation, or tab creation is
  performed by this interaction.

## Source status

- Branch: `feat/monitor-exact-tab-focus-20261021`
- Original base: `d8082fff6baaae5b792103d41b4ed289165d8d56`
- Latest integrated main: `c4d6e06ba3f8ef8038cff5155d541deedf290215`
- LIVE Monitor/RCC/Native Host: unchanged

## Verification

- Exact adapter APPLIED receipt: PASS
- Identity mismatch before effect: PASS, zero Chrome mutation
- Ambiguous post-effect failure: PASS, recorded as UNKNOWN
- Desktop switch -> native foreground -> exact tab focus ordering: PASS
- Existing BCT node interaction and thumbnail/HWND/minimized badge checks: PASS
- Monitor structure and JavaScript syntax gate: PASS
- `tests/test_monitor_runtime.py`: 10 PASS with unittest

Two unrelated checks are not candidates for this change's success signal:

- `check_monitor_desktop_visual.js` needs an operational Native Host binary
  intentionally absent from the isolated worktree.
- `check_monitor_ncodex_rdp_route.js` expects removed legacy N-CODEX UI text on
  the unchanged base and fails before this change as a stale test.

## Remaining

1. Commit and push the isolated source candidate.
2. Run GitHub CI on the exact candidate.
3. Do not overwrite the installed pending Monitor build until its existing
   reload result is reconciled.
4. After a separately staged Monitor release and same-ID reload, double-click
   N4/N7/N9 and confirm exact desktop, window, and tab selection in LIVE.
