# BCT canonical operating instructions

This file is the **single canonical common instruction** for BCT source work.
It contains durable operating rules only. Current versions, generations,
installed payload hashes, live owners, and incident-specific decisions belong
in BCT state/receipts or a bounded handoff, not here.

## 1. Authority and storage

- Canonical BCT source: local Git `main` at `D:\BCT\source`.
- Feature development: isolated Git worktrees, normally under `D:\BCT\worktrees`.
- GitHub `p4147691/BCT`: review, CI, publication and backup remote. It never
  overrides a verified local-main decision. Publish accepted main fast-forward only.
- Runtime: `D:\BCT\runtime`. Durable project/working data: `D:\BCT\data`.
  Source, installed payload, running process and durable state are different things.
- Use current BCT status/receipts for live facts. Do not copy old version,
  generation, backup-path or deployment claims from this file or a stale worktree.

## 2. Terms

- **Work**: one durable BCT scope/authorization record. It is not a Worker node.
- **Worker/Manager**: a ChatGPT/Codex node that performs or manages work.
- **Worktree**: an isolated Git source directory for one candidate.
- **Operation**: one exact BCT action and its durable receipt.
- `Work.state=ACTIVE` is an authorization state, not proof that execution is running.

## 3. Instruction authority

Instruction precedence for common BCT work:

1. This file: common operating policy.
2. A nested `AGENTS.md`: module-specific additions only; it must not redefine
   common authority, Work semantics or global delivery policy.
3. Runtime settings such as `relay-message-settings.json`: message wording and
   project-specific presentation only; they do not grant execution permission.
4. BCT code/policy/Work/Operation/resource fences: actual machine enforcement.
5. Docs, handoffs, checkpoints, backups and old worktree copies: reference/history.

`.cursor/rules/bct-delivery-flow.mdc` is only a thin always-on pointer to this
file. There must not be a second independent common-policy Cursor rule.

Before modifying an existing worktree, run:

    python D:\BCT\source\scripts\check_instruction_authority.py --worktree <WORKTREE> --strict

If it reports `STALE_INSTRUCTIONS`, do not overwrite the worktree blindly.
Read this canonical file, preserve branch-specific work, and decide whether the
candidate needs a rebase/cherry-pick/manual reconciliation.

## 4. Default development boundary

- Inspect the current Work, receipts, expected source SHA and protected external
  effects before changing anything.
- Develop and test in an owned isolated worktree. Do not make ordinary feature
  edits directly in shared local main.
- Keep one coherent candidate with exact changed files, feature HEAD and focused
  regression evidence. Classify its integration lane before any shared effect:
  `LOCAL_FIRST` or `GUARDED_CI_FIRST`. Use exact candidate CI only when the
  guarded impact gate requires it; an unclassified boundary uses the guarded
  lane until its effects and rollback are understood.
- Project Managers normally stop at **READY_FOR_INTEGRATION**: verify the
  candidate and submit one durable integration request when the currently
  running Core exposes `bct_integration_queue`. If that tool is not live, retain
  the exact readiness evidence and explicitly report `QUEUE_NOT_LIVE`; never
  claim that a request was stored.
- A supervisor/coordinator is a traffic-management default, not an exclusive
  permission role. If the user directly appoints a Manager to integrate, that
  Manager may do so through the same BCT Work/Operation/resource fences.

## 5. Shared effects and delivery order

Serialize only the actual shared effect. Independent inspection, preparation
and unrelated repositories may proceed in parallel.

Every accepted candidate uses one of two explicit lanes.  `LOCAL_FIRST` is the
default only for a bounded, reversible change whose affected behavior is
covered locally and whose LIVE target has an exact backup/rollback path:

1. isolated implementation + focused affected tests;
2. guarded local-main integration with expected main/feature SHA and clean tree;
3. exact resulting-main verification;
4. guarded LIVE deployment and real E2E for **affected targets only**;
5. GitHub main fast-forward publication and CI audit after LIVE acceptance;
6. final reconciliation of exact source, installed/running state, publication,
   CI and receipts.  A later CI failure is an audit failure to investigate; it
   does not silently roll back an already accepted local/LIVE effect.

Use `GUARDED_CI_FIRST` when a change can create or misattribute an external
effect, weaken an identity or authorization fence, make rollback uncertain, or
changes Core/RCC/Native Host, protocol, durable DB/Claim/UNKNOWN semantics,
message delivery, credentials/security, or the deployment mechanism:

