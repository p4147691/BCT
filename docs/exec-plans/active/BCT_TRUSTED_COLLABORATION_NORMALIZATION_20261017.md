# BCT trusted collaboration normalization

## Goal

Complete ordinary Manager/Worker collaboration on the existing BCT Core,
SQLite and RCC paths.  This is not a new security platform.  `D:\BCT` remains
the operating root and protected-path migration is deferred.

## What actually blocked normal use

The current Policy already treats read, write, test, execution and Git/GitHub
operations as normal user-scoped work.  Principal ownership, Work roots and
actions do not request repeated approval; they keep one project request from
escaping into another.

Two code boundaries did block the intended workflow:

1. Schema 2 recovery required every exact Work ID in deployed static config.
   A fresh collaboration therefore needed config editing, deployment and a
   Core restart before it could run.
2. Worker assignment metadata accepted only `read`, even when the user-scoped
   Work and current Policy already allowed ordinary development actions.

## Minimal contract

- `manager_wake_receipt_v2_enabled` remains one global emergency stop and
  defaults to false.
- The static Work allowlist is removed.
- A session stores `wake_receipt_mode` at creation.  Sessions created while the
  global switch is off use `LEGACY_RETURN_V1`; sessions created after an
  intentional activation use `RCC_RESULT_POLL_V1`.
- Existing databases add the column with the legacy default.  Settings changes
  and restarts cannot reinterpret an old session or wake.
- Manager recovery and Worker dispatch select only sessions pinned to the
  durable mode, in addition to existing current Work, Policy, epoch, lease,
  attachment and exact receipt checks.
- Trusted Worker assignments may carry normal project development actions:
  read/write/test/verify, bounded execution/process sessions, Git/GitHub work,
  inspection and monitoring.  Deploy, service control, credentials, delete,
  browser control and orchestration authority are not delegated automatically.

## Safety retained

SQLite transactions, deterministic IDs, resource claims, assignment and
Manager epochs, leases, exact RCC attachment/binding verification, result hash,
ACK separation and UNKNOWN no-resend remain unchanged.  The protected RCC Host
may remain installed, but protected runtime migration and further ACL work are
not prerequisites for collaboration.

## Acceptance sequence

1. Focused and full regressions, exact-head CI and code review.
2. Merge without changing LIVE.
3. One explicit operational approval covering exact-main Core deployment,
   enabling the global switch, and a fresh isolated Manager + two Worker E2E.
4. Prove two independent results, Manager synthesis, one FOLLOW_UP, COMPLETE,
   durable receipts/ACKs, no duplicate sends, restart recovery and Manager
   takeover continuity.
5. Only then run one ordinary code-analysis/edit/test task in a real project.

Historical UNKNOWN, Claim, Issue #111 and `consumed_at` rows are evidence only;
they are never retried, released, rewritten or reused by this plan.

## Local verification pitfall

The developer Python installation has an editable `D:\BCT\source\src` entry.
Running discovery from another worktree without installing that worktree or
placing its `src` first on `PYTHONPATH` mixes new tests with the old checkout.
That produces false missing-column and legacy-contract failures. Local evidence
must first print `bct.__file__` and prove the exact worktree; the incorrect mixed
run is not a regression result and must not be repeated.
