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
- Implemented and locally verified: deployment/service V1 (named exact-file profile, immutable release,
  exact process ownership and health, idempotent control, rollback). Do not mark it live accepted until
  `D:\BCT\runtime` evidence is recorded.
- Unmigrated: MCP catalogue/server, RCC/Chrome extension.
- Keep current ACT, MCP, RCC, Chrome profile and bindings operational while features are migrated.
- Do not claim an unmigrated feature is compatible or live accepted.

## Development

Run:

    python -m pip install -e .
    python -m unittest discover -s tests -v
    python -m compileall -q src tests
    git diff --check

Use isolated disposable repositories for mutation acceptance. Never point a new BCT test at ACT live state or a protected user project.
