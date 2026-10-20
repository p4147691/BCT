# BCT contributor map

Read `docs/DESIGN.md`, `PROJECT_HANDOFF.md`, and the relevant execution plan before changing BCT.

## Source of truth

- Repository: `p4147691/BCT`
- Default branch: `main`
- Local `main` checkout: `D:\BCT\source` (a synchronized working copy, not a second authority)
- Runtime releases and durable state remain separate under `D:\BCT\runtime` and `D:\BCT\data`.
- BCT source and tests live in this repository. ACT runtime is not the BCT source tree.

## Current boundary

- `BCT_PLATFORM_PACKAGE_V1` is live accepted. The BCT repository owns core identity/policy/receipt,
  file and Git workflows, GitHub integration, deployment/service control, MCP, RCC control,
  Python/PowerShell/argv execution, persistent sessions, and the BCT Monitor.
- Runtime is `D:\BCT\runtime`, data is `D:\BCT\data`, and the same BCT process serves health,
  MCP (`http://127.0.0.1:18790/mcp`) and Monitor (`http://127.0.0.1:18790/monitor`).
- The DesktopWindow Monitor Chrome component remains installed at its existing live location; BCT owns
  its accepted source baseline and validation while the independent BCT Monitor is the core status UI.
- ACT is a rollback/legacy compatibility installation. BCT runtime must not import ACT modules or
  dispatch a mutation through ACT.
- Project-specific ADC utilities are not platform subsystems. Run them as ordinary project workflows
  through BCT execution when needed instead of copying every historical tool into BCT core.
- RCC Rebuild V2-1~6 is complete. LIVE RCC is the exact 46-file RC2 payload; Simple Relay,
  read-only diagnostics and existing error contracts are active. Browser management Adapters remain
  optional source/payload and must not be connected to relay authority without a separate design and
  acceptance. The retained rollback is
  `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-rc2-20261020-184845`.

## Development

Run:

    python -m pip install -e .
    python -m unittest discover -s tests -v
    python -m compileall -q src tests
    git diff --check

Use isolated disposable repositories for mutation acceptance. Never point a new BCT test at ACT live state or a protected user project.

## Default delivery flow

Unless a request explicitly narrows the scope, use the durable delivery flow in
`.cursor/rules/bct-delivery-flow.mdc`: set the scope and protected operations
first; run local checks as one recipe; use one coherent PR and exact-head CI;
deploy the exact SHA; then advance E2E in ordered gates. Preserve UNKNOWN
effects and protected claims, diagnose failed external effects before retrying,
and parallelize only read-only or independently prepared work.

## Shared LIVE mutation ownership

- A manager may prepare several candidates in parallel, but it must name exactly one active
  `LIVE owner` Work for each shared runtime target (Core, tunnel, RCC, or VTL Agent) before the
  first state-changing operation. Other Works remain read-only or preparation-only for that target.
- A timer, heartbeat, chat, or local helper is never a second owner. An approved local one-shot
  executor may act only as the named Work's bounded executor and must be pinned to the exact target,
  operation ID, payload SHA, expected pre-state, rollback, and expiry.
- Prefer event/condition-triggered one-shot execution over periodic chat polling. It checks the
  declared conditions once, applies at most once, writes a durable result, and exits. A failed or
  UNKNOWN mutation is reconciled from receipts and postconditions; it is not blindly replayed.
- Ownership ends only after the durable result and postcondition are recorded, or after an explicit
  handoff records the successor. Do not reload, deploy, or schedule the same LIVE target from two
  chats while either owner or executor is active.
