# Monitor source modularization truth, 2026-10-26

User goal: no manual 8만줄 monitor.js edits, and ultimately independently owned domains with interfaces, tests and live acceptance.

The controlling target architecture and migration order are in `MONITOR_ARCHITECTURE.md`. The thumbnail is the first reference extraction; later domains must follow the same port/contract/state/renderer pattern rather than copying its implementation or introducing side channels.

## What actually exists now
- Canonical editable source: source-parts/manifest.json (10 ordered JS files, about 1.4k-1.6k lines each) plus existing dedicated modules.
- Generated runtime: extension/monitor.js (14,046 physical lines). Do not edit it.
- Deterministic builder: tools/build_monitor_bundle.py. tools/check_monitor_structure.py fails on missing/out-of-sync runtime/part syntax.
- Function ownership lookup: source-parts/SOURCE_FUNCTION_INDEX.md. Monitor.js is now a build output, not human edit authority.
- Independent responsibility modules already implemented: monitor-desktop-thumbnail-v2.js, monitor-thumbnail-service.js, monitor-bct-shell.js, monitor-ui-layout.js, monitor-act-transport.js, etc.
- Native background state is separately implemented in DesktopBackgroundStateSource.cs and integrated with DesktopVisualSnapshot.cs. Windows mode and global base color are read-only; GUID-specific picture lookup remains a separate read-only input.
- Two fully isolated visible boundaries now exist. `extension/features/sketch/` owns Sketch, and `extension/features/notes/` owns Notes DOM, CSS, model, history and synchronization behind injected ports. The remaining ordered source/domain files still share lexical globals; nodes, windows, recovery and diagnostics require the same extraction pattern and real E2E.
- Organization is explicitly `PARKED/UNUSED`: preserved for possible future use, but excluded from the active migration sequence.

## Strict reporting
Not complete until development authority+domain API separation+CI+live deployment+real user E2E across requested functions.
Do not call blank-run compaction or 10 ordered slices 'full modularization complete'.
Avoid duplicate work: BCT-MONITOR-FULL-MODULARIZE-SOLIDCOLOR-20261026-01.
Existing live rollback protections: do not modify RCC/Core, active Chrome conversation, or unrelated extensions; preserve installed-only Monitor changes before source import.

## Domain function ownership improvement
- The original ownership pass moved every function to ten semantic source files, leaving ordered global statements in source-parts. The current audited compatibility source contains 520 owned functions after Sketch and Notes behavior moved to standalone controllers.
- domains/manifest.json and SOURCE_FUNCTION_INDEX.md provide one source authority for each function. Builder prevents missing/duplicate ownership and mismatched generated output.
- Shared state and global calls remain; independently injectable state/API boundaries are not yet completed. Do not claim overall modularization complete.


## Independent runtime API progress (2026-10-26)
- 43 safe functions from four domains now execute from standalone monitor-domain-apis.js. Compatibility bridges keep existing call sites. Module is immutable and unit tested in a DOM-free Node VM.
- Sketch is separately loaded before `monitor.js`; the compatibility bundle only creates it with injected storage/timing ports and calls its bounded layout API. Its old DOM, handlers, state and CSS were deleted from the bundle source in the same change.
- Notes is separately loaded before `monitor.js`; Native shared-note operations, ACT AI organization and Recovery trash are injected ports. Old Notes DOM/state/handlers/CSS were deleted from the compatibility source.
- Shared state in the remaining domains is still coupled. Full independent domain APIs and LIVE acceptance remain incomplete.

## Current dependency audit and cleanup
- `tools/analyze_monitor_dependencies.py` generates `MONITOR_DEPENDENCY_AUDIT.md` from the editable domains, ordered source parts and active script graph.
- The current source has 520 owned functions and no definition-only function/global candidate after cleanup.
- Historical pre-split comparison restored the GitHub completion Inbox and exposed the earlier physical Chrome-window grouping. The node-list contract now deliberately supersedes that grouping: conversation networks and `미소속 대화` are the only visible groups, while physical desktop/window/tab order is only a fallback sort key. `check_monitor_modularization_regressions.js` pins the revised contract.
- `MONITOR_REBUILD_READINESS.md` records what must be retained, what was removed and when a clean shell rewrite becomes safer than incremental extraction.
- These source facts are not deployment or LIVE acceptance. Installed and currently running versions must be reported separately from this source cleanup.

## Thumbnail reference extraction (source implementation, LIVE pending)
- Background, HWND window pixels and composition now have separate owners: `monitor-thumbnail-background-layer.js`, `monitor-thumbnail-window-layer.js` and `monitor-desktop-thumbnail-v2.js`.
- `monitor-desktop-visual-source.js` accepts one injected canonical request function. Thumbnail code cannot call Chrome Native Messaging directly.
- The persistent Control Native port correlates every response by `requestId`; a wallpaper event is no longer allowed to disturb a FIFO reply queue, and the one-off `sendNativeMessage` wallpaper side channel is removed.
- `monitor-thumbnail-contract.js` accepts only an exact desktop GUID plus either JPEG/PNG/WEBP bytes or a proven `mode:solid` `#RRGGBB` value. Invalid input clears the claimed capture and exposes the failure instead of inventing a gray wallpaper.
- This branch is not installed or LIVE accepted yet. Source build, automated regression, Native build and physical photo/solid/D1/D2 acceptance remain separate gates.


## Windows API color provenance, isolated acceptance pending
- Windows supports per-virtual-desktop pictures; solid color is one global background mode. Dormant per-GUID picture paths are never mixed with the active solid mode.
- DesktopVisualSnapshot.cs validates the requested active GUID. DesktopBackgroundStateSource.cs uses only read-only IDesktopWallpaper: all monitor paths empty means global solid mode, while GetBackgroundColor supplies the global base color beneath pictures in every mode.
- Registry BackgroundType, screen-pixel sampling, source-tile inheritance and Monitor wallpaper writes have been removed. Failure remains visible instead of being converted into a guessed background.
- New/restored desktops are rendered only after a fresh Native snapshot succeeds. The current PC still requires physical photo/solid/reload acceptance before claiming LIVE_SOLID_ACCEPTED.
- check_monitor_background_state_native_contract.py compiles the read-only COM decision harness and rejects heuristic or setter regressions without changing user wallpaper.

## Background-layer LIVE acceptance (2.0.68, 2026-10-27)
- Installed and running Monitor both acknowledged 2.0.68 with the exact deployment token. The registered Control Host is `1.9.20.188-readonly-global-mode`; the prior 2.0.67 extension and 1.9.20.187 host remain available as rollback artifacts.
- On the current three-desktop Windows picture configuration, each active GUID returned a distinct photo snapshot plus the same official base color. Runtime diagnostics reported `background-ready`, canonical `background-only`, `capture=captured`, `accepted_kind=photo`, empty failure reasons and `thumbnail_ready=1` for D1-D3.
- A request-before/request-after comparison proved that wallpaper path, placement and per-GUID registry values were unchanged by the acceptance read. The isolated global-solid decision contract also passes, but a physical solid-color LIVE transition was intentionally not performed because verification must not change Windows personalization.
- The bottom background layer is accepted for the current picture configuration. Window pixels, semantic overlays and summary overlays remain disabled by the layer policy and require separate staged acceptance.
