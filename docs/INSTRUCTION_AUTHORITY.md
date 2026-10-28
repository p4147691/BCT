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

## Boundary checks (isolated candidate; not a LIVE claim)

The common comparator remains `scripts/check_instruction_authority.py`.
`src/bct/instruction_preflight.py` invokes that exact script in strict
read-only mode; it does not maintain a second set of canonical rule contents.

- BCT `bct_work_create` observes instruction status for linked worktree roots
  inside the local BCT authority scope. Its returned `instruction_authority`
  is advisory: Work registration is an authorization record, not execution.
  Existing Work and unrelated repositories must not be blocked.
- Guarded `git_commit(operation="merge_local_main")` requires an attached,
  clean feature Worktree at the exact expected commit and a `MATCH` result
  before modifying shared main. Missing/unverifiable or stale instructions
  require review; no Worktree files are overwritten.
- A separately owned `bct_integration_queue` implementation must call
  `inspect_feature_branch(repository_root, feature_branch)` before a new
  submit and distinguish `MATCH` from `STALE_INSTRUCTIONS` / `UNKNOWN`.
  This candidate deliberately does **not** edit that feature branch.
  Do not report an active queue submission gate until that hook is integrated,
  tested and deployed.

A stale result is an exact-content difference, **not** a proven semantic
conflict. Manual review decides compatibility. This source-only candidate
requires independent tests, exact feature CI, local-main integration and
any affected Core LIVE acceptance by the designated integration owner.
