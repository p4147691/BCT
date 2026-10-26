# Monitor source modularization truth, 2026-10-26

User goal: no manual 8만줄 monitor.js edits, and ultimately independently owned domains with interfaces, tests and live acceptance.

The controlling target architecture and migration order are in `MONITOR_ARCHITECTURE.md`. The thumbnail is the first reference extraction; later domains must follow the same port/contract/state/renderer pattern rather than copying its implementation or introducing side channels.

## What actually exists now
- Canonical editable source: source-parts/manifest.json (10 ordered JS files, about 1.4k-1.6k lines each) plus existing dedicated modules.
- Generated runtime: extension/monitor.js (15,389 physical lines); full nonblank statements were preserved in order from installed 2.0.42 source. Do not edit it.
- Deterministic builder: tools/build_monitor_bundle.py. tools/check_monitor_structure.py fails on missing/out-of-sync runtime/part syntax.
- Function ownership lookup: source-parts/SOURCE_FUNCTION_INDEX.md. Monitor.js is now a build output, not human edit authority.
- Independent responsibility modules already implemented: monitor-desktop-thumbnail-v2.js, monitor-thumbnail-service.js, monitor-bct-shell.js, monitor-ui-layout.js, monitor-act-transport.js, etc.
- Native color is separately implemented in DesktopSolidColorSource.cs and integrated with DesktopVisualSnapshot.cs. Windows color/solid/virtual desktop mode is read-only.
- NO fully isolated API boundaries have yet been established for the 10 ordered source parts. These parts share lexical globals and logic; per-domain state/API encapsulation is the next major refactoring phase and requires real E2E for notes, nodes, windows, recovery, organization and capture.

## Strict reporting
Not complete until development authority+domain API separation+CI+live deployment+real user E2E across requested functions.
Do not call blank-run compaction or 10 ordered slices 'full modularization complete'.
Avoid duplicate work: BCT-MONITOR-FULL-MODULARIZE-SOLIDCOLOR-20261026-01.
Existing live rollback protections: do not modify RCC/Core, active Chrome conversation, or unrelated extensions; preserve installed-only Monitor changes before source import.

## Domain function ownership improvement
- All 588 functions moved to 10 semantic source files, leaving ordered global statements in original source-parts. The compiled 15,389-line runtime SHA remained fa8ef4d2ba8509fc29a261db7d363f508cc4e42421abb455b111a7fca86f762c, i.e. zero runtime effect.
- domains/manifest.json and SOURCE_FUNCTION_INDEX.md provide one source authority for each function. Builder prevents missing/duplicate ownership and mismatched generated output.
- Shared state and global calls remain; independently injectable state/API boundaries are not yet completed. Do not claim overall modularization complete.


## Independent runtime API progress (2026-10-26)
- 43 safe functions from four domains now execute from standalone monitor-domain-apis.js. Compatibility bridges keep existing call sites. Module is immutable and unit tested in a DOM-free Node VM.
- Shared state and other function bodies remain coupled. Full independent domain APIs and E2E remain unaccepted.

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
