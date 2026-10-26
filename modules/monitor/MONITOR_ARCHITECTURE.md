# Monitor architecture and migration order

## Objective

`extension/monitor.js` is a generated compatibility bundle, not an editing surface. New work moves one accepted responsibility at a time behind a narrow injected API. A file split without owned state, an interface and an independent test does not count as modularization.

The screen-level ownership map is `MONITOR_UI_FEATURE_BOUNDARIES.md`. It is the authority for deciding which visible feature owns DOM, CSS and mutable UI state; the current ten edit domains are transitional and do not define the target layout.

## Dependency direction

```text
desktop.html composition root
  -> application ports (Native, BCT, storage, browser)
  -> domain controllers (thumbnail, notes, desktops/windows, nodes, recovery, organization)
  -> pure policy/contracts
  -> presentation layers
```

Dependencies only point downward. A presentation module never opens a Native port, reads Chrome storage or selects its own backend. A transport never writes DOM. Cross-domain work goes through an explicit method or event, not another domain's mutable map.

## Runtime domains

| Domain | Owns | Required public boundary | Current state |
| --- | --- | --- | --- |
| Thumbnail | bottom-tile refresh lifecycle, background, HWND pixels, completion and overlay composition | `MonitorDesktopThumbnailV2` over injected visual/frame ports | source controller extracted; LIVE pending |
| Sketch | drawing canvas, tools, text input and history | `MonitorSketchFeature` + injected persistence port | source controller/CSS extracted; isolated test passed; LIVE pending |
| Notes | note model, undo/redo, persistence orchestration, editor projection | `NotesController` + injected storage/native/AI ports | planned after thumbnail acceptance |
| Desktop/window lifecycle | desktop identity, window observation, move/focus actions | `DesktopWindowController` + Native port | planned |
| Nodes/conversations | RCC identity projection, attention/generation state | `NodeProjectionController` + BCT/RCC readers | pure subset extracted; controller planned |
| Recovery | exact conversation restore policy and execution | `RecoveryController` + explicit launch/ACT ports | planned |
| Organization | pure hierarchy/layout policy and ACT commit projection | `OrganizationController` + ACT port | PARKED/UNUSED; compatibility code preserved, no active migration plan |
| Diagnostics | read-only health and bounded commands | `DiagnosticsController` | planned independently of organization |

## Thumbnail reference implementation

The thumbnail is the template for later domains:

```text
correlated Native Control port
  -> MonitorDesktopVisualSource          (input adapter only)
  -> MonitorThumbnailContract            (GUID and payload validation)
  -> MonitorThumbnailBackgroundLayer     (photo or confirmed solid color)
  -> MonitorThumbnailWindowLayer         (HWND image, geometry and Z order)
  -> MonitorDesktopThumbnailV2            (composition/compatibility facade)
```

Rules:

- There is one persistent Control Native port. Requests carry `requestId`; unsolicited events cannot consume replies.
- No thumbnail module calls `chrome.runtime`, `connectNative` or `sendNativeMessage`.
- The background layer is the only owner of `backgroundImage` and `backgroundColor`.
- The window layer is the only owner of thumbnail HWND elements and their image sources.
- A solid color is renderable only after the Native reply identifies the exact desktop GUID and returns `mode: solid` with `#RRGGBB` evidence. A missing/invalid reply is a visible failed state, not a fabricated gray background.
- The compositor knows layer order, not how either layer obtains or paints pixels.
- The compositor is the only owner of per-tile refresh concurrency and combined completion. Normal duplicate requests coalesce; a real wallpaper event queues one follow-up read. Background and frame success remain separately observable.

## Migration sequence

1. Finish and physically accept Thumbnail: solid, photo, D1/D2 switching, window overlays and extension reload.
2. Extract Sketch as one visible feature with its canvas state and history. **Source complete; LIVE pending.**
3. Extract Notes without changing behavior: first define storage/native/AI adapters, then move model, then editor projection.
4. Finish Nodes/conversations as one visible node panel around the already isolated pure generation/identity APIs.
5. Split the full desktop stage from the bottom desktop strip around exact GUID/HWND ownership; keep mutations behind one Native port.
6. Extract Recovery and Header command surfaces only after node and desktop identity ports are stable.
7. Extract Diagnostics independently. Organization stays parked and is excluded from the active sequence unless the user reactivates it.
8. Remove compatibility shims and global state only after every caller has moved and full regression plus LIVE acceptance passes.

At every step the old bundle remains generated from `source-parts` and `domains`; nobody edits or revives an 80,000-line artifact. A domain is complete only when authority, inputs, owned state, outputs, public API, isolated regression and LIVE acceptance are all recorded separately.
