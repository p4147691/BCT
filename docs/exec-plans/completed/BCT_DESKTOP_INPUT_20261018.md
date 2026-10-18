# BCT desktop input — 2026-10-18

Status: `complete`

## Delivered boundary

BCT now exposes audited real mouse move/click, restricted key input and Unicode
text input through authenticated MCP. Every operation requires the exact active
VTL `window` lease. BCT derives the lease owner from the work, durably fences the
operation and preserves UNKNOWN/no-retry semantics. VTL revalidates the owner,
lease ID, HWND/PID/process-start identity, input desktop and emergency stop
immediately before `SendInput`.

Mouse coordinates must resolve to the leased root window or a child control.
Key/text require the leased root window to already be foreground; an exact
in-window click can establish focus. A partial `SendInput` is UNKNOWN and is not
retried. Program launch, general window activation/mutation, Scheduled Task and
auto-logon remain outside this slice.

## Verification and rollout

- VIRTUAL-TEST-LAB PR #10 passed both checks and merged as
  `806682dca0611bae66ec17df43a718271ad499aa`.
- VTL PowerShell parse validation passed, and the dedicated current-session
  WinForms probe observed mouse movement, a real button click, Korean Unicode
  text, Backspace, wrong-owner rejection and emergency-stop rejection.
- BCT focused desktop/MCP/module tests passed 21/21. The correctly isolated full
  local regression passed 731/731.
- BCT PR #193 passed its full Windows CI and merged as
  `0d7510659fd8ae59305db1695d922ce5189b597f`.
- Exact merged BCT main deployed with outcome APPLIED. Core Generation 115 was
  READY and advertised 27 MCP tools including `bct_desktop_input`.
- Live authenticated MCP acceptance used only a dedicated probe window. It
  observed exact cursor movement, one button click, Korean Unicode text and
  Backspace; a second work could not use the lease; emergency stop revoked the
  lease and blocked further input.
- The exact generation-fenced reset succeeded. Final Agent state had no active
  lease and no active emergency stop. The original cursor/foreground window was
  restored and all temporary probe/script artifacts were removed.

## Next slice

Add exact-window inventory/selection and bounded activation, or program launch,
behind the same lease/emergency/UNKNOWN boundary. Do not infer either authority
from the input capability delivered here.
