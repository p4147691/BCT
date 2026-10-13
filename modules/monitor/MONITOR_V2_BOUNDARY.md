# BCT Window Monitor 2.0 boundary

## Primary surface

- Windows Native Host is authoritative for exact HWND existence, geometry, desktop and captured
  pixels.
- The Monitor renders windows, desktop thumbnails, window movement and local undo/recovery from
  that physical evidence.
- The primary panel shows a small BCT-native list of RCC-observed ChatGPT windows/tabs with exact
  Chrome window ID, tab ID and current OPEN/active/generating state. This projection is read-only
  and does not assign roles, permissions or physical HWND identity.
- BCT health/status is read from the exact Core endpoint on port 18790.
- Laya is shown through BCT status. The retired port-7865 UI is not a current dependency.
- Installed-extension reload only reloads the installed payload. GitHub merge, source checkout and
  deployment remain separate, visible steps.

## Frozen compatibility surface

- ACT organization, roles, node authority and auto-processing.
- ACT conversation rename and handoff/recovery endpoints.
- Node badges may be shown only as optional display metadata. The BCT-native window list uses exact
  RCC window/tab identities; an HWND badge requires a separate exact physical mapping. Neither may
  decide whether a Native Host window or thumbnail exists.

The compatibility implementation remains temporarily in source to protect physical-window
regressions, but it has no primary UI entry point and must not receive new features.
