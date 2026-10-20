# BCT Monitor flexible UI: isolated pre-LIVE handoff (2026-10-20)

Status: ISOLATED_FEATURE_TESTED / NOT_DEPLOYED / EXTERNAL_NATIVE_GATE_UNVERIFIED.

Isolation and owner:
- BCT Work: BCT-MONITOR-UI-FLEXIBLE-ISOLATED-20261020-01
- Working tree: D:\BCT\worktrees\bct-monitor-ui-flexible-20261020
- Branch: feat/monitor-flexible-ui-isolated-20261020
- Frozen source main: 9ee2953d7820a8878345e9516d3488186fae1452
- Remote origin removed from this clone. Do not push to D:\BCT\source.
- Shared source, current installed Monitor, RCC, Native Host, Chrome, BCT Core, tunnel, GitHub main, and existing Claim receipts are untouched.

Implemented, isolated:
1. BCT/RCC node labels N1..Nn and actual ChatGPT conversation titles remain independent of ACT/HWND thumbnail rules.
2. Once exact physical Chrome window ID -> HWND mapping exists, all BCT labels for the shared Chrome window appear on the thumbnail. One Chrome window may contain multiple ChatGPT conversation tabs. Unknown mapping cannot fabricate a label for a different HWND.
3. `N?` appears only when an RCC-reported tab is on a supported ChatGPT host but has no registered
   conversation label or `/c/<conversation_key>`. Other browser tabs are not Monitor nodes and never
   receive `N?`. Do not invent a permanent conversation identity.
4. Desktop position is read from the observed physical HWND/desktop mapping only. The node remains listed with a provisional location if the native mapping is not yet known.
5. Existing native events refresh the displayed node location (no new polling, no tab mutation).
6. Compact 2 or 3 node columns are user switchable and stored as UI-only preference. Narrow view reduces columns.
7. Node row shows original chat title and Dn; ▶ means ChatGPT generating, Ⅱ means not generating. This is not a BCT work-completion guarantee. Stop/error symbols are not inferred without authoritative receipts.
8. Laya status button removed from Monitor UI only. Laya/BCT underlying service is untouched.
9. Reload/Recovery dropdown connects RCC requery and the existing Monitor extension reload path; RCC reload, BCT Supervisor start/recovery, MCP tunnel repair, and ChatGPT BCT Control tool refresh remain explicitly disabled pending separately approved, exact, supported action APIs. Do NOT implement these by arbitrary scripts, force restarts, or ChatGPT UI hacks.
10. Project groups and free-form role tags are sourced in principle from BCT conversation-network project_view data, not from window titles or the Chrome Project UI. The present /monitor/state list has no verified project-membership contract, so grouping is NOT switched on. No natural-language role instruction automatically modifies BCT memberships.

Verifications:
- monitor-flex-multitab-readonly-projection-acceptance-v1: FINISHED/APPLIED; N4/N5 same HWND, cross-window isolation, unresolved and pending N?, ACT fallback only before initial BCT directory read.
- monitor-flex-verify-contract-index-and-syntax-v2: FINISHED/APPLIED.
- monitor-flex-entire-targeted-regression-final-v1: targeted checks PASS except the historical desktop-visual executable check, detailed below.
- check_monitor_bct_shell.js PASS.
- check_monitor_thumbnail_service.js PASS.
- check_monitor_capture_route.js PASS.
- check_monitor_node_binding_idempotence.js PASS.
- check_monitor_structure.py PASS after official build_monitor_js_index.py regeneration.
- node --check monitor.js PASS.
- check_monitor_desktop_visual.js NOT VERIFIED: ENOENT for historical build native\1.9.20.156-desktop-visual\DesktopWindowMonitorHost.exe absent in isolated source clone; do not call this a behavioral regression.
- GUI visual inspection of the actual installed Monitor is NOT PERFORMED, because Monitor LIVE is to be preserved.

