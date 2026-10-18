# BCT direct VTL validation — 2026-10-19

Status: `IMPLEMENTED / LOCAL_FOCUSED_PASS / PR_AND_LIVE_PENDING`

## Goal

Let a normal ChatGPT or Codex conversation run the cheapest sufficient VTL
validation directly through BCT, without using GitHub Actions as the edit/test
loop. GitHub required checks remain the final independent candidate check.

## Boundary

- VTL installs clean Git-tracked source as an immutable release under
  `D:\TOOLS\VTL\releases\<source-sha>` and atomically advances `current.json`.
- BCT verifies the pointer, manifest hash, every tracked release file hash and
  required entrypoints before every dispatch.
- `browser` runs a project-owned browser-playwright scenario in Fast or Full
  mode. `profile` runs a project-owned VTL profile/scenario whose source path
  remains inside the BCT work roots.
- Each request is a background BCT operation with one runtime claim and an
  operation-derived evidence directory under `D:\BCT\data\vtl-evidence`.
- Assertion failure is an applied validation result (`status=FAIL`), distinct
  from runtime/result-contract failure (`FAILED / INFRA_ERROR`). Timeout is
  explicit and terminates the spawned process tree.
- No GitHub workflow is dispatched by this capability. No project-specific
  selector or expected result is added to BCT or VTL core.

## Verification plan

1. VTL PowerShell parse, installer idempotency, manifest hash and doctor.
2. BCT focused feature, MCP catalogue/background and deployment-profile tests.
3. Full BCT regression and exact-head PR CI.
4. Merge VTL first, install its exact merged main runtime, and run one direct
   browser Fast smoke outside GitHub Actions.
5. Merge/deploy exact BCT main, verify the live catalogue, then run the same
   direct smoke through authenticated BCT MCP and retrieve its final receipt.
6. Confirm no GitHub VTL workflow was created for the live direct smoke and
   preserve GitHub CI only as the repositories' final merge check.
