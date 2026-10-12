# BCT contributor map

Read `docs/DESIGN.md`, `PROJECT_HANDOFF.md`, and the relevant execution plan before changing BCT.

## Source of truth

- Repository: `p4147691/BCT`
- Default branch: `main`
- Canonical local source checkout: `D:\BCT\source`
- Runtime releases and durable state remain separate under `D:\BCT\runtime` and `D:\BCT\data`.
- BCT source and tests live in this repository. ACT runtime is not the BCT source tree.

## Current boundary

- `BCT_PLATFORM_PACKAGE_V1` is live accepted. The BCT repository owns core identity/policy/receipt,
  file and Git workflows, GitHub integration, deployment/service control, MCP, RCC control,
  Python/PowerShell/argv execution and persistent sessions, Laya runtime integration, and the BCT Monitor.
- Runtime is `D:\BCT\runtime`, data is `D:\BCT\data`, and the same BCT process serves health,
  MCP (`http://127.0.0.1:18790/mcp`) and Monitor (`http://127.0.0.1:18790/monitor`).
- The DesktopWindow Monitor Chrome component remains installed at its existing live location; BCT owns
  its accepted source baseline and validation while the independent BCT Monitor is the core status UI.
- ACT is a rollback/legacy compatibility installation. BCT runtime must not import ACT modules or
  dispatch a mutation through ACT.
- Project-specific ADC utilities are not platform subsystems. Run them as ordinary project workflows
  through BCT execution when needed instead of copying every historical tool into BCT core.

## Development

Run:

    python -m pip install -e .
    python -m unittest discover -s tests -v
    python -m compileall -q src tests
    git diff --check

Use isolated disposable repositories for mutation acceptance. Never point a new BCT test at ACT live state or a protected user project.