Before any LIVE change:
A. Verify other owners' active Monitor/RCC changes and compare exact target files with their commit heads; rebuild a new isolated clone if main has moved or changed this area.
B. Re-test with the current installed native executable and the up-to-date Monitor contract using approved, bounded tests.
C. Confirm BCT/RCC live node labels, native Chrome-window-ID/HWND mapping, and thumbnail rendering with actual minimized/multi-tab/closed tab samples without any unauthorized relays.
D. Project grouping requires a verified read-only BCT project directory endpoint or authorized adapter; do not invent project membership.
E. Finalize the user-facing semantics of STOP/ERROR indicators, and do not treat generation idle as task completion.
F. Make guarded reload buttons functional only with verified supported APIs and another owner's clearance; tool catalogue refresh is client-side and must not be portrayed as an MCP tunnel action.
G. Maintain backups and rollback snapshots; run required source tests, JS syntax, structured index, and actual HTML/DOM rendering tests.
H. Deploy or reload ONLY with user approval through the existing official Monitor deployment path, observing post-reload instance rather than ACK alone.

Safe extension principles:
- Read/presentation has few prerequisites and degrades gracefully if a source is unavailable.
- Side-effect actions require precise target and one accountable owner.
- Never manufacture physical HWND, conversation key, node numbers, project memberships, or completion status.
- A closed Chrome tab disappears from the live list; preserve work and conversation history, and do not mark unfinished BCT work COMPLETE.


## V2 desktop thumbnail badges and lock audit

### Implemented in the same isolated branch
- A Chrome window containing nodes N2, N3, N5, N6 renders 2/3/5/6 in its thumbnail overlay; source BCT/RCC node IDs stay separate from physical HWND identity.
- The Native Host iconic property is the only minimized-window condition. A minimized HWND's nodes are grouped by observed immutable desktop ID and deduplicated.
- Minimized indicators appear inside the thumbnail visual, bottom-right, never inside the desktop title row.
- One minimized node: 2; two: 2 3; three or more: 2 3 ...; remaining numbers are not shown.
- BCT/RCC directory refresh and native window events re-project overlays without a new polling loop.
- Both the normal and the lightweight desktop thumbnail builders put their minimized-node overlay in the image visual.

### Tests and evidence
- monitor-flex-minimized-two-plus-test-run-v2 = FINISHED/APPLIED.
- monitor-flex-final-thumbnails-native-bct-regressions-v2 = FINISHED/APPLIED: 8/8 check commands PASS including BCT multi-tab labels, minimized bottom-right, Monitor BCT shell, capture adapter, thumbnail cache, node binding, organization model and structure.
- check_monitor_bct_minimized_badges.js tests grouped minimized HWND node labels, dedupe, desktop grouping, not-minimized filtering, 2+ellipsis, and zero badges after restore.
- check_monitor_organization_model.py updated to assert the new image-overlay DOM rather than old title-row placement.
- GUI/live E2E still not run. No user Chrome tabs, Native Host, RCC, Core, tunnel, or installed Monitor modified.

### Lock / protected desktop: existing icon is NOT an enforced guarantee
- Existing Monitor has desktop modes OBSERVE_ONLY, MANAGED, PROTECTED stored in chrome.storage.local; lock icon indicates PROTECTED.
- In the inspected monitor.js, PROTECTED references only define, store, render and cycle mode. No enforcement was found at native window-move, automated Chrome/tab, relay or BCT controller effect boundaries.
- Do not claim clicking lock protects desktop. Do not automatically enable risky actions under that assumption.
- Desired semantics: PROTECTED prevents automation from moving, resizing, focusing, closing, or creating tabs/windows on that desktop or auto arranging its layout. Do not restrict manual user actions or suppress ordinary screen observation.
- First inventory actor/action boundaries (Monitor Native, BCT Desktop Lease, Chrome API/RCC). Apply protection checks at each owning effect boundary using immutable desktop ID, not D1/D2 display index. A CSS-only lock is insufficient for independent actors.
- Mark globally enforced desktop protection NOT VERIFIED until isolated protected-versus-managed desktop E2E rejects automated actions while permitting human interactions.
- Do not force extra cross-system prerequisites for ordinary node lists and thumbnails; protect only intrusive effects.

