# BCT desktop input — 2026-10-18

## Goal

Expose bounded real mouse and keyboard input through authenticated BCT MCP while
preserving the exact-window lease, emergency stop, durable operation fencing and
UNKNOWN-effect boundary.

## Scope

- `desktop_input` operations: mouse move, mouse click, key and Unicode text.
- Exact active `window` lease only; a session-wide lease cannot authorize input.
- Revalidate owner, lease ID, HWND/PID/process start identity, input desktop and
  emergency-stop state immediately before the effect.
- Require the leased root window to be foreground for key/text. A validated
  in-window click may be used to focus it.
- Treat partial `SendInput` as UNKNOWN and never retry it automatically.
- Keep program launch, general focus/window mutation, Scheduled Task and
  auto-logon out of this slice.

## Verification

- Unit tests for validation, owner fencing and UNKNOWN versus confirmed failure.
- VTL current-session probe smoke proving mouse move, click, Korean Unicode text,
  key input, wrong-owner rejection and emergency-stop rejection.
- PR CI, exact-main merge, exact-release deployment and live authenticated MCP
  acceptance against the dedicated probe window.
