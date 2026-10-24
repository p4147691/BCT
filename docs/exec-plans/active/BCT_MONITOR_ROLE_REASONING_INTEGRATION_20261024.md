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

## Reasoning mutation candidate and off-desktop thumbnail checkpoint — 2026-10-25

- Isolated branch `fix/monitor-offdesktop-thumbnail-fallback-20261025` adds a
  narrow `cdp_reasoning` request/status capability.  The durable row stores an
  absolute target for one exact RCC instance and conversation UUID; it is not
  a relay Delivery or resource Claim and cannot block messages.
- RCC observation must prove the exact endpoint OPEN and idle before CDP input.
  The CDP adapter accepts only the generated reasoning prepare/readback scripts
  and ArrowLeft/ArrowRight/Escape.  Each attempt reads the actual current level
  first, moves toward the absolute target, closes the menu, and verifies the
  exact resulting label.
- Busy targets remain pending without CDP input.  Transient connection/readback
  failures use bounded exponential backoff and fail after five attempts;
  selector/position/focus contract failures become terminal immediately.  A
  failed setting request remains inspectable but never blocks relay or another
  BCT capability.
- Manual official-CDP acceptance changed N33 and N34 from High to Medium and
  restored both to High.  N33 also traversed all five observed labels (Instant,
  Medium, High, Extra High, Pro) and was restored.  No ChatGPT message was sent.
- Cloaked windows on another virtual desktop now receive an opaque full-window
  explanatory thumbnail instead of a nearly transparent generic placeholder.
  Exact HWND geometry and drag behavior are unchanged.
- Focused Python tests (14), Monitor fallback policy, Monitor structure and JS
  syntax, Python compile, and `git diff --check` pass with `PYTHONUTF8=0`,
  explicit UTF-8 stdout, and the worktree `src` first on `PYTHONPATH`.  The full
  Python suite was also run once and passed 1,080 tests in 709.345 seconds; do
  not repeat it interactively unless the final exact-head verification needs it.
- Source integration, CI, Core deployment, Monitor publication/reload, and LIVE
  invocation through the new BCT capability remain pending.  Existing Core,
  RCC, Monitor, Chrome tabs, Windows language/Beta UTF-8 setting, and reboot
  state were not changed at this checkpoint.

## Verification required before integration

- Python focused and full suites with `PYTHONUTF8=0` and the worktree `src` at
  the front of `PYTHONPATH`.
- RCC JavaScript suite, RC manifest verification, Monitor structure and source
  baseline checks.
- Exact-source CI before local-main integration.
- Core and Monitor/RCC rollout reported independently. Browser reload occurs
  only when existing ChatGPT tabs are idle and exact same-ID preservation can
  be checked.

## Verified integration and rollout state

- Feature commit `fa502800358bb7bbcea761e42087c39f15337e77` passed exact-head
  CI run `40095612901`. Local-authority main merge
  `73fcb4adc14e4883aa60750b471041b2fddf1a52` passed push CI run
  `40096059555`.
- Core generation 219 runs exact main `73fcb4a` with manifest
  `c0a4b98f569ad9b451cf4f05d2fde31c3f58cf7fb5d046eb38810ca2f5c53544`.
  A long-lived MCP request delayed the old Core shutdown, so the initial
  deployment receipt correctly ended `UNKNOWN`. The old PID later exited;
  the bounded Core Supervisor started the already activated immutable release,
  and a separate exact LIVE reconciliation operation finished `APPLIED` and
  released the original deployment Claims. Do not retry that deploy effect.
- Authenticated Streamable HTTP LIVE acceptance exposed
  `bct_conversation_network_update`. It added and removed the temporary N34
  tag `BCT-런타임검증` against exact digests under `PYTHONUTF8=0`; both
  operations were `APPLIED`, and final tags/digest were restored exactly.
  Future role edits use this runtime store and do not require Git, CI, Core
  deployment, or extension reload.
- Monitor installed payload 2.0.32 contains the role/digest display changes and
  passed the installed structure and BCT-shell checks. Its deployment token is
  published but runtime observation/reload remains `PENDING`; do not call it
  LIVE until the same-ID Monitor runtime reports 2.0.32 and the exact token.
- RCC RC33 exact 52-file aggregate
  `0b6d1e3489745ce9e787014d232829af3bd833cea8608766365b32a27b8a87de`
  was activated only after every observed tab was idle. One same-ID reload
  operation finished `APPLIED`; extension instance and tab IDs were preserved
  while the session advanced to `76a9b285dc29413d98fca5b0c08cf390`.
  Repeated read-only observations reported N32/N36 `Medium` and N33/N34/N35
  `High`, all from `chatgpt-model-selector`. No message was sent. Exact RC31
  runtime and RC32 installed-folder backups remain available for rollback.
