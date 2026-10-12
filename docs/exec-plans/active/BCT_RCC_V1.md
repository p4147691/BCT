# BCT RCC V1

## Goal

Preserve the accepted RCC implementation as BCT source and expose its safe browser-control
surface through the existing BCT core/MCP operation path without changing current Chrome
bindings or reinstalling the extension.

## Completed source work

- Imported 22 live extension files and the current Native Host source/manifest with exact
  SHA-256 provenance in commit `c103c8fcad0f9ab7001e06ee8370365ffc8e48d6`.
- Added the exact-instance named-pipe client and bounded `relay_browser` feature.
- Bound browser mutation idempotency to the common BCT operation ID.
- Added secret redaction at the BCT boundary.
- Focused tests cover read/duplicate, exact mutation ID, bootstrap identity, confirmed
  not-applied, ambiguous no-retry, unavailable transport, owner denial, unknown fields,
  and secret removal.

## Acceptance remaining

- Full regression, compile, and diff checks.
- GitHub PR/CI/main integration.
- Exact BCT runtime deployment and one BCT service restart.
- Fresh MCP catalogue verification and read-only live RCC state acceptance.
- Existing extension/tabs/bindings must remain unchanged.
