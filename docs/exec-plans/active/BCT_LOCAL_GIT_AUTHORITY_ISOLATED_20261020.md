# BCT Local Git Authority + Nonblocking GitHub CI — isolated candidate

Status: ISOLATED_TESTED / NO_GITHUB_PUSH / NO_MAIN_MERGE / NO_LIVE_DEPLOY

## Existing evidence reused
- Original isolated Git prototype: Work \`BCT-LOCAL-GIT-AUTHORITY-ISOLATED-20261020-01\`
  Operation \`local-origin-synthetic-worktrees-main-live-remote-ci-v1\`, FINISHED/APPLIED.
- Source checkout at study start: local and GitHub main
  \`77867ccfbf9bf76d00f862bb45873771baf01b39\`.
  It may change independently; recheck exact heads at every transfer.
- Running BCT Core release baseline: \`7df4f06a5e9390175392e341e567b02631fa6ce5\`;
  pre-existing unresolved Claims: 22.

## Code changes (in isolated standalone clone only)
- No new MCP tool or public argument schema. Existing \`bct_git_commit\`
  accepts \`operation="merge_local_main"\` **only** when explicit
  \`[git_authority]\` mode \`local\` is configured for the exact root/repository.
- BCT coordinator continues to own Work/Principal/Policy, operation_id digest,
  resource Claims, receipt state and UNKNOWN no-retry.
- Merge request binds exact local main SHA, exact local feature branch SHA,
  repository identity, clean \`main\` worktree and explicit message.
  Independent resource claims include \`git-index\`, \`git-worktree\` and
  the existing \`github-base\` namespace. A \`git merge-tree --write-tree\`
  preflight rejects ordinary content conflicts without touching main.
  A successful merge verifies exact two parents and predicted tree SHA.
  Uncertain post-effects remain UNKNOWN without automatic replay/abort.
- For the selected BCT repository, \`github_pr_merge\` is denied in local mode;
  \`github_sync_main\` is denied at the canonical local source root.
  Other repository workflows remain unaffected.
- \`github_push\` remains the already deployed fast-forward-only publishing
  capability. A **pre-dispatch** Git remote connection error now reports
  NOT_APPLIED instead of incorrectly recording an UNKNOWN side effect.
  Post-dispatch uncertainty still retains UNKNOWN + Claim; no forced push.
- Existing DeployFeature unchanged: clean local main, expected SHA, tracked
  policy and Git blob/manifest checks remain authoritative.
- Normal/github mode defaults unchanged until an explicit migration.

## Proposed configuration (not installed)
Add ONLY to the versioned BCT policy after isolated acceptance and ownership handoff:

    [git_authority]
    mode = "local"
    repository = "p4147691/BCT"
    source_root = "D:\\BCT\\source"

This does not rename any directory, overwrite BCT SQLite, modify RCC or
introduce another scheduler, credential store or Git remote.

## Evidence — BCT Core tests and fake runtime
- New focused unit tests: 9 PASS, including two independent agent worktrees,
  idempotent merge receipt, single-owner Claim conflict, exact HEAD rejection,
  preflight merge conflict, old GitHub authority route rejection, actual BCT
  fake-runtime deployment and executable release E2E, offline preflight
  publish NOT_APPLIED, non-force publish, divergent remote rejection and
  post-push CI failure preservation.
- Existing GitHub integration, deploy, development flow and verification test
  modules: 48 tests across four modules, exit code 0; verification receipt
  \`local-authority-existing-critical-regressions-v1\` FINISHED/APPLIED.
- No real GitHub remote used; local bare Git repository stands in for GitHub.
  Only the \`_remote_matches\` GitHub URL identity check was mocked for the
  stand-in push tests. Production push URL validation remains unchanged.
- Fake runtime uses BCT's actual DeployFeature with \`restart=false\`,
  immutable exact local SHA, hashed manifest and executable release file.
  It does **not** start or reload real BCT Core, RCC, Supervisor, tunnel or LIVE.
- GitHub CI failure is simulated as an isolated failing command; this proves
  no automatic rollback of local LIVE. Production GitHub status/notification
  handling is not implemented by this slice.

## Transition prerequisites and cautions
1. Assign **one** Local Main Merge Owner, one Deploy Owner and one GitHub
   Publisher. Stop other GitHub-main merge/sync writers for BCT before cutover.
2. Verify current local/GitHub main, source cleanliness, active Works,
   unresolved Claims, exact LIVE pointer and accepted backups. Never overwrite
   a changed remote Git ref or assume the original 22-Claim snapshot is current.
3. Bootstrap requires a controlled *existing* Git integration operation to
   land the new code/config in local main before the new local merge mode is
   available in LIVE. Do not treat deploying the isolated branch as permission
   to skip preflight or owner handoff.
4. Use the existing deployment profile for exact verified local commit only
   after separate authorization; expect immutable release, current.json,
   manifest and service fingerprint.
5. Publish local main to GitHub using existing \`github_push\` exact source
   and expected remote SHA; failures do not gate local execution.
   However SYNC_PENDING/SYNC_CONFLICT require distinct external status tracking
   and a recovery workflow before production adoption. A failed push after
   dispatch must not be falsely treated as NOT_APPLIED.
6. GitHub Actions remains an independent post-push audit. An AUDIT_FAILED
   SHA requires investigation/rollback decision, not automatic effect replay.
7. This work does not approve a production policy cutover, PR/main mutation,
   GitHub CI run or a live E2E. Preserve old claims and receipts.

## Acceptance boundary
Candidate only: tests PASS and fake deployment PASS.
Actual authoritative-source migration, sharing remote, deployment, live E2E,
and real hosted GitHub CI are NOT PERFORMED.
