# BCT RCC integration V1

## Boundary

BCT owns a byte-exact source baseline of the currently accepted Chrome extension and
Native Host source under `modules/rcc/`. The already installed extension, Chrome profile, native
host executable, tabs, and role bindings remain in place. V1 adds a BCT control path to
the existing exact-instance Native Messaging pipe; it does not silently reinstall or
reload Chrome components.

The MCP capability is `relay_browser` (`bct_relay_browser`). It exposes only:

- read-only: `state`, `presence`, `result`;
- bounded side effects: `create-chat-tab`, `create-chat-window`,
  `send-to-created-tab`, `move-tab`, `rename-conversation`, `send`.

Binding creation/reassignment, ACK/CANCEL/RESEND, extension reload, state clearing, and
manager promotion are deliberately not exposed by this slice.

## Identity and duplicate effects

- Every call requires one exact live RCC instance ID. There is no cross-instance fallback.
- The BCT operation ID is the Native Host request ID and the extension operation ID for
  every mutating command.
- BCT work ownership, capability scope, resource claims, and duplicate receipts apply
  before the pipe call.
- A confirmed pre-dispatch failure releases the resource claim.
- A timeout, malformed response, or lost pipe after dispatch becomes `UNKNOWN`; BCT keeps
  the claim and never submits a second browser mutation automatically.
- Exact session/tab/window/create-operation identity is required for bootstrap send and
  tab movement.
- Conversation rename requires exact instance/session/tab/conversation identity and a bounded
  title. It changes the actual ChatGPT conversation title through the installed RCC UI path,
  verifies the saved title, publishes a fresh endpoint snapshot, and uses the BCT operation ID
  for both BCT and RCC duplicate fencing.

## Secret boundary

The legacy RCC state payload contains internal transport settings. BCT recursively removes
token, secret, password, and authorization fields before recording or returning an RCC
result. It preserves useful endpoint and tab identity without copying transport secrets
into BCT receipts.

## Deployment

Only the two Python integration files are loaded into the BCT Core runtime. RCC itself is an
installable module and is deployed separately to `D:\ChromeExtensions\RCC`.

The first installed-path migration keeps the running legacy instance available while a second,
fixed-identity BCT instance is loaded.  The old instance is read exactly once, registrations are
recreated only against matching open tab/conversation identities, and no pending/result operation is
copied or retried.  The old extension is disabled only after the new exact instance is healthy.  The
committed public key fixes the BCT extension ID at `ocbidbaplechjjdacmokhnfbdmgjkphf`, so later source
updates do not depend on the checkout or installation path.

The installed BCT extension is displayed as `BCT RCC`; the legacy compatibility extension keeps its
old display name.  The BCT manifest starts at product version `1.0.0`.  Every subsequently deployed
extension payload change must increase the four-part-compatible Chrome manifest version and update
`version_name` when a human-readable qualifier is useful.  The fixed public key, not the display name
or version, remains the durable extension identity.

`BCT RCC 1.0.1` adds bounded final-response failure evidence to durable result receipts. It records
the final DOM validation phase, the network signal/error, and the independent DOM reason without
including submitted or assistant message text. This is diagnostic evidence only: it does not weaken
the exact-operation duplicate fence or retry an `UNKNOWN` submission.

After `BCT RCC 1.0.0` passed exact-instance and preserved-tab acceptance, the legacy extension was
disabled.  The steady-state Native Host manifest and executable therefore accept only
`ocbidbaplechjjdacmokhnfbdmgjkphf`; the former path-derived origin is not a fallback identity.

`BCT RCC 1.0.2` gates new-tab first-message submission on the exact
composer draft and the composer-local enabled send-arrow transition.
Before clicking it verifies the same editor/button remain valid; for bootstrap
messages keyboard Enter fallback is disabled. Existing conversations retain
their bounded legacy fallback. The loaded build marker and exact release hashes
are checked separately from the Core runtime SHA.

If the first-message route change closes the original content-script response
port, submission is accepted only when the background has recorded the exact
conversation POST and the exact created tab/window subsequently exposes one
conversation ID with one matching user turn. Any incomplete or ambiguous
evidence remains `SUBMIT_UNKNOWN` and is never resent automatically.

An old `SUBMIT_UNKNOWN` claim may be released only through
`reconcile-send-to-created-tab`. The command is scoped to the original work,
operation and RCC instance, requires a persisted terminal result with no pending
host work and a conversation ID, records a separate reconciliation operation,
and does not rewrite or replay the original UNKNOWN operation.
For an existing 1.0.1 receipt, the public projection may omit `submitState`;
that legacy case is accepted only when the original BCT error is exactly
`RCC_HOST_OUTCOME_UNVERIFIED:SUBMIT_UNKNOWN` and all terminal/bootstrap identity
fences still match. Newer receipts expose and verify `submitState` directly.

`BCT RCC 1.0.3` also covers a distinct content-side route race observed by the
one-shot 1.0.2 LIVE E2E: the blank bootstrap route may acquire or replace its
conversation identity before final reply validation. Rebinding is allowed only
when the send is a created-tab bootstrap, the pre-submit turn set was empty,
the new route has a conversation identity, and exactly one new user turn
matches the submitted text. This does not relax identity changes for existing
conversations and does not retry an UNKNOWN send.
