# BCT GitHub integration V1 — completed

Status: ACCEPTED

## Delivered

- `github_push`: clean tree, exact local HEAD, exact prior remote SHA/absence, repository remote match,
  fast-forward only, remote post-state verification.
- `github_pr_create`: exact remote head SHA, deterministic BCT request marker, conflicting open-head denial,
  response-loss reconciliation.
- `github_pr_status`: exact PR head and named required-check evidence.
- `github_pr_merge`: exact head, every required check successful, post-merge state and merge SHA verification.
- `github_sync_main`: clean local `main`, exact prior local SHA, exact verified remote SHA, ff-only update.
- All capabilities reuse the existing BCT work owner, policy, operation receipt and resource claim.
- GitHub credentials remain in the official `gh` credential store and are not persisted by BCT.

## Tests

- Local full suite after follow-up regression: 19/19 PASS
  (14 core/development tests + 5 GitHub focused tests).
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- Negative coverage: stale remote SHA, dirty sync tree, missing required check, duplicate operation,
  cross-operation duplicate PR/merge, and lost create/merge response reconciliation.

## Real GitHub acceptance

- Source commit: `cd48bd7a74cfa2ef2f8c3f2292efce336763645e`.
- BCT `github_push` created `feature/github-integration-v1` at that exact SHA.
- Repeating the same push operation returned its durable result without a second dispatch.
- BCT `github_pr_create` created PR #2; a new operation with the same request returned PR #2 and did not
  create another PR.
- GitHub Actions run `38241115179`, Windows job `test`: PASS.
- BCT `github_pr_status` verified exact head and successful `test` check.
- BCT `github_pr_merge` merged once to `9140bc07d7e0fac9b809a208818a20f6bf094653`.
- A second merge operation returned `already_merged=true`; it did not perform a second merge.
- BCT `github_sync_main` fast-forwarded local `main` from
  `934c69fd39032b0dea3981c922f8527441935de5` to the exact merge SHA.
- Merge-main push CI run `38241278661`: PASS.
- Post-follow-up local full suite: 19/19 PASS; local `main == origin/main` and worktree clean.

## Follow-up defect resolved during adoption

The central registry repository rejected its first structured commit before changing HEAD because that checkout
had no local Git author identity. BCT originally retained the resource claim even though exact HEAD and dirty-set
evidence proved the commit was not applied. The Git commit feature now releases a claim only when both facts are
re-verified after failure; any unavailable or unexpected post-state remains `UNKNOWN` and keeps the claim.

- Fix PR: BCT #4.
- Fix merge: `c770eb5595856776db63fbb085ea148f731bdb92`.
- Regression: two consecutive confirmed pre-commit rejections can be evaluated without a stale claim, while
  the repository HEAD remains unchanged.
- Central recovery registry status: BOOTSTRAP PR #23, merge
  `f478d5e75c57e4e8455914b503d1c5f5fee41546`, doctor PASS.

## Bootstrap observation

Before local main contained the new feature, its editable Python import could not call `github_sync_main`.
The accepted feature commit was therefore executed from an immutable detached worktree to perform the first
ff-only transition. No source or remote state was changed by the failed preflight calls. The next deployment/
service feature must provide a stable installed runtime separate from the checkout it updates, so future updates
do not need this bootstrap technique.

## Preserved boundaries

- Existing ACT, MCP, RCC, Chrome profile, tabs, role bindings and services were not changed.
- No repository permission, token, credential, runner or branch-protection setting was changed.
- Deployment/service, MCP and RCC remain unmigrated.

## Next

Implement the deployment/service feature with exact source/runtime SHA, backup, atomic replacement,
all-or-nothing rollback, minimal restart and health verification. Keep ACT live until a bounded BCT transition
is accepted.
