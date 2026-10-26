# Monitor UI feature boundaries

Status: active ownership map. The current ten `domains/*.js` files are transitional edit owners, not the final screen modules. Sketch and Notes are fully extracted screen features; Thumbnail remains the reference layered renderer.

Current migration state:

- `SketchFeature`: source extracted to `extension/features/sketch/`; isolated contract passes; installed/LIVE acceptance is pending.
- `NotesFeature`: source extracted to `extension/features/notes/`; Native shared note, ACT AI and Recovery trash enter only through injected ports; installed/LIVE acceptance is pending.
- `OrganizationFeature`: `PARKED/UNUSED`. Its compatibility code remains preserved but is outside the active basic-feature sequence. It is not migrated or extended unless the user explicitly reactivates it.
- `DiagnosticsFeature` and `RecoveryFeature`: preserved and deferred until the basic Sketch, Notes, Node panel and desktop surfaces are stable.

## Screen composition

```text
MonitorApp (composition only)
├─ HeaderFeature
│  ├─ version and connection status
│  └─ reload, recovery and collapse commands
├─ Workbench
│  ├─ SketchFeature
│  ├─ NotesFeature
│  └─ NodePanelFeature
│     ├─ ConnectedNodesView
│     ├─ SharedChromeWindowRows
│     └─ GithubInboxView
├─ DesktopStageFeature
│  ├─ current wallpaper layer
│  └─ current window layer
├─ DesktopStripFeature
│  ├─ scroll and desktop selection
│  ├─ ThumbnailFeature
│  │  ├─ background layer
│  │  ├─ HWND/window layer
│  │  └─ node badge/status overlay
│  ├─ create desktop
│  └─ trash and undo
└─ OverlayFeatures
   ├─ RecoveryFeature
   ├─ DiagnosticsFeature
   ├─ OrganizationFeature
   └─ NodeDetailsDialog
```

## Ownership

| Feature | Sole UI ownership | Owned state | Injected ports |
| --- | --- | --- | --- |
| Header | Monitor header, version/status and utility buttons | collapsed state and command busy state | deployment, RCC, ACT and tunnel commands |
| Sketch | drawing panel, canvas, tools and cursor | tool, strokes, text size and undo/redo | sketch persistence only |
| Notes | note list, editor and note buttons | notes, selection, edit history and dirty state | storage, shared-note transport and AI organizer |
| Node panel | connected-window rows, shared Chrome cards, GitHub Inbox and node detail dialog | selected node, grouping, row projection and refresh state | BCT/RCC reader, exact-tab focus and role commands |
| Desktop stage | full visible wallpaper and current-window projection behind the Monitor | selected desktop visual snapshot | read-only visual/frame ports |
| Desktop strip | bottom rail, scrolling, selection, create, trash and undo | desktop order, selected GUID and strip interaction | desktop mutation port and Thumbnail API |
| Thumbnail | pixels and semantic overlays inside one desktop tile | per-tile refresh/generation state | visual source, frame reader and node-overlay snapshot |
| Recovery | closed/deleted/reboot recovery surfaces | recoverable records and pending restores | storage, launch and ACT recovery ports |
| Diagnostics | diagnostics panel and log views | selected diagnostics tab and bounded command state | read-only health readers and explicit repair commands |
| Organization (parked) | preserved organization overlay and hierarchy editor | draft graph, history and placement | ACT organization read/commit port |

## Non-visual ports

These are infrastructure and must never create or query feature DOM:

- `NativeControlPort`: exact desktop GUID, HWND, geometry, Z order and mutations.
- `NativeCapturePort`: wallpaper and window pixels only.
- `BctRccPort`: node/session/tab observations and exact receipts.
- `ActPort`: ACT state and explicit commands.
- `StoragePort`: typed feature namespaces; no feature reads another feature's raw keys.
- `DeploymentPort`: reload token and ACK lifecycle.

## Module contract

Every visible feature exposes one factory such as:

```text
createFeature({ mount, ports, initialSnapshot })
  -> { start(), update(snapshot), destroy() }
```

Rules:

1. One DOM node and one CSS selector prefix have exactly one feature owner.
2. A feature owns its mutable state; another feature receives a snapshot or a typed event, never the map itself.
3. A feature cannot call another feature's private function or query its DOM.
4. Native, Chrome, BCT, ACT and storage access enter only through injected ports.
5. `MonitorApp` mounts features and routes typed events; it contains no drawing, note, node or thumbnail policy.
6. Extraction moves the implementation and deletes the old body in the same change. Copying code and leaving both paths is not accepted.
7. A feature is complete only after isolated tests, generated-bundle checks and physical LIVE acceptance.

## Current code to target feature

The existing edit domains intentionally do not dictate the final layout:

- Sketch DOM, CSS, mutable state and persistence now live in `extension/features/sketch/`.
- Notes DOM, CSS, model, history and shared-view synchronization now live in `extension/features/notes/`; `sketch-notes.js` retains only Recovery trash adapters and the narrow Sketch/Notes layout composition.
- `node-identity.js`, `conversations.js` and relevant `shared-ui.js` code converge into `NodePanelFeature`.
- `thumbnail-wallpaper.js` plus the three standalone thumbnail layers become `ThumbnailFeature`.
- desktop visual code in `thumbnail-wallpaper.js`, `desktop-lifecycle.js` and `shared-ui.js` separates into `DesktopStageFeature` and `DesktopStripFeature`.
- recovery code leaves `desktop-lifecycle.js` and `conversations.js` for `RecoveryFeature`.
- `diagnostics-shell.js` becomes `DiagnosticsFeature`; Organization remains parked and separate.
- `native-transport.js` becomes ports only and owns no screen feature.
- the broad `shared-ui.js` file is emptied as ownership moves; it is not a permanent module.

## Extraction order

1. Keep Thumbnail as the reference implementation and complete LIVE photo/solid/D1-D2 acceptance.
2. Extract Sketch because it is visually isolated and has the smallest external surface. **Source complete; LIVE pending.**
3. Extract Notes with separate model, persistence and editor projection. **Source complete; LIVE pending.**
4. Extract Node panel, including shared Chrome rows and GitHub Inbox, without mixing organization authority into it.
5. Split Desktop stage from Desktop strip; reuse Thumbnail rather than moving its internals back into either feature.
6. Extract Recovery and Header commands after node/desktop identity ports are stable.
7. Extract Diagnostics.
8. Organization is not in the active migration queue. If it is ever reactivated, decide then whether to migrate or remove it.

This order shrinks the compatibility bundle after every accepted feature while keeping one working Monitor throughout the migration.
