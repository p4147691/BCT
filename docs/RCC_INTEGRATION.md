# BCT RCC integration V1

## Boundary

BCT owns a byte-exact source baseline of the currently accepted Chrome extension and
Native Host source under `modules/rcc/`. The already installed extension, Chrome profile, native
host executable, tabs, and role bindings remain in place. V1 adds a BCT control path to
the existing exact-instance Native Messaging pipe; it does not silently reinstall or
reload Chrome components.

The MCP capability is `relay_browser` (`bct_relay_browser`). It exposes only:

- read-only: `state`, `presence`;
- bounded side effects: `create-chat-tab`, `create-chat-window`,
  `send-to-created-tab`, `move-tab`, `send`.

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

## Secret boundary

The legacy RCC state payload contains internal transport settings. BCT recursively removes
token, secret, password, and authorization fields before recording or returning an RCC
result. It preserves useful endpoint and tab identity without copying transport secrets
into BCT receipts.

## Deployment

Only the two Python integration files are loaded into the BCT runtime. The recovered RCC
extension source is versioned in BCT but is not copied over the accepted ACT extension in
V1. A future extension change must use a separate exact-file Chrome deployment profile and
explicit reload acceptance.
