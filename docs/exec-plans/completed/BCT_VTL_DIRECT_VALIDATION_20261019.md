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
- The initial `D:\TOOLS\VTL\current.json` installation pointed to that exact
  merge; its manifest hash matched and the release entrypoint existed.
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

## Post-acceptance cold-start correction

- A later documentation-only sync exposed a non-interactive cold-start defect:
  Node emitted the Chromium executable path as UTF-8 while Windows PowerShell
  decoded it through the active legacy code page. The non-ASCII user profile
  became invalid, so operation
  `bct-vtl-direct-live-af1c4fd9-c332ae84-browser-fast` finished once as
  `FAILED / INFRA_ERROR / VTL_RESULT_MISSING`. That exact operation was
  preserved and not retried.
- VTL PR #20 transports that path as ASCII Base64 with explicit UTF-8 decode,
  moves the browser selftest to the existing VTL self-hosted runner, removes
  duplicate feature-branch push/PR validation, and prewarms each exact release
  before publishing `current.json`. It merged as
  `6e75ab689c62731e98a50f2786ead92efac98d06`.
- Merged-main browser selftest `39175862089`, validation `39175862213`, and
  runtime sync `39175862108` passed. The installed manifest verifies and its
  prewarm result is PASS in 962 ms.
- Final authenticated MCP operation
  `bct-vtl-direct-live-af1c4fd9-6e75ab68-browser-fast` returned
  `FINISHED / APPLIED / PASS` in 2.078 seconds (3.525 seconds external wall
  time), and duplicate submission returned the original receipt. Evidence is
  `D:\BCT\data\vtl-evidence\3b03c0e2ca7812e9591d86300e4706fd23be06c1b2df9f691289866d45ab090f`.

## Code-page-neutral follow-up

- VTL machine results remain explicit UTF-8 JSON files; ambiguous native
  stdout is never used to decide PASS/FAIL or locate evidence.
- BCT now captures child output as bytes, recognizes UTF BOMs, tries strict
  UTF-8 first, then the deployed Korean legacy encoding before the active
  Windows ANSI/OEM encodings. This keeps diagnostic logs readable whether the
  Windows UTF-8 system-locale option is on or off, including after a setting
  change, without changing that setting itself.
- Child Python tools receive process-local UTF-8 environment variables. No
  registry, system locale, language pack, reboot or global shell profile is
  changed.
- Focused decoder tests cover UTF-8, CP949, UTF-16 and UTF-32 streams. The first
  hosted run exposed that a US CP1252 host can permissively turn CP949 bytes
  into mojibake; CP949 was therefore moved ahead of the current ACP/OEM
  fallback. The exact failing revision was not retried.
- BCT PR #206 exact head `85f120c186fd2a71238c7bbd2168ba439166f096`
  passed CI run `39177425436` (four core shards, browser bridge and preflight),
  then merged as `c70f6d2ec7f346baeef10c83ffa29d039613f3b5`.
  Merged-main CI run `39177781086` also passed.
- Durable deployment operation `bct-vtl-direct-deploy-c70f6d2ec7f3-op`
  installed that exact release with manifest
  `51580b99aae7f696dd6f4b7f0a71d776b7ac46bc2678f829c47ca148b476c608`;
  Core became READY at generation 122.
- VTL docs closeout PR #22 merged as
  `37536df2b7f41b18b4efdb2601dd6191236b010b`. Its merged-main validation and
  runtime sync passed, the installed manifest re-hash matched, and prewarm was
  PASS. Authenticated operation
  `bct-vtl-direct-live-c70f6d2e-37536df2-browser-fast` returned
  `FINISHED / APPLIED / PASS` in 2.046 seconds; duplicate submission preserved
  the original receipt. Evidence is under
  `D:\BCT\data\vtl-evidence\7b805a587e0a5131c2af6458a039a0264af2198c2ec52c6b9db80e0118a30d1c`.
