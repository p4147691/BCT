# BCT MCP V1

## Objective

Expose the already accepted BCT core through one authenticated standard MCP endpoint,
without duplicating policy, ownership, operation receipts, or service lifecycle.

## Implemented

- MCP Streamable HTTP mounted in the existing BCT core service.
- Bearer authentication on loopback using a separate durable runtime secret.
- Tool catalogue generated from registered capabilities.
- Idempotent work creation and exact operation receipt lookup.
- Every capability tool delegates to the common BCT operation coordinator.
- Health includes MCP readiness and catalogue count.
- Codex configuration uses the stable endpoint and an environment-backed bearer token.

## Verification

- MCP focused test: unauthorized 401; initialize; exact catalogue; work create/recover;
  read call; duplicate operation; operation receipt; conflicting work rejection.
- Deployment/service focused tests remain passing with the MCP-enabled runtime server.
- Full BCT regression: 27 tests after upgrade-compatibility and safe-retry coverage.
- GitHub: PR #8 introduced MCP; PR #9 added profile-evolution and port-release fencing;
  PR #10 versioned the health contract for exact V1-to-V2 upgrades. Final required CI passed.
- Live release: `5d18519e9a0d3b68ef60ab7ee3c3551d741628ab`, generation 4,
  health contract 2, MCP ready, exact PID/fingerprint health.
- Live protocol: unauthorized 401; protocol `2025-11-25`; 14 exact tools; real work/read;
  duplicate receipt.
- Codex configuration: global server `bct`, environment-backed bearer token, safe read call
  from a fresh Codex process, and side-effect tools configured for interactive approval.
