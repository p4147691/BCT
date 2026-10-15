# BCT Browser Bridge PR3 — peer adapter checkpoint

Status: `PR3E_CI_ACCOUNT_BLOCKED`.

This plan is a source and review checkpoint for the independent Browser Bridge.
It is not part of RCC, does not use the RCC Native Host, and does not authorize
changes to BCT LIVE, Chrome, HKCU, existing credentials, Issue #111, or
historical UNKNOWN/Claim records.

## Accepted foundations

- PR #128 rebuilt the PR3-a Core-only adapter after the original implementation
  was reverted. Its result digest, current assignment/attachment fencing, and
  ACK transaction boundary are covered by the isolated tests.
- PR #129 added the fixture-only capability grant boundary; it is not a browser
  credential issuer.
- PR #130 added strict inner JSON ingress with Core-owned clock and lease
  fencing.
- PR #131 added a fixture-only peer proof before PR3-c. Its exact main CI
  passed. Caller-supplied launcher metadata remains non-attesting metadata.

These foundations are Core-side contracts and fake-transport tests. They do
not prove Chrome completion observation, browser delivery, real receiver ACK,
or a usable normal-ChatGPT manager loop.

## Current checkpoint: PR #132

PR #132 (implementation commit `17d08f41067ed6832e31fb71d757fbd30d758d48`) adds the transport-neutral
PR3-e outer peer adapter. It is disabled unless a caller explicitly supplies a
`PeerBindingProvider`; it never accepts the existing Browser Bridge read-only
MCP bearer. The adapter validates a canonical outer frame, an HMAC over exact
PR3-c bytes and the peer binding, binding generation, launcher metadata and
strictly increasing sequence. Sequence reservation occurs before inner ingress
and no secret is persisted in SQLite.

Focused inherited bridge tests, local full unittest, `compileall`, and
`git diff --check` passed in the isolated worktree. No runtime resource was
created or changed.

GitHub Actions run `38696516437` did not execute any workflow step. GitHub
reported an account payment/spending-limit gate; a rerun failed identically
before runner setup. This is external CI evidence missing, not a source-test
failure. Do not merge PR #132 until its current exact head has a completed CI run.

## Required rechecks, in order

1. Restore GitHub Actions account eligibility, rerun CI for the unchanged
   exact PR #132 head, and distinguish runner startup from test failure.
2. Perform an independent read-only review of PR #132: outer canonical parsing,
   binding generation rotation, replay reservation, provider failure behavior,
   secret/error non-disclosure, and the PR3-c handoff.
3. Merge only after review and exact-head CI pass. Deployment is explicitly not
   part of this checkpoint.
4. Before a real listener, separately design and approve an OS-backed peer
   credential lifecycle (provision/rotate/revoke/recovery) plus protected local
   IPC/process identity. There is no safe existing credential-store component
   to reuse as of this checkpoint.
5. Only then integrate a real Host transport and validate it in isolated
   Chrome. Current regular Google Chrome cannot automate unpacked extension
   loading with `--load-extension`; use Chrome for Testing or an explicit
   isolated-profile Load-unpacked workflow.

## Separate tracks — do not conflate

- Issue #111 and existing RCC UNKNOWN/Claim handling remain governed by their
  own active plans. They are not inputs to PR3 and must not be replayed or
  released to unblock this work.
- The desired ordinary-ChatGPT manager/node wake-and-result workflow is tracked
  separately by GitHub issue #86. PR3 Core contracts are prerequisites, not an
  implementation of that user-interface workflow.
- Hosted timing/runner performance follow-up remains issue #82. The current
  Actions account gate is an external billing condition, not measured runner
  contention or a BCT code bottleneck.
