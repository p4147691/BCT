# BCT contributor map

Read `docs/DESIGN.md`, `PROJECT_HANDOFF.md`, and the relevant execution plan before changing BCT.

## Source of truth

- Repository: `p4147691/BCT`
- Default branch: `main`
- Local development checkout: `D:\PROJECTS\BCT`
- BCT source and tests live in this repository. ACT runtime is not the BCT source tree.

## Current boundary

- Implemented and accepted: core identity/policy/operation store, bounded file read/write, Python test,
  Git commit, and GitHub integration V1 (exact push, idempotent PR, CI-gated merge, verified-main sync).
- Implemented and live accepted: deployment/service V1 (named exact-file profile, immutable release,
  exact process ownership and health, idempotent control, rollback) at `D:\BCT\runtime`, port 18790.
- Implemented and live accepted: MCP V1 (same-process Streamable HTTP, bearer authentication,
  catalogue generated from real capabilities, common work/operation receipts) at
  `http://127.0.0.1:18790/mcp`; Codex server name `bct`.
- Unmigrated: RCC/Chrome extension.
- Keep current ACT, MCP, RCC, Chrome profile and bindings operational while features are migrated.
- Do not claim an unmigrated feature is compatible or live accepted.

## Development

Run:

    python -m pip install -e .
    python -m unittest discover -s tests -v
    python -m compileall -q src tests
    git diff --check

Use isolated disposable repositories for mutation acceptance. Never point a new BCT test at ACT live state or a protected user project.