### Remaining gate
- This work does not authorize LIVE changes. Inspect other Monitor and RCC active owners and fresh main versus installed Monitor diffs before integrating, then test visually with the true Native Host and Chrome. Separate user approval required for deployment.

## 2026-10-20 minimized badge projection correction

### Cause confirmed by LIVE evidence
- The installed Monitor hid a desktop preview on either a native `iconic: true` field or a `reason: "minimized"` lifecycle event.
- The minimized-node overlay used only `iconic: true`. A valid lifecycle event that supplied `reason: "minimized"` without that field could therefore hide the Chrome preview while projecting no node number. This is the observed LIVE failure; it is not a missing BCT node registration.

### Isolated correction
- `monitor-minimized-node-badge-contract.js` is a pure boundary: Native lifecycle provides minimized/desktop facts; BCT/RCC provides existing node numbers for an HWND. It cannot create a node, alter a window, or infer an HWND.
- Both the thumbnail hide path and the badge path normalize `reason: "minimized"` and `iconic: true` to one minimized state.
- A minimized event schedules exactly one 250 ms identity re-convergence. It refreshes the read-only identity index and redraws only the badge projection; it does not poll, reload Chrome, mutate a tab, or control a window.

### Isolated verification
- `node --check monitor-minimized-node-badge-contract.js` PASS.
- `check_monitor_bct_minimized_badges.js` PASS: shared-window labels, desktop grouping, restore removal, `reason: "minimized"` normalization, bottom-right 2+ellipsis projection, and no invented labels.
- Existing current-session HWND, thumbnail-label, and thumbnail-service checks PASS.

### Still required
- The correction is source-only and is not installed. Before any LIVE claim, deploy through the official Monitor path, same-ID reload it, and repeat one bounded minimize → visible number → restore → removed-number E2E on an already-open ChatGPT Chrome window.

## 2026-10-20 thumbnail status SVG contract

- Thumbnail and node-list state icons are inline SVG only: filled play triangle, two-rectangle pause, square close-safe completion, and triangle/exclamation warning. They share one white monochrome style.
- Existing overlay containers are reused; no desktop/window capture pixels, capture route, click target, drag target, or completion acknowledgement path changes.
- A square is allowed only for a connected task with an authoritative terminal success report. Chat generation becoming idle, a disconnected connection, a stopped/cancelled process, or an unverified report cannot create it.
- Network disconnection, retry/recovery/new-chat requirements, failed/blocked reports, and review-required reports use warning. Warning is independently rendered with an active/play or pause icon when both facts exist.
- This is source-only and shares the same pending LIVE gate as the minimized-number correction.

## 2026-10-21 open-window node projection: legacy-state gate removed

### LIVE failure evidence and exact cause
- Installed Monitor 2.0.14 acknowledged the official same-ID reload, but both desktop projections reported `NO_STATE`, `candidates: 0`, `matched: 0`, and `rendered: 0`.
- The overlay was not hidden by capture pixels or z-index. `monitor-bct-thumbnail-projection.js` returned before collecting exact HWND candidates whenever the legacy `monitorLastAiState` value was null.
- BCT/RCC node cards and node-number lookup use `monitorBctWindowNodesCache`; this authoritative path remains valid without legacy ACT/AI state. The renderer therefore had an obsolete cross-domain prerequisite.
- The previous regression passed only because it injected `state: {}`. It did not reproduce the actual BCT/RCC-only runtime.

### Correction and regression contract
- The projection renderer no longer requires legacy ACT/AI state before enumerating exact Native HWND geometry and asking the supplied BCT/RCC number provider for labels.
- Strict window identity is unchanged: no HWND or node number is invented, and unresolved bindings still render no badge.
- `check_monitor_thumbnail_node_overlay.js` now passes `state: null` and requires an exact N4/7/9 overlay from the BCT/RCC provider, including capture-DOM replacement.
- Focused node overlay, minimized badge, thumbnail label, current-session HWND, HWND overlay-flow, render-backpressure, syntax, and Monitor structure checks pass locally.
