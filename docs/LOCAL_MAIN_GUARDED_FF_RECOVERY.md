# BCT guarded local-main fast-forward recovery (isolated proposal)

This is a bounded **recovery exception**, not an authority-mode change.
`D:\BCT\source` local `main` remains canonical; `github_sync_main`
and remote PR merge stay forbidden in local authority mode.

## Exact capability and request

Use the **existing** BCT `git_commit` capability within a user-scoped
`Work` owned by the calling principal and rooted at the exact canonical
source directory. A unique `Operation` receipt fences the effect.

```json
{
  "operation": "fast_forward_local_main_recovery",
  "path": "D:\\BCT\\source",
  "expected_head": "<verified current local main 40/64-character SHA>",
  "expected_remote_head": "<verified exact origin/main 40/64-character SHA>"
}
```

Do not submit an actual recovery operation until the designated single
integration owner has confirmed all relevant Work/Operation/Claim ownership,
the remote provenance, the desired local-main change, and its LIVE implications.

## Fail-closed preflight

1. `require_local_main` validates canonical local-mode authority, repo root,
   Work scope and remote GitHub repository identity.
2. An exact CLEAN `main` at `expected_head`; no detached branch or dirty files.
3. Only `origin`/`refs/heads/main`; exact `ls-remote` SHA equals
   `expected_remote_head` with one unambiguous ref.
4. Fetch only that ref, compare `FETCH_HEAD^{commit}` against the pinned SHA.
5. Prove old local HEAD is ancestor of that fetched exact remote commit.
   Divergence, missing objects, failed Git commands or remote drift all abort.
6. Immediately before the local effect recheck main HEAD, branch,
   clean status and exact current remote SHA.
7. Perform exactly one `git merge --ff-only <expected_remote_head>`.
   Verify exact post-head, clean main, no pending merge state.
8. Preserve UNKNOWN if effects cannot be proved; never replay with a new
   Operation ID merely to force success.

No force, reset, checkout, PR merge, remote push, service restart, Worktree
deletion, or Claim release is part of this operation.

## Evidence scope and outstanding actions

The isolated proposal includes Git preflight and local mock remote
regressions. The designated integration owner must review that this exception
is appropriate to reconcile GitHub remote-only merges before enabling it
on LIVE Core. Source/main/LIVE/Chrome/RCC are unchanged by developing this code.

## One-time bootstrap, before the new Core command exists