1. isolated implementation + focused and required regression tests;
2. exact candidate CI/review;
3. guarded local-main integration and exact resulting-main verification;
4. guarded LIVE deployment and real E2E for affected targets only;
5. GitHub main fast-forward publication and resulting-main CI audit;
6. final reconciliation of exact source, installed/running state, publication,
   CI and receipts.

Documentation-only or source-only work with no LIVE target skips the deployment
step.  GitHub/network unavailability does not invalidate verified local main,
but never use the local-first lane to bypass an applicable guarded impact gate.

Core, Monitor and RCC are separate deployment targets. A changed source-main SHA
does not by itself require redeploying an unaffected target.

### 5.1 CI runs asynchronously by default

- CI is an exact-SHA verification stream, not a reason to idle the whole task.
  After the required local affected checks pass, freeze the candidate commit,
  start CI, register `github_run_watch`/Inbox notification, and continue work
  that does not depend on that CI result or modify the same unstable boundary.
- Do not hold an interactive `gh run watch` or equivalent wait unless the next
  protected action is unsafe without that exact result. Poll or reconcile the
  registered receipt only at a dependency, integration, release or final-report
  boundary.
- Use Code Block Scan/Block Cards and changed-path contracts to identify the
  affected blocks. Run focused checks on small commits, checkpoint CI on a
  completed feature bundle, and full CI when the impact gate or repository
  contract requires it. Risk boundaries override a narrow scan result.
- A newer commit that contains an older candidate may become the active CI
  checkpoint when no separate acceptance receipt is required for the older SHA.
  Keep every result attributed to its exact SHA; never present an older success
  as proof for newer code.
- CI failure stops only work that depends on the failed boundary. Preserve the
  evidence, repair that line, and continue unrelated work. A CI success marks
  only that SHA as verified; it does not prove deployment or LIVE acceptance.
- `GUARDED_CI_FIRST` still blocks its protected integration/deployment boundary
  on exact candidate CI. `LOCAL_FIRST` may deploy after its local and rollback
  gates, while GitHub CI continues as the documented follow-up audit.
- Final reports separate local affected checks, candidate/checkpoint CI,
  integrated local main, GitHub main, deployed release and physical LIVE E2E.

## 5A. Chain Recipe is the default execution route

- When the user assigns an implementation, inspection, repair, verification,
  deployment, or other executable BCT task, use Chain Recipe as the default
  coordination and continuation route without requiring the user to name it.
- Treat ordinary requests such as "do this", "fix this", or "continue" as
  selecting the Chain Recipe route. Create a bounded Work, resolve fresh exact
  Manager/Worker or Supervisor identities, and preserve the normal receipts,
  response watch, return-to-Manager, UNKNOWN and no-replay contracts.
- Do not use Chain Recipe only when the user explicitly requests an exception,
  such as "do not use Chain Recipe", "work only in this node", or a named
  alternative execution route. Follow that exception only for the requested
  scope; it does not change the project default.
- A question, explanation, status request, or design discussion with no assigned
  execution is not forced through Chain Recipe. Once the user asks to perform
  the work, the default above applies.
- If the exact Chain Recipe route is unavailable, ambiguous, paused, or unsafe,
  do not silently substitute another execution route. Preserve current receipts
  and report the exact blocked stage or ask for the necessary target choice.

## 6. UNKNOWN, retries and completion

- Never replay an `UNKNOWN` external effect under a new Operation ID just to make
  progress. Read the original receipt and current external state first.
- Never erase UNKNOWN/Claim history or mass-change Work states to make dashboards
  look clean.
- Separate request registration, message delivery, ACK, merge, verification,
  LIVE acceptance and GitHub publication; one is not proof of another.
- Report `COMPLETE` only after the user's requested acceptance scope is actually
  satisfied. Otherwise report the verified progress, blocker and exact next step.
- User-observed physical acceptance is evidence; unobserved UI behavior is not.

## 6A. Evidence-based measurement (current user policy)

- A measurement is not proof unless the observation itself is verified. Missing,
  ambiguous or failed observation is `MEASUREMENT_UNVERIFIED`: keep diagnostic
  evidence, do not infer target failure, and do not turn it into an external
  mutation `UNKNOWN` or a development/dispatch stop condition.
- Platform-recognized observation-only operations create **no resource Claim**.
  This is decided by the BCT feature contract, never by a caller-supplied label.
  Fix the faulty measurement path and repeat it separately if a trustworthy
  measurement is necessary; ordinary unrelated corrective work continues.
- A failed CI/test measurement is actionable diagnostic data, not an authority
  to block unrelated fixes. Exact acceptance gates still apply to the actual
  protected merge, release, destructive effects and same-target mutations.
