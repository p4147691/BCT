# BCT Chrome content control V1

Status: COMPLETE — EXACT-MAIN DEPLOYED / AUTHENTICATED MCP LIVE PASS.

## Goal

Add authenticated MCP capabilities for bounded background element inventory and
exact actions inside the active web document of one existing Chrome window.
The VTL Agent remains the execution owner; BCT owns policy, durable receipts,
Lease fencing, and UNKNOWN semantics.

## Capabilities

- `desktop_chrome_content_list`: read-only bounded edit/button metadata for an
  exact Chrome HWND and optional exact active-document title.
- `desktop_chrome_content_action`: under the calling work's exact Window Lease,
  either set one writable ValuePattern or invoke one InvokePattern selected by a
  fresh opaque element ID, exact document title, and active-tab ordinal/full title.
  `set_value` requires the leased Chrome window to already be foreground; callers
  explicitly activate it first. The action never performs implicit activation.

Text is never persisted in evidence or output.  Only its UTF-8 byte length,
character length, and SHA-256 are returned.  Invoke success means the exact UIA
InvokePattern call returned while the Lease/window and foreground remained exact;
it does not assert an application-specific server-side result.

## Intended files

- `src/bct/integrations/desktop_session.py`
- `src/bct/features/desktop_session.py`
- `src/bct/service.py`, `src/bct/mcp_server.py`, `src/bct/core/operations.py`
- `bct.toml`
- focused desktop/MCP/module/CI tests
- `docs/USER_GUIDE.md`, `docs/CAPABILITY_OWNERSHIP.md`, `PROJECT_HANDOFF.md`

## Deployment and E2E boundary

Run focused tests first, then the repository's adaptive/full required checks and
static/diff checks.  Merge only exact heads with required CI green.  Deploy the
exact BCT main SHA through the reviewed immutable profile.  Authenticated LIVE
acceptance must prove background list plus explicit activation and reversible
set/clear against the exact leased Chrome window, restore the original foreground,
preserve Chrome process roots, release the Lease,
and leave emergency stop inactive.  Never retry UNKNOWN.

## Final validation

- VTL PR #37/#38/#39/#40 produced Agent 2.0.2 at immutable main
  `b60de5b2d519ae651da1772ad69b44294a7d68b1`. BCT PR #221/#222 produced
  main `928ffcf631d034b446544066e696d65d2ac2f3bc`; exact-main CI run
  `39208516097` passed every required job.
- BCT focused desktop/MCP tests (61), full suite (789), `py_compile`, and
  `git diff --check` passed before merge.
- Authenticated `bct_deploy` installed exact BCT main as generation 137 with
  manifest `05757ae9ff4c20026e26dccc6ae1cdde04ca072b57dc0b56741d3f372c09f3e3`.
  Health is READY/OK and the MCP catalogue contains 38 tools including both
  new Chrome-content capabilities.
- Authenticated LIVE background `set_value` was rejected before dispatch as
  `CHROME_CONTENT_VALUE_REQUIRES_FOREGROUND`. After explicit restore/activation
  of the exact disposable Chrome for Testing window, set operation
  `mcp2-set-72a0c82ffe8044faa1bcc93c720c1186` wrote 16 characters / 20 UTF-8
  bytes and matched the returned SHA-256. Clear operation
  `mcp2-clear-51bf7fa419bf408ba9987262857d0ddd` proved zero characters and the
  empty-string SHA-256. Both were APPLIED with `foregroundPreserved=true`.
- One immediate read-only post-clear list overlapped a user foreground change
  and failed closed with `CHROME_CONTENT_LIST_CHANGED_FOREGROUND`; it performed
  no mutation and was not retried as an effect. A later fresh authenticated MCP
  list proved one writable empty editor, one disabled send control and preserved
  foreground.
- Final control state has no Lease and no emergency stop; the disposable window
  is minimized again. No Chrome process/tab/window was launched or closed and no
  content was submitted.
