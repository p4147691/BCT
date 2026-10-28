# BCT instruction authority

This document classifies instruction-like artifacts. It is descriptive; the
common policy itself lives only in `D:\BCT\source\AGENTS.md`.

## A. Canonical common instruction

- `D:\BCT\source\AGENTS.md`
- One current common policy for BCT source work.
- Must contain durable rules, not current version/generation/incident facts.

## B. Module-specific rules

- Example: `modules/monitor/extension/AGENTS.md`.
- May add local file ownership, build, runtime and E2E requirements.
- Must not redefine BCT-wide source authority, Work semantics, UNKNOWN policy,
  integration order, or supervisor permissions.

## C. Thin editor adapters

- `.cursor/rules/bct-delivery-flow.mdc`
- Only points the editor/agent to the canonical `AGENTS.md` and stale-instruction
  check. It is not another policy source.
- `bct-persistent-supervision.mdc` is retired by this consolidation; its durable
  useful rules moved into `AGENTS.md`.

## D. Runtime/project settings

- `D:\BCT\runtime\config\relay-message-settings.json`
- `D:\BCT\data\mcp_tools.toml`
- `bct.toml` runtime/deployment/policy configuration.

These are validated machine-readable settings. They may affect presentation,
routing choices, tool catalogue or deployment configuration, but do not replace
the common AI operating policy and do not grant capability beyond BCT Work/
Operation enforcement.

## E. Machine enforcement

Examples: BCT policy, Work ownership, expected SHA checks, resource claims/
leases, durable Operation receipts, deploy guards, merge guards and exact route
identity checks in `src/bct/**`.

This is the strongest layer. A string inside source code is not automatically
an enforcement rule; only executed checks/fences are.

## F. Compatibility instructions (retired runtime files)

The former runtime files `manager-relay-note.txt` and `worker-relay-note.txt` are retired. Orchestration protocol/safety wording is self-contained in source, and current editable Delivery wording belongs in `relay-message-settings.json`. Historical copies may be archived as evidence but must not be restored to `runtime/config` as instruction sources.

## G. Reference/history only

- `docs/**` design/guide/exec-plan documents unless explicitly named above.
- `PROJECT_HANDOFF.md`, `D:\BCT\data\*HANDOFF*`, checkpoints, audit reports,
  deployment receipts, backups and old Worktree copies.
- They preserve evidence and context. They do not outrank current main policy
  or current machine state.

## H. Drafts in feature Worktrees

A Worktree may intentionally contain a newer or historical instruction proposal.
That proposal is not common policy until integrated into local main.

Before editing an existing Worktree use:

`python D:\BCT\source\scripts\check_instruction_authority.py --worktree <WORKTREE> --strict`

`STALE_INSTRUCTIONS` means "review current canonical policy before continuing",
not "overwrite branch files".

## Retirement rule

An instruction-like artifact may be removed only after its active caller is
identified and migrated or retired. Do not delete compatibility files solely
because a newer path exists.
