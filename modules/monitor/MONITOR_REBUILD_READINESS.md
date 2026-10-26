# Monitor rebuild readiness

Status: source cleanup in progress; installed Monitor 2.0.48 is unchanged.

## Decision

Do not rewrite the whole Monitor in one replacement release. Keep the current UI and verified Windows/BCT ports, then replace one responsibility at a time. Reassess a shell rewrite only after Thumbnail, Notes, Sketch and Node list no longer depend on bundle globals.

The generated `extension/monitor.js` is not an editing surface. It remains a compatibility bundle until every active responsibility has a standalone owner. Reducing its line count without removing ownership is not modularization.

## Current measured state

The generated dependency report is `MONITOR_DEPENDENCY_AUDIT.md`.

- `monitor.js`: 14,509 physical lines, 632,954 characters.
- Function owners: 545 functions in ten editable domain files.
- Ordered bootstrap/global declarations: 417.
- Separately loaded scripts: 27.
- Definition-only functions/globals after cleanup: zero.
- The ten domain files are ownership indexes, not runtime-isolated modules. They still share globals and call each other directly.

## Removed in this cleanup

Twenty production functions had no runtime caller or external reference. Four globals existed only for those functions. They were removed from the editable domains, ordered source parts, generated bundle and indexes. The removal includes abandoned ghost telemetry helpers, obsolete organization persistence/palette helpers, unused window-focus/project-context helpers, an unused generation wrapper and the unused thumbnail batch path.

No active storage key, DOM entry point, Native request, BCT operation or user event handler was removed.

The first source-part split had accidentally dropped active code that existed immediately before it. This cleanup restored shared Chrome-window tab grouping/focus, the GitHub completion Inbox, and thumbnail node-chip/Z-order rail styling. A dedicated regression contract now prevents those features from disappearing during future bundle generation.

## Keep

Keep these verified ports and standalone implementations. A rebuild should inject or wrap them, not recreate them:

- `monitor-act-transport.js`: ACT/BCT transport boundary.
- `monitor-thumbnail-service.js`: per-HWND capture queue, cache and disposal.
- `monitor-thumbnail-contract.js` and `monitor-desktop-visual-source.js`: exact desktop wallpaper input.
- `monitor-thumbnail-background-layer.js`, `monitor-thumbnail-window-layer.js`, `monitor-desktop-thumbnail-v2.js`: bottom-thumbnail ownership.
- `monitor-bct-shell.js` and `monitor-bct-thumbnail-projection.js`: BCT read/projection boundaries.
- `monitor-window-hwnd-contract.js`: physical window identity validation.
- `monitor-node-generation-state.js`: injected generation/attention state.
- `monitor-ui-layout.js`: presentation layout policy.
- `features/sketch/monitor-sketch-feature.js` and its stylesheet: the sole owner of Sketch DOM, state, events, history and persistence calls.
- `monitor-work-recovery.js`, `monitor-context-resume.js`, `monitor-project-context-recall.js`: explicit recovery/read paths.
- Native host contracts for exact GUID, HWND, geometry, Z order and captured pixels.

Keep the following compatibility-bundle behavior until it has a standalone controller and focused acceptance:

- Notes and shared note synchronization.
- Desktop/window lifecycle and drag mutations.
- BCT node-list projection and interaction.
- Recovery UI.
- Diagnostics.
- Organization compatibility UI. It is parked/unused and receives no new migration work unless explicitly reactivated.

## Thumbnail boundary after cleanup

`MonitorDesktopThumbnailV2` now owns one complete tile refresh:

1. request and validate the exact desktop background;
2. request and validate the HWND frame;
3. render the two independent layers;
4. report `wallpaperReady`, `frameReady` and combined `ok` separately;
5. coalesce duplicate normal requests per tile;
6. queue at most one follow-up read for overlapping real wallpaper-change events.

The compatibility bundle only supplies the injected frame reader and semantic window-decoration callback, then calls `renderer.refresh(visual, desktopId)`. It no longer calls background, frame-token and window-layer methods itself. A valid window frame cannot turn a failed wallpaper read into a successful thumbnail.

Initial acceptance requires the selected tile and every background tile. Reload ACK is withheld until that gate passes.

## Next extraction order

Each step must move state and side effects, route all callers to one API, delete the old implementation, rebuild, run focused regression and pass live acceptance before the next step.

1. Thumbnail: finish source tests, deploy once, accept photo/solid/D1-D2/reload.
2. Sketch: source extraction complete behind `MonitorSketchFeature` with injected storage and a layout callback; install/LIVE acceptance remains.
3. Notes: split storage/native/AI ports from note model and editor projection, then move note state.
4. Node list: isolate BCT/RCC readers, row state and interaction; do not combine it with organization authority.
5. Desktop/window lifecycle: move exact GUID/HWND state and mutations behind one controller.
6. Recovery and diagnostics after the basic screen features are stable.
7. Organization is parked outside the active sequence; if reactivated, decide whether to migrate or remove it.

## Rebuild threshold

A clean shell rewrite becomes safer than continued extraction only when all of these are true:

- Thumbnail, Sketch, Notes and Node list can start and run without lexical globals from `monitor.js`.
- Native, BCT and storage ports have stable injected interfaces.
- Existing UI behavior has automated fixtures plus physical acceptance notes.
- The new shell can load the same controllers without copying their implementation.

Until then, a full rewrite would require rediscovering hundreds of hidden behavior contracts at once and would repeat the regression that this cleanup is removing.
