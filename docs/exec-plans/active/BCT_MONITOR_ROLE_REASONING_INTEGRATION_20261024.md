# BCT monitor role and reasoning integration

Work: `BCT-MONITOR-ROLE-REASONING-INTEGRATION-20261024-01`

## Objective

Reuse the conversation-network role-tag store as the single advisory role
source for the Monitor, Manager, and newly composed relay prompts. Show only a
currently observed ChatGPT reasoning level; do not create a preferred-value
store or let missing observation block work.

## Implemented in the isolated branch

- Monitor node labels show `D# · role tags` with bounded abbreviation.
- Monitor and AI edits use the same membership-tag table.
- Both edit paths expose and compare a canonical UTF-8 role-tag SHA-256, so a
  stale editor returns `NOT_APPLIED` without retaining a Claim.
- `conversation_network_update` gives an authorized Manager a narrow
  add/remove role patch. It changes no tools, permissions, browser route, or
  Delivery and affects newly composed messages only.
- RCC RC33 observes the current reasoning label from the semantic ChatGPT
  model-selector control. Monitor shows the label only with `OBSERVED`
  evidence. Missing or changed UI becomes `UNAVAILABLE` and never blocks a
  node, Delivery, or Wake.
- No preferred reasoning setting is stored. No reasoning mutation is included
  in RC33.

## Reasoning mutation finding

Official Agent Sessions can update model and reasoning effort for subsequent
turns, but no supported API was found for changing an existing ordinary
ChatGPT web conversation. The current web control exposes `High` in the
accessibility tree. A content-script synthetic key attempt was rejected before
any event and the live value remained `High`. A later mutation feature must
therefore use a separately verified CDP/UI input path, exact conversation
identity, idle-state checks, and post-change readback. Failure must be terminal
for that change only and must not block relay work.

## Verification required before integration

- Python focused and full suites with `PYTHONUTF8=0` and the worktree `src` at
  the front of `PYTHONPATH`.
- RCC JavaScript suite, RC manifest verification, Monitor structure and source
  baseline checks.
- Exact-source CI before local-main integration.
- Core and Monitor/RCC rollout reported independently. Browser reload occurs
  only when existing ChatGPT tabs are idle and exact same-ID preservation can
  be checked.
