# BCT direct VTL validation — 2026-10-19

Status: `COMPLETE / MERGED / LIVE_ACCEPTED`

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

## Current evidence

- VTL PR #18 merged as `2480d2bd70a420c5300071ad51a541a13407b99b` after both
  exact-head validation runs passed. Merged-main validation, interactive runner
  Sandbox smoke and immutable runtime sync all passed.
- `D:\TOOLS\VTL\current.json` points to that exact merged SHA; its manifest
  hash matches and the release entrypoint exists.
- A direct non-Actions browser Fast smoke used the installed release, prepared
  dependencies once, and returned PASS with result evidence under
  `D:\BCT\data\vtl-evidence\direct-pre-bct-2480d2bd`.
- BCT focused feature/MCP/deployment/layout/CI tests passed. The complete local
  regression passed 757/757 in 347.814 seconds; compile and diff checks passed.
- BCT PR #203 exact head `0b79e72ce0bb4f9c1dea487cdb3793fa0885ab4b`
  passed CI run `39174274844` and merged as
  `af1c4fd9b1ca172c58ca09ebe44185ddda0e14b8`. Merged-main CI run
  `39174601320` also passed.
- Exact merged BCT main was deployed through the durable deployment operation
  `bct-vtl-direct-deploy-af1c4fd9b1ca-op`. LIVE is READY at generation 121,
  exposes 31 MCP tools including `bct_vtl_validate`, and uses manifest
  `aa0f6161d320f728f5ce647b93f34400a37c7db68ce24a1d57219078ed43052e`.
- Authenticated LIVE operation
  `bct-vtl-direct-live-af1c4fd9b1ca-browser-fast` ran the installed VTL release
  `2480d2bd70a420c5300071ad51a541a13407b99b` directly and returned
  `FINISHED / APPLIED / PASS`. VTL execution was 2.156 seconds and the external
  acceptance path was 3.800 seconds. Duplicate submission returned the same
  receipt without rerunning the scenario.
- Evidence is under
  `D:\BCT\data\vtl-evidence\7228e29fbe1e050704e1f7d87303af61c777b36902c625078b0f7a327b962ac9`.
  The scenario SHA-256 is
  `d94b9d8c1b6eb353fc050c33398958c27706a3695b3d0293bb58e9c8e8bd0373`.
  No VTL Actions run was created by this acceptance; the latest VTL runs remain
  the three merged-main runs created at `2026-10-18T22:39:08Z`.
