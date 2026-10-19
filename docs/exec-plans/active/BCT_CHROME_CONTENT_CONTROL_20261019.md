# BCT Chrome content control V1

Status: ACTIVE.

## Goal

Add authenticated MCP capabilities for bounded element inventory and exact
background actions inside the active web document of one existing Chrome window.
The VTL Agent remains the execution owner; BCT owns policy, durable receipts,
Lease fencing, and UNKNOWN semantics.

## Capabilities

- `desktop_chrome_content_list`: read-only bounded edit/button metadata for an
  exact Chrome HWND and optional exact active-document title.
- `desktop_chrome_content_action`: under the calling work's exact Window Lease,
  either set one writable ValuePattern or invoke one InvokePattern selected by a
  fresh opaque element ID, exact document title, and active-tab ordinal/full title.

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
acceptance must prove list plus reversible set/clear against the exact leased
Chrome window, preserve foreground and Chrome process roots, release the Lease,
and leave emergency stop inactive.  Never retry UNKNOWN.
