# BCT Chrome/Explorer semantic application targeting — 2026-10-19

Status: implementation and validation in progress.

## Boundary

Add one `desktop_application_target` capability with read-only `list` and
Lease-producing `bind` operations. It recognizes Chrome and Explorer by exact
process-family plus top-level window class, optionally narrows by Unicode title,
and binds only when one current-Session/current-virtual-desktop window remains.

Zero, multiple, or Agent-truncated candidates fail before any control effect.
The resulting exact Agent Lease is then consumed by the existing activate,
input, and window-management capabilities. This increment does not inspect
Chrome tabs/profiles or resolve Explorer folder paths; those require separate
browser/shell semantic adapters after this reliable HWND binding boundary.

## Gates

1. Focused unit/MCP/core tests and compileall.
2. Adaptive exact-head PR CI and independent merged-main CI.
3. Exact-main deployment and authenticated MCP LIVE list/bind/release proof.
4. Final control state has no Lease and emergency stop remains false.
