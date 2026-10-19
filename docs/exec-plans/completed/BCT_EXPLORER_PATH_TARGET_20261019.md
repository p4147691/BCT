# BCT Explorer folder-path targeting — 2026-10-19

Status: COMPLETE / LIVE ACCEPTED.

## Boundary

The existing `desktop_application_target` tool now accepts an optional existing
absolute `folder_path` for Explorer. The Desktop Session Agent maps Shell
location metadata to the exact current-Session/current-virtual-desktop HWND
inventory. Chrome behavior is unchanged.

List remains read-only. Bind fails closed on zero, multiple, or truncated
candidates, then the Agent revalidates the full HWND/PID/process-birth/Session/
virtual-desktop fingerprint while acquiring the existing Window Lease. The
feature does not navigate, create, close, or mutate Explorer or its files.

## Evidence

- Local focused desktop/MCP/core/layout validation passed 51 tests.
- VTL Agent 1.7 full Session 1 smoke opened a disposable Unicode folder in
  Explorer, resolved its exact HWND from the folder path, closed only that
  disposable window, and left no Lease or emergency-stop latch.
- VTL PR #29 passed validation, merged as
  `e17e7e0e296b777fcfeb81ac5a3c48db8d4e7987`, published an immutable runtime,
  and rolled out Agent 1.7.0 from that exact release.
- BCT PR #214 passed scope, preflight, all four core shards, and Browser Bridge
  Windows E2E, then merged as
  `17270507d3a763a346fb65eec44217a7da38f6a3`. Merged-main CI run
  `39191218971` passed the same gates.
- Durable `bct_deploy` applied that exact BCT SHA as generation 130 and health
  reported READY.
- Authenticated MCP LIVE exposed 34 tools, selected one current-desktop
  Explorer by its exact folder path, confirmed exact-list and bind HWND
  identity, then released the Lease without activation or input. The folder
  value was retained only as a SHA-256 in acceptance output.
- A disposable Explorer created on another virtual desktop was correctly
  excluded by the existing boundary and cleaned by exact HWND. Final desktop
  control state had no Lease and no emergency-stop latch.
