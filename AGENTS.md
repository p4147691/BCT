# BCT contributor map

Read `docs/DESIGN.md`, `PROJECT_HANDOFF.md`, and the relevant file under `docs/exec-plans/active/` before changing BCT.

## Source of truth

- Repository: `p4147691/BCT`
- Default branch: `main`
- Local development checkout: `D:\PROJECTS\BCT`
- BCT source and tests live in this repository. ACT runtime is not the BCT source tree.

## Current boundary

- Implemented first slice: core identity/policy/operation store plus bounded file read/write, Python test, and Git commit.
- Unmigrated: GitHub integration, deployment/service control, MCP catalogue/server, RCC/Chrome extension.
- Keep current ACT, MCP, RCC, Chrome profile and bindings operational while features are migrated.
- Do not claim an unmigrated feature is compatible or live accepted.

## Development

Run:

    python -m pip install -e .
    python -m unittest discover -s tests -v
    python -m compileall -q src tests
    git diff --check

Use isolated disposable repositories for mutation acceptance. Never point a new BCT test at ACT live state or a protected user project.

