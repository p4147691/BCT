# BCT Desktop Session read-only first slice — 2026-10-18

Status: `completed`

## Exact scope

Deliver only the prerequisite that lets BCT see the existing logged-in Windows
desktop:

1. identify the exact interactive logon session;
2. manually start one VTL-owned per-user Agent;
3. connect through a same-logon protected named pipe;
4. return exact session/foreground-window/monitor metadata;
5. capture the virtual screen, one monitor, or one exact HWND without focus or
   input mutation;
6. expose status and PNG image content through BCT MCP;
7. prove the current live monitor capture and its SHA-256.

Out of scope: Scheduled Task installation/recovery, auto-logon, program launch,
window mutation, Chrome/Explorer control, mouse/keyboard/clipboard, input lease
and emergency stop.  Those begin only after this read-only slice is accepted.

## Ownership

- VIRTUAL-TEST-LAB owns `VtlDesktopSessionAgent.cs`, its build/start helper and
  current-session smoke test.
- BCT owns endpoint validation, Pipe server attestation, operation receipts and
  the two MCP tools.
- HOST-INFRA is untouched because no privileged lifecycle operation is in this
  slice.

## Security and failure contract

- The Agent must run in a non-zero interactive Windows session.
- One session-local mutex prevents duplicate agents.
- The Pipe owner is the current user SID.  Its protected DACL contains only the
  exact logon SID and LocalSystem, both with full control.
- The Agent rejects clients outside its exact Windows session.
- BCT independently verifies server PID, user SID, logon SID, Session ID, owner
  SID and the two-entry protected DACL before writing a request byte.
- Endpoint JSON contains identity metadata only; it contains no bearer secret.
- Capture writes only under the configured BCT evidence root.  BCT verifies the
  canonical path and file SHA before returning the image.
- A missing/locked/secure desktop is reported; no other session or foreground
  target is substituted.

## Acceptance gates

1. VTL PowerShell parse validation.
2. VTL Agent compile + current-session status/capture smoke.
3. BCT focused feature/unit tests and MCP catalogue integration.
4. BCT full local regression once for the candidate revision.
5. VTL and BCT PR exact-head CI.
6. Merge both repositories.
7. Deploy exact BCT main SHA without changing the running Agent.
8. Call live `bct_desktop_session_status` and `bct_desktop_capture` through the
   authenticated MCP endpoint.
9. Confirm image content, exact session identity, hash and cleanup state.

## Completion evidence

- VIRTUAL-TEST-LAB PR #6 passed both exact-head checks and merged as
  `0733e6aeb675d21c7cb08fde45f2a3b2061d5ed1`.
- BCT PR #187 passed its 12-minute full CI and merged as
  `d6e88d00206bf5c6123a8830b04985efaf04d691`; the exact merged-main CI also
  passed before deployment.
- The reviewed deployment service replaced release `882a496739972b446affd5f04b0b3c037a00d367`
  with exact merged main `d6e88d00206bf5c6123a8830b04985efaf04d691`.
  Live Core generation is 111 and its post-deploy health contract is READY.
- A fresh authenticated MCP session advertised 24 tools including
  `bct_desktop_session_status` and `bct_desktop_capture`.
- Live status proved the manually started VTL Agent in Windows Session 1.  Live
  capture returned both MCP text metadata and an `image/png` content block.
- The accepted 1280x720 image is
  `D:\BCT\data\desktop-session\evidence\20261018T132400437Z-desktop-capture-live-01.png`
  (442448 bytes, SHA-256
  `6c847dd50ff92595012fe1ed98f8fd7b10f2d780c15e48e029c02e5eb60286b1`).
- The image was opened and visually confirmed as the current desktop.  The BCT
  source and VTL completion worktree were clean, both existing Core/Tunnel
  Supervisor tasks remained running, and no reboot, logoff, auto-start task or
  input mutation was performed.
