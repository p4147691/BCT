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

## Read-only observation versus browser mutation

A platform-recognized RCC read command with feature-owned `mutating=false`
creates no resource Claim. If its observation is missing or unverified, report
`MEASUREMENT_UNVERIFIED` without inferring target state or blocking another
normal corrective operation. An unverified message submit, rename, tab move or
other browser mutation is different: preserve its original receipt and exact
mutation duplicate fence, with no blind resend. A caller-supplied read-only
label cannot turn a mutating command into a measurement.

## Secret boundary

The legacy RCC state payload contains internal transport settings. BCT recursively removes
token, secret, password, and authorization fields before recording or returning an RCC
result. It preserves useful endpoint and tab identity without copying transport secrets
into BCT receipts.

## Deployment

Only the two Python integration files are loaded into the BCT Core runtime. RCC itself is an
installable module and is deployed separately to `D:\ChromeExtensions\RCC`.

The protected operating-path plan stages the Native Host and unpacked extension
under `%LOCALAPPDATA%\BCT\rcc`, but copying does not change Chrome's active
unpacked path or the HKCU Native Messaging registration. Any later switch is a
separately approved operating step. It must preserve the manifest public key,
the fixed extension ID `ocbidbaplechjjdacmokhnfbdmgjkphf`, the sole allowed
origin, extension storage, RCC instance and existing tab/conversation identity.
A different ID or lost identity blocks activation and rolls the path references
back; the process must never load a second RCC identity as a shortcut.

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

The BCT coordinator performs one bounded read-only result lookup when a
`send-to-created-tab` dispatch initially reports `SUBMIT_UNKNOWN`. It never
dispatches the message again. The original operation is accepted as `APPLIED`
only if the terminal receipt is persisted, successful and non-ambiguous, has a
conversation and reply, and its complete bootstrap fingerprint exactly matches
the create operation, RCC instance/session, tab/window and submitted text.
Missing, pending, failed or mismatched evidence remains `UNKNOWN`.

`BCT RCC 1.0.4` adds `create-and-send` as the normal new-chat path. One BCT
operation creates a tab or independent window, submits the exact draft once,
waits read-only for the durable assistant result, and returns the conversation
identity and reply. Network-start and exact-user-turn evidence race in parallel,
so a missing network observer no longer adds a fixed five-second delay after
the DOM already proves submission. Timestamp-only stage evidence covers editor
ready, exact draft, send-button ready/click, user-turn confirmation and
conversation capture. `reconcile-create-and-send` is the only release path for
an UNKNOWN composed parent and requires its deterministic child receipt.

If the exact created conversation completed after its content response port was
lost, RCC 1.0.5 performs a single result-only DOM recovery after the recorded
network request completes. It verifies the composed fingerprint and exact
instance/tab/window/conversation, requires one matching user turn and one
completed assistant turn, and persists the result without clicking or sending.

RCC 1.0.6 tightens that recovery completion check. A stale inert stop control may
be ignored only when the exact routed turn independently reports both a complete
turn state and its completion action UI. Missing either signal remains fail-closed;
the recovery path still never clicks or submits.

RCC 1.0.7 applies the same dual-signal rule to the normal final-response
classifier. This removes the equivalent false negative before recovery while
preserving the stricter streaming result whenever either exact-turn signal is
missing.

RCC 1.0.8 adds an exact-binding fence for durable orchestration sends. The
caller supplies the immutable conversation binding receipt and message digest;
both are included in the duplicate fingerprint. Immediately before submission,
the extension verifies the current role registration still has the same
instance, session, tab, conversation, and binding receipt. A changed attachment
is rejected before clicking. The existing generic send contract remains
backward compatible when these optional fence fields are absent.
The exact tuple is carried into the content script and checked again immediately
before editor mutation and immediately before the click/Enter submit transition.
The acknowledgement and durable result receipt contain the tuple attested by the
content script; caller-supplied expected values are not echoed as proof. A rebind
between background validation and submission therefore fails closed without a click.

RCC 1.0.9 separates confirmed pre-activation rejection from an ambiguous
post-activation outcome. The content script persists `submit-attempted`
immediately before click or Enter; a failure before that checkpoint clears only
the exact unchanged relay draft and reports `NOT_APPLIED`, while any failure at
or after it preserves durable evidence as `UNKNOWN`. Opted-in orchestration
sends return a submit ACK to BCT immediately so SQLite records delivery before
long result collection. Final-response capture is scoped to the exact routed
turn, so a later user turn in the same conversation cannot keep an already
completed assignment falsely marked as generating. Generic RCC sends keep their
existing wait-for-terminal-result behavior.

RCC 1.0.10 also handles a completed content-side record whose result was
already recovered and persisted by the background after the content script's
bounded delivery retries ended. A later exact relay first retries only that
idempotent result receipt. If the stale record remains or the target is still
generating, the new exact relay returns confirmed `NOT_APPLIED` and is not
queued. Pre-1.0.10 orchestration queue entries did not retain the complete
binding tuple; RCC drops those local entries before submit and leaves the
background evidence available for explicit reconciliation. This prevents an
old queued prompt from firing after Core has timed out.

RCC 1.0.11 treats `/c/local-chatgpt` as a provisional navigation marker rather
than a conversation identity. A newly created tab must reach its durable
server-assigned conversation key before bootstrap state is bound. The content
and background paths share the same parser so later exact sends cannot inherit
a completed record tied to the optimistic route.

RCC 1.0.12 distinguishes a stale content-side completion from an unproven
effect by asking the background for the exact durable result receipt. It clears
the local record only when the receipt is `RESULT_PERSISTED` and its tab and
conversation still match. It also compares contenteditable drafts using their
direct paragraph structure, so ProseMirror's visual blank line does not turn an
unchanged inserted newline into a false editor mismatch. Neither path weakens
the pre-submit binding or exact-draft fences.

RCC 1.0.13 applies that exact durable-receipt cleanup when the content record
is still `submitted` as well as `completed`. This covers background-side exact
DOM recovery finishing before the original content collector. Without an exact
persisted receipt for the same tab and durable conversation, the old submitted
record remains in place and a new relay stays blocked.

Protected-path staging does not trust the writable installed RCC directory as a
source authority. Extension bytes are reconstructed from the exact clean Git
commit, the installed manifest must normalize to that commit, and the Native
Host binary is built inside the protected boundary from the exact Git source
blob. Its operation-scoped receipt binds the Git head/tree/blob, system compiler
path/hash and produced artifact hash; a hash supplied for the writable installed
Host is not accepted as authority. The staging
receipt is operation-scoped and non-activating. Chrome's loaded unpacked path,
extension storage, RCC instance and all tab/conversation identities remain an
operating acceptance gate; copying files alone never claims they were preserved.
