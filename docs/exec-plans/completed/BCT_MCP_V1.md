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

## Verification before live deployment

- MCP focused test: unauthorized 401; initialize; exact catalogue; work create/recover;
  read call; duplicate operation; operation receipt; conflicting work rejection.
- Deployment/service focused tests remain passing with the MCP-enabled runtime server.
- Full BCT regression, compile, diff check, GitHub CI, live protocol call, and Codex
  configuration evidence are recorded in `PROJECT_HANDOFF.md` after acceptance.