- Historical receipts and Claims remain immutable audit evidence; do not bulk
  clear or misrepresent them. A truly ambiguous *mutating* effect still requires
  original-receipt verification, duplicate-effect fencing and applicable approval.
- Ordinary repeated chat messages should be idempotently handled by receivers
  where possible; never blindly replay an unverified prior submission.

## 7. Worktree lifecycle

- Before creating a new worktree, look for an owned reusable clean worktree for
  the same Work.
- Never broad-prune/reset/clean user worktrees.
- A worktree may be retired only after its candidate is contained in accepted
  main and current checks prove: clean tracked/untracked state, reviewed ignored
  files, no exact Work/unresolved Operation/process reference, and no recovery role.
- Use non-force `git worktree remove <exact path>` and retain branch, commit and
  durable receipts unless a separate reviewed action says otherwise.
- Read-only hygiene tool:

    python scripts\bct_worktree_hygiene.py --repo D:\BCT\source --worktrees-root D:\BCT\worktrees --state-db D:\BCT\runtime\state\state.sqlite

A review candidate is not automatic deletion approval.

## 8. Module and runtime boundaries

- Module-specific rules belong in that module's nested `AGENTS.md`.
- Message wording/project overrides belong in
  `D:\BCT\runtime\config\relay-message-settings.json`.
- Retired `manager-relay-note.txt` / `worker-relay-note.txt` runtime files are
  not message-policy sources. Do not recreate them; current editable message
  wording belongs in `relay-message-settings.json`.
- Do not delete or rename internal `node-sync` merely to simplify user-facing flow.
- ACT and retired compatibility paths must not silently regain BCT authority.

## 9. Natural-language ChatGPT delivery routing

- Interpret "새 창 열고 메시지 보내줘" as `create-chat-window` followed by `send-message` using the exact creation receipt in the same Work.
- Interpret "새 탭 열고 메시지 보내줘" as `create-chat-tab` followed by `send-message` using the exact creation receipt in the same Work.
- Interpret "기존 탭에 보내줘" as `send-message` only after fresh RCC `state` proves the exact target instance, session, window, tab, and conversation identity. If multiple targets remain, ask for disambiguation; do not guess by title or tab order.
- The user need not provide numeric Chrome IDs. Derive identifiers from fresh trusted RCC state or the BCT creation receipt; never invent them.
- Use `rcc-send-message-v1` with a single immutable send Operation, capture the assistant reply and verify the result receipt. Do not retry an ambiguous effect with a new Operation ID.
- Public commands are `create-chat-window`, `create-chat-tab`, and `send-message`; `state` is read-only. Do not initiate new `send` or `create-and-send` calls. Retain historical receipt decoding and internal recovery compatibility.

## 10. Block-assembly AI coding

- Default every new or changed implementation to reusable, composable boundaries.
  Before writing code, search `docs/component-library.v1.json` and the current
  source for an existing compatible block; extend or adapt it instead of copying it.
- Classify meaningful behavior as `primitive`, `module`, `partial_recipe`, or
  `full_recipe`. Keep user-visible recipes separate from the lower-level effects
  they compose.
- Every reusable block must make its purpose, inputs, outputs, external effects,
  failure/UNKNOWN behavior, receipts, tests and known callers explainable. A user
  must be able to descend from a recipe to its parts and source when desired.
- Treat contact points as first-class parts. Use explicit ports/contracts plus
  small connector, adapter, validator and state/receipt components where block
  shapes differ; do not hide one-off glue inside a recipe.
- Maximize compatibility through small stable contracts, not premature universal
  abstractions. A boundary must have independent meaning and a realistic reuse,
  replacement or isolated-test value; do not turn individual code lines into blocks.
- Recipes call shared blocks rather than duplicating their implementation. Test the
  isolated block contract and the composed recipe boundary. Preserve exact identity,
  idempotency, rollback and UNKNOWN/no-replay rules for external effects.
- Update the component catalogue when a block is added, promoted, replaced or
  retired. Label embedded boundaries honestly; do not claim isolation or LIVE proof
  merely because a function or wrapper exists.
- Refactor legacy code incrementally at the touched boundary. Do not broad-rewrite
  unrelated working code solely to make the catalogue look complete.
- Explain implementation work as a block map: reused blocks, new blocks, connection
  parts, changed effects and verification evidence. File diffs remain supporting
  evidence, not the primary user-facing model.

## 11. Verification

For BCT source changes run the focused affected tests first, then the relevant
repository gate. Typical static checks:

    python -m compileall -q src tests
    git diff --check

Run the full suite when the affected boundary or CI contract requires it.
Always state the exact tested SHA and distinguish local tests, CI, LIVE and
physical E2E evidence.
