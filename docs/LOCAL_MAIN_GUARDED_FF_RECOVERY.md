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
