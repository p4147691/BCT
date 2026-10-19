# BCT Chrome/Explorer semantic application targeting — 2026-10-19

Status: COMPLETE / LIVE ACCEPTED.

## Boundary

The `desktop_application_target` capability provides read-only `list` and
Lease-producing `bind` operations. It recognizes Chrome and Explorer by exact
process family plus top-level window class, optionally narrows by Unicode
title, and binds only when one current-Session/current-virtual-desktop window
remains.

Zero, multiple, or Agent-truncated candidates fail before any control effect.
The exact Agent Lease is consumed by the existing activate, input, and window
management capabilities. This increment does not inspect Chrome tabs/profiles
or resolve Explorer folder paths; those remain the next browser/shell semantic
adapter boundary.

## Final evidence

- Compileall and 51 focused desktop/MCP/core/layout tests passed locally.
- Direct Session 1 read-only validation classified three Chrome windows and no
  Explorer windows without acquiring a Lease.
- BCT PR #212 passed scope, preflight, all four core shards, and Browser Bridge
  Windows E2E, then merged as
  `e196f7be4f286f01a54b919256cb997c95a79cc2`. The merge tree exactly matched
  tested commit `f4138cd`, and merged-main CI run `39189371584` also passed.
- Durable `bct_deploy` applied that exact main SHA as generation 128 and health
  reported READY.
- Authenticated MCP LIVE exposed 34 tools. It listed Chrome and Explorer,
  selected one unique non-minimized Chrome title, acquired an exact
  HWND/PID/process-birth/Session/virtual-desktop Window Lease, and immediately
  released it without activation or input.
- Final control state has no Lease and emergency stop is false.

