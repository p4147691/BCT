# BCT Conversation Network A — flexible scope and advisory roles

Status: `LOCAL_MAIN_ACCEPTED / MAIN_CI_SUCCESS / LIVE_NOT_APPLIED`

## User contract fixed on 2026-10-21

- “project” and “conversation network” are one user-facing **conversation scope**. The existing
  `conversation_network_projects` table remains the compatibility storage; no second `network_id`
  registry is introduced.
- A conversation has at most one current scope. Moving it marks the old membership `EXCLUDED` so
  recovery/history can still describe it.
- `Manager` is an advisory role tag only. Zero, one, or several nodes may carry it. It grants no
  permission, never gates another feature, is not auto-assigned to the first node, and does not
  require a successor before a node can move or close.
- A 600 ms stationary left press adds the `Manager` tag as a shortcut. Pointer movement cancels the
  timer so click, double-click, and future drag remain distinct.
- `N<n>` is a durable display alias for the conversation UUID. Closing a chat does not release or
  recycle it; newly observed conversations receive a new number.
- Right-click opens one compact information editor containing exact identity/location, actual
  ChatGPT title, scope, and free role tags. Verified title changes are also written back to the BCT
  conversation record.
- The existing trash/recovery UI is reused. Trash records carry the durable N label, previous scope,
  and roles; a second archive system is not created.

## Source implementation

- Core adds `configure_conversation_scope()` and `conversation_scope_directory()` on the existing
  tables. Existing `set_membership()` also retires another ACTIVE membership for the same UUID.
- `/monitor/state` projects current scope metadata onto the already exact RCC conversation UUID.
- Monitor origin may call `/monitor/conversation-network/update` for metadata only. This route does
  not create execution authority, a browser effect, or a resource Claim.
- BWM groups existing compact cards by scope in the existing three-column list and keeps an
  `미소속 대화` section. The compatibility ACT organization projection is not extended.

## Verification completed locally

- full BCT Python regression: **895 PASS**
- conversation-network, Monitor runtime, and Monitor rename/scope focused tests: **26 PASS**
- BCT shell, exact node interaction, and thumbnail label Node checks: PASS
- JavaScript syntax checks: PASS
- Monitor structure/index check: PASS
- Python compileall: PASS
- `git diff --check`: PASS

The broader Monitor tool sweep also passed except for two already-known environment/baseline checks:
the isolated worktree has no prebuilt native visual executable, and the NCodex route checker still
expects a retired label. Neither failure executes or covers this conversation-scope change.

## Remaining gates

The candidate commit `06b157cbf32557696ef1818782c46e9da494dda2` was integrated through the
`merge_local_main` operation as exact main `73066a84caba93d18a2c933c629fe26d5364d8aa` and
published fast-forward-only. GitHub Actions run `39551081584` passed scope, preflight, all four Core
shards, and Browser Bridge.

1. Deploy the exact accepted Core and Monitor payload only after the shared LIVE target is clear.
2. Reload same-ID BWM and perform actual right-click, scope grouping, 600 ms Manager tag, rename,
   close/trash/recovery E2E. Until then this is not LIVE accepted.

## 2026-10-21 node drag and Manager toggle follow-up

- The stationary 600 ms gesture now toggles the advisory `Manager` tag both on and off. It still
  changes no permission or routing authority.
- Pointer ownership is captured by the source card on pointer-down so crossing a scope heading cannot
  steal the drag. While a drag is active, headings do not receive pointer actions; a short post-drag
  fence also prevents an accidental fold click.
- Scope headings remain non-drop targets. The synthetic `여기에 놓기` card was removed. Dropping at
  the end of a wrapped row now uses the real final node card's right-hand insertion line.
- The node-interaction regression executes the heading rejection and wrapped-row append calculation,
  and verifies the Manager add/remove contract. Focused conversation/Monitor tests are 33 PASS; the
  complete local Python suite is 898 PASS. The previously documented missing native visual binary and
  retired N-Codex label checks remain baseline-only and do not cover this change.
- Source validation is complete; exact-head CI, installation publish/reload, and visual E2E remain the
  delivery gates for this follow-up.
