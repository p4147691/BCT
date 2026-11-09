# Dot Orchestrator candidate

Scope: isolated source candidate; no installation, reload, runtime DB edits or node messages.
Lane: GUARDED_CI_FIRST (identity and durable metadata boundary).

Blocks reused: Monitor windowNodes exact RCC tab projection, Node Info editor,
Core Monitor origin check, Store transaction, generated Monitor bundle.
New module: bct.dot_node_info (see component catalogue).

Identity: /dots/<opaque>~<opaque> is stored losslessly as a compound reference.
Its parts are exposed as references only, with no asserted server semantics.
Same full route across tabs shares metadata; instance/session/window/tab remain distinct.
Different compound references are never merged. A second registration fails closed.
Unregistered dot surfaces show Dot; saving Node Info registers the single O.
O is global and unassigned. Candidate color is purple, subject to user preference.
Only task/memo/advisory tags are edited; a dot browser title is not renamed through /c/.
Existing conversation UUID allocation, memberships and Supervisor rules are untouched.

Limitations requiring further investigation: whether distinct compound routes refer to
one logical dot, durable registration transfer, and dot-native delivery/return.
The existing Chain watch and origin contracts require conversation UUIDs. No synthetic
UUID, empty-UUID send, implicit return-tab choice or fallback send was added.
A future adapter must bind the dot reference and exact tab plus an independently
verified return channel/message cursor, preserve Work/Task/generation and UNKNOWN
receipts, and reject ambiguous multiple-tab origins.

Verification: focused metadata and HTTP integration tests use temporary SQLite.
JS contract tests simulate RCC tabs and HTTP requests; these are not physical browser
E2E or proof of deployed behavior. Independent review and physical isolated browser
acceptance remain required before integration/deployment.

Observed verification: focused candidate and regression checks passed: 3 dot/HTTP,
7 Codex local surface, 15 Monitor runtime, 22 conversation-network, and 17 catalogue
tests. Dot JS projection, existing shell/detail/interaction, Monitor structure,
component freshness, compileall and diff whitespace checks passed. The isolated browser
editor check additionally proves that saving a dot updates only its exact compound key,
not an unrelated Codex-local node with a blank conversation UUID.
Headless Chrome temporary-profile test passed for actual Node Info editor DOM and
metadata save using a simulated HTTP boundary. This does not prove the full extension
plus real Core plus authenticated dot path end to end. No CI or independent review yet.


## Additional routing investigation and linked isolated acceptance

Source evidence:
- modules/rcc/extension/core/identity.js: conversationKeyFromUrl accepts /c/ only;
  conversationUuid enforces canonical UUIDs and resolveExactConversation rejects
  ambiguous multiple tabs.
- modules/rcc/extension/relay_core.js: conversationKey likewise ignores /dots/.
- modules/rcc/extension/domain/exact_tab_send_service.js: nonblank targets need
  a matching nonempty conversation key; /dots/ must not be treated as a blank chat.
- src/bct/chain_direction.py: assessment manager_conversation_key is a canonical
  ChatGPT conversation UUID for the return destination.
- src/bct/send_delayed_message.py: reserved target/manager bindings and the return
  send retain that UUID-based identity.

check_monitor_dot_rcc_boundary.js confirms a synthetic dot URL produces an empty
conversation key, its UUID-shaped prefix resolves to MISSING, the compound value
is rejected as a UUID, and a normal /c/ Manager still resolves EXACT. No sends.

check_monitor_dot_http_e2e.py passed actual headless Chrome -> ephemeral localhost
HTTP -> dot_node_info_response -> temporary SQLite save/reload. It exercised the
real Node Info editor and shell adapter with two dot tabs and an ordinary node.
The test-only HTTP adapter supplies the trusted extension Origin because the page
runs on localhost. It does not validate a loaded extension's authorization,
native-host connection, real ChatGPT dot or real Manager message return.

The received dot URL establishes only an observed opaque compound route. Neither
BCT source nor these tests establishes the server meaning of the two parts or
whether the first part identifies the same dot across different contexts. Hence
there is intentionally no automatic merging of different compound routes.

Read-only current-session observation found one open route of this compound form.
That is evidence that the form is live on the current Chrome surface, not evidence
that another compound route represents the same dot.

## Proposed delivery/return boundary; not implemented

Reuse the existing exact ordinary Manager target resolver and send/watch ledger.
Add a separately versioned DOT origin identity rather than relaxing UUID validation:
identity_kind=DOT, dot_reference plus complete compound context reference, explicit
registered metadata revision, and fresh instance/session/window/tab endpoint.
Bind one return destination explicitly when multiple tabs expose that dot context;
never select by O label, title or tab order. Persist the original Work, Task,
generation, outbound Operation, response hash/cursor, and return Operation together.
Dot receiver readiness must be independently observed, including its ability to
receive a result without switching context or confusing user/assistant turns.
UNKNOWN remains attached to the original receipt with no replacement replay.

Before a real full-chain acceptance: implement and independently review this typed
origin/receiver adapter in Core/RCC, stage an isolated authenticated ChatGPT profile
with an explicitly designated disposable Manager conversation and dot return tab,
then verify delivery, response observation, exact return, navigation/session drift,
duplicate tabs and UNKNOWN recovery. Existing LIVE nodes cannot serve as disposable
test fixtures while preserving their conversations. No such runtime adapter or
isolated authenticated fixture has been deployed or provisioned here.

The O color remains a provisional purple candidate, not a user-confirmed choice.