The exact source of this bootstrap is
\`scripts/bct_local_main_ff_bootstrap.py\` **in the pinned, tested feature Worktree**.
It uses the current Core's existing BCT \`execute\` capability as the outer
durable BCT Operation. Inside that process, it loads the feature source's
\`GitCommitFeature\`, then invokes **OperationCoordinator.run(capability="git_commit")**
on the *same live BCT store*, using a separate, exact inner Operation ID.
It never calls \`git merge\` directly and does not bypass the current policy.

The bootstrap uses Store's existing DB, **without startup schema migration**.
It validates that the outer \`execute\` Operation is RUNNING, belongs to the
same ACTIVE Work/Principal/Epoch, owns the current execution claim observation,
and both source and pinned feature Worktree are in Work roots.
The inner \`git_commit\` operation has the same resource keys and guard logic as
the approved feature code. Note: BCT resource Claims are currently observational;
they are **not independent mutexes**. Only one designated integration operator
may perform a shared-main effect, after checking active work and processes.

### Mandatory operator review (no automatic effect)

Before any execution, the supervisor must confirm:
- Candidate exact commit SHA and matching feature CI; no uncommitted bytes.
- The approved BCT Work has \`execute\` and \`git_commit\`, one owner, roots
  exactly covering source + the pinned feature Worktree; choose two unique IDs
  (outer execute, inner Git) and preserve both receipts.
- The actually running BCT policy is compatible with the reviewed local-source
  \`bct.toml\`; inspect \`git_authority\` and \`normal_actions\` and do not loosen
  permissions or override \`github_sync_main\`.
- Local source \`main\` is CLEAN at the expected original SHA; origin URL is
  EXACTLY the repository in policy; current remote main is at the pinned SHA;
  ancestry is proven and Work/Operation owners and concurrent Git effects are
  reconciled. Verify the remote head again immediately before execution.
- The one-time bootstrap changes **only** local source main. New PRs, CI
  publications or deployed LIVE may need reconciliation after this effect.

### Exact BCT execution recipe (supervisor-only, not run in this task)

Create/recover an exact Work via \`bct_work_create\`:
\`\`\`json
{
  "work_id": "BCT-LOCAL-MAIN-FF-BOOTSTRAP-APPROVED-20261029",
  "request_summary": "One-time supervised exact origin/main fast-forward",
  "roots": [
    "D:\\BCT\\source",
    "D:\\BCT\\worktrees\\bct-local-main-guarded-ff-n63-20261029"
  ],
  "actions": ["execute", "git_commit", "read"]
}
\`\`\`
Use **one** BCT \`bct_execute\` with the exact Work and frozen arguments below
and a unique \`operation_id\`, not raw Git, not an arbitrary shell. The inner
Operation ID MUST remain different and MUST be recovered, not reissued, on
an uncertain outcome.
\`\`\`json
{
  "work_id": "BCT-LOCAL-MAIN-FF-BOOTSTRAP-APPROVED-20261029",
  "operation_id": "n63-ff-bootstrap-outer-20261029-approved-01",
  "arguments": {
    "kind": "python",
    "cwd": "D:\\BCT\\worktrees\\bct-local-main-guarded-ff-n63-20261029",
    "script": "D:\\BCT\\worktrees\\bct-local-main-guarded-ff-n63-20261029\\scripts\\bct_local_main_ff_bootstrap.py",
    "args": [
      "--candidate-root", "D:\\BCT\\worktrees\\bct-local-main-guarded-ff-n63-20261029",
      "--canonical-root", "D:\\BCT\\source",
      "--policy-path", "D:\\BCT\\source\\bct.toml",
      "--state-db", "D:\\BCT\\runtime\\state\\state.sqlite",
      "--work-id", "BCT-LOCAL-MAIN-FF-BOOTSTRAP-APPROVED-20261029",
      "--outer-operation-id", "n63-ff-bootstrap-outer-20261029-approved-01",
      "--git-operation-id", "n63-ff-bootstrap-git-20261029-approved-01",
      "--expected-head", "b297083791156e5510cbb9ee7359a9a358e73aaa",
      "--expected-remote-head", "4819c29f5ad3390b62fda752653680990b75c418"
    ],
    "timeout_s": 120
  }
}
\`\`\`
The IDs and SHAs above are **examples grounded in the handoff**, not blanket
approval: refresh exact HEAD/remote and owner/operation state first.
A changed HEAD/remote needs a new reviewed plan, not a blind retry.

### Post-state and rollback discipline

1. Read the **outer** \`execute\` receipt and the **inner** \`git_commit\`
   receipt \`bct_operation_get\`. If either is RUNNING/UNKNOWN, preserve the
   original Operation ID, read actual source HEAD and other receipts, and
   **do not replay**.
2. Verify current main branch, CLEAN, exact expected target commit, remote
   unchanged and no MERGE_HEAD. Existing live Core need not change just to
   move the source ref; do not claim LIVE upgrade/acceptance until verified.
3. Save pre/post HEAD and exact receipts in a new checkpoint. The pre-FF
   commit is preserved as an ancestor in Git, even after success.
4. **There is no automatic Git main rollback**. A ref rewind would violate
   ancestry and could erase other actors' work; never \`reset --hard\`,
   \`push --force\`, branch deletion or blind checkout. If reversal is
   required, supervisor must evaluate affected source and deploys and prepare
   separate reviewed revert commits (or a guarded, specifically approved
   restoration plan), with separate Work/Operation/CI. If LIVE changed later,
   use its verified release rollback mechanism independently.
5. Continue PR #345 feature integration against the refreshed local main
   only after the bootstrap's exact outcome is confirmed and all owners
   reconcile outstanding dependent work. No automatic PR merge is included.
