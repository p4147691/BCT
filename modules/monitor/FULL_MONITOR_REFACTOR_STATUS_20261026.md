# Monitor source modularization truth, 2026-10-26

User goal: no manual 8만줄 monitor.js edits, and ultimately independently owned domains with interfaces, tests and live acceptance.

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