# Relay Control vs Chain Message: responsibility boundary

## Canonical distinction

**Relay Control** (`bct_relay_control`, `src/bct/relay_executor.py`) is a bounded adapter for registered, authorized BCT operations. A caller supplies a purpose and scope; the fixed registry selects a known handler. The Work must separately authorize the underlying capability. Settings never grant authority, create arbitrary handlers, or create AI plans.

**Chain Direction** records the human/Manager's intent and direction. **Chain Execution Plan** (`bct_set_execute_plan`, `src/bct/chain_execution_plan.py`) stores a Worker B-authored plan bound to the started direction/task, preserving the original plan and SHA-256. **Chain Message** coordinates the work lifecycle; **Task Run** handles authorized execution. Storing a plan does not execute it.

## Do not conflate

- Do not rename Relay Control to Chain Message, or describe Chain Execution Plan as a Relay Control configuration.
- Do not imply Relay Control authors plans, chooses next tasks, or independently decides Manager/Worker roles.
- Do not infer that `relay_control` is a required Chain dependency merely because a tool or Work advertises the capability. Prove any dependency from actual code/call receipts.
- Do not use Relay Control as an alternative public message transport unless its exact supported contract and permissions explicitly require it. Preserve the canonical public message commands and idempotency/UNKNOWN rules.
- Chain plan storage must remain distinct from delivery, ACK, Task Run, and Manager return. Each requires its own evidence.
- Do not infer successful Chain E2E from the presence of registered MCP tools.

## Concrete code anchors

- `src/bct/relay_executor.py`: fixed purpose/handler registry and delegated Work capability.
- `src/bct/relay_settings.py`: scoped Relay Control settings/preview.
- `src/bct/chain_direction.py`: Chain Direction storage.
- `src/bct/chain_execution_plan.py`: B-authored plan persistence and hash.
- `src/bct/mcp_server.py`: distinct public tool contracts.

## Safe review gate

When changing either feature, inspect the other only for real call edges. Keep unrelated semantics untouched; record explicit evidence if an integration is proposed. Changes to this document alone do not modify LIVE or enforce runtime behavior.
