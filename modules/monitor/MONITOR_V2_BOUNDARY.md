# BCT Window Monitor 2.0 boundary

## Primary surface

- Windows Native Host is authoritative for exact HWND existence, geometry, desktop and captured
  pixels.
- The Monitor renders windows, desktop thumbnails, window movement and local undo/recovery from
  that physical evidence.
- BCT health/status is read from the exact Core endpoint on port 18790.
- Laya is shown through BCT status. The retired port-7865 UI is not a current dependency.
- Installed-extension reload only reloads the installed payload. GitHub merge, source checkout and
  deployment remain separate, visible steps.

## Frozen compatibility surface

- ACT organization, roles, node authority and auto-processing.
- ACT conversation rename and handoff/recovery endpoints.
- Node badges may be shown again only as optional metadata after an exact BCT window/conversation
  mapping exists. They must not decide whether a window or thumbnail exists.

The compatibility implementation remains temporarily in source to protect physical-window
regressions, but it has no primary UI entry point and must not receive new features.
