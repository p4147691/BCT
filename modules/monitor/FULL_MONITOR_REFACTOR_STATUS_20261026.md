# Monitor source modularization truth, 2026-10-26

User goal: no manual 8만줄 monitor.js edits, and ultimately independently owned domains with interfaces, tests and live acceptance.

The controlling target architecture and migration order are in `MONITOR_ARCHITECTURE.md`. The thumbnail is the first reference extraction; later domains must follow the same port/contract/state/renderer pattern rather than copying its implementation or introducing side channels.

## What actually exists now
- Canonical editable source: source-parts/manifest.json (10 ordered JS files, about 1.4k-1.6k lines each) plus existing dedicated modules.
- Generated runtime: extension/monitor.js (13,891 physical lines after Sketch and Notes extraction). Do not edit it.
- Deterministic builder: tools/build_monitor_bundle.py. tools/check_monitor_structure.py fails on missing/out-of-sync runtime/part syntax.
- Function ownership lookup: source-parts/SOURCE_FUNCTION_INDEX.md. Monitor.js is now a build output, not human edit authority.
- Independent responsibility modules already implemented: monitor-desktop-thumbnail-v2.js, monitor-thumbnail-service.js, monitor-bct-shell.js, monitor-ui-layout.js, monitor-act-transport.js, etc.
- Native color is separately implemented in DesktopSolidColorSource.cs and integrated with DesktopVisualSnapshot.cs. Windows color/solid/virtual desktop mode is read-only.
- Two fully isolated visible boundaries now exist. `extension/features/sketch/` owns Sketch, and `extension/features/notes/` owns Notes DOM, CSS, model, history and synchronization behind injected ports. The remaining ordered source/domain files still share lexical globals; nodes, windows, recovery and diagnostics require the same extraction pattern and real E2E.
- Organization is explicitly `PARKED/UNUSED`: preserved for possible future use, but excluded from the active migration sequence.

## Strict reporting
Not complete until development authority+domain API separation+CI+live deployment+real user E2E across requested functions.
Do not call blank-run compaction or 10 ordered slices 'full modularization complete'.
Avoid duplicate work: BCT-MONITOR-FULL-MODULARIZE-SOLIDCOLOR-20261026-01.
Existing live rollback protections: do not modify RCC/Core, active Chrome conversation, or unrelated extensions; preserve installed-only Monitor changes before source import.

## Domain function ownership improvement
- The original ownership pass moved every function to ten semantic source files, leaving ordered global statements in source-parts. The current audited compatibility source contains 516 owned functions after Sketch and Notes behavior moved to standalone controllers.
- domains/manifest.json and SOURCE_FUNCTION_INDEX.md provide one source authority for each function. Builder prevents missing/duplicate ownership and mismatched generated output.
- Shared state and global calls remain; independently injectable state/API boundaries are not yet completed. Do not claim overall modularization complete.


## Independent runtime API progress (2026-10-26)
- 43 safe functions from four domains now execute from standalone monitor-domain-apis.js. Compatibility bridges keep existing call sites. Module is immutable and unit tested in a DOM-free Node VM.
- Sketch is separately loaded before `monitor.js`; the compatibility bundle only creates it with injected storage/timing ports and calls its bounded layout API. Its old DOM, handlers, state and CSS were deleted from the bundle source in the same change.
- Notes is separately loaded before `monitor.js`; Native shared-note operations, ACT AI organization and Recovery trash are injected ports. Old Notes DOM/state/handlers/CSS were deleted from the compatibility source.
- Shared state in the remaining domains is still coupled. Full independent domain APIs and LIVE acceptance remain incomplete.

## Current dependency audit and cleanup
- `tools/analyze_monitor_dependencies.py` generates `MONITOR_DEPENDENCY_AUDIT.md` from the editable domains, ordered source parts and active script graph.
- The current source has 516 owned functions, 385 ordered top-level declarations and no definition-only function/global candidate after cleanup.
- Historical pre-split comparison found and restored three real regressions: shared Chrome-window tab grouping/focus, GitHub completion Inbox rendering, and the thumbnail node-chip/Z-rail CSS. `check_monitor_modularization_regressions.js` now pins those contracts.
- `MONITOR_REBUILD_READINESS.md` records what must be retained, what was removed and when a clean shell rewrite becomes safer than incremental extraction.
- These source facts are not deployment or LIVE acceptance. Installed Monitor 2.0.48 remains unchanged during this cleanup.

## Thumbnail reference extraction (source implementation, LIVE pending)
- Background, HWND window pixels and composition now have separate owners: `monitor-thumbnail-background-layer.js`, `monitor-thumbnail-window-layer.js` and `monitor-desktop-thumbnail-v2.js`.
- `monitor-desktop-visual-source.js` accepts one injected canonical request function. Thumbnail code cannot call Chrome Native Messaging directly.
- The persistent Control Native port correlates every response by `requestId`; a wallpaper event is no longer allowed to disturb a FIFO reply queue, and the one-off `sendNativeMessage` wallpaper side channel is removed.
- `monitor-thumbnail-contract.js` accepts only an exact desktop GUID plus either JPEG/PNG/WEBP bytes or a proven `mode:solid` `#RRGGBB` value. Invalid input clears the claimed capture and exposes the failure instead of inventing a gray wallpaper.
- This branch is not installed or LIVE accepted yet. Source build, automated regression, Native build and physical photo/solid/D1/D2 acceptance remain separate gates.


## Windows API color provenance, isolated acceptance pending
- Photo and solid must be identified by Windows desktop truth, not a stale remembered per-desktop wallpaper filename or merely the global RGB color.
- DesktopSolidColorSource.cs first requires the exact current virtual-desktop GUID. It asks read-only IDesktopWallpaper for all physical monitor wallpaper paths; for an actual solid-color presentation these paths are empty, and COM GetBackgroundColor provides the RGB value.
- If the COM interface is unavailable it uses exact-current-desktop Windows BackgroundType or distributed exposed-screen-color evidence. It never attributes current color to another desktop.
- The current PC was in picture mode during isolated E2E; a true solid-color presentation was not present and must be physically retested before claiming LIVE_SOLID_ACCEPTED. This is not a reason to fabricate a successful check.
- check_monitor_solid_native_contract.py compiles the pure GUID decision harness on Windows and asserts six false-positive/positive behaviors without changing user wallpaper.
