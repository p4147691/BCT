# BCT GitHub integration V1

Status: IMPLEMENTING

## Scope

- Exact-SHA branch push with remote precondition and post-state verification.
- Idempotent pull-request creation using a deterministic request marker.
- Required-check observation and exact-head merge.
- Clean local `main` fast-forward to an explicitly verified remote SHA.
- Reuse BCT work ownership, operation receipts and resource claims.

## Non-scope

- Deployment, service control, MCP and RCC migration.
- Repository creation, credential storage or permission administration.
- Background schedulers and a second workflow/receipt system.

## Acceptance

- Local focused and regression tests pass.
- A real BCT feature branch is pushed through the new capability.
- A real PR is created through the new capability, CI succeeds, and the exact PR head is merged once.
- Local `main` is synchronized to the verified merge SHA through the new capability.
- Existing ACT/MCP/RCC runtime remains unchanged.
