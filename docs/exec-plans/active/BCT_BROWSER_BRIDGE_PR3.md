# BCT Browser Bridge PR3 — peer adapter checkpoint

Status: `PR3M_WINDOWS_RELAY_E2E_ACCEPTED / PRODUCT_GATE_BLOCKED`.

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

## Accepted checkpoint: PR #132

PR #132 (merge commit `6fc0a3af6106ec80200f1399144e245629309f41`) adds the transport-neutral
PR3-e outer peer adapter. It is disabled unless a caller explicitly supplies a
`PeerBindingProvider`; it never accepts the existing Browser Bridge read-only
MCP bearer. The adapter validates a canonical outer frame, an HMAC over exact
PR3-c bytes and the peer binding, binding generation, launcher metadata and
strictly increasing sequence. Sequence reservation occurs before inner ingress
and no secret is persisted in SQLite.

The same PR now includes a disconnected Native Host-side canonical frame
encoder. It takes explicit bounded arguments and an already provisioned secret,
but cannot read a secret, make a Core request, or alter the existing read-only
Host. Cross-boundary tests prove its exact bytes are accepted by the Core
adapter; this prevents a future duplicated wire format from silently drifting.

Focused inherited bridge tests, local full unittest, `compileall`, and
`git diff --check` passed in the isolated worktree. The exact PR head
`d0a1abab47753b3cc411e2fdf74fb3105eaa1dec` later passed GitHub Actions run
`38701545681` after the account's included Actions capacity was restored.
Independent source review and a local inherited bridge regression run (59
tests) found no merge-blocking issue. No runtime resource was created or
changed, and the merged code remains disabled without an injected provider.

## Accepted isolated checkpoints after PR #132

- PR #133 (PR3-f) added the disabled, injected binding lifecycle.
- PR #134 (PR3-g) added an in-memory Windows DPAPI codec boundary.
- PR #135 (PR3-h) added a create-only, explicitly injected DPAPI file store.
- PR #136 (PR3-i) exercised lifecycle/store integration only in a disposable
  directory.
- PR #139 (PR3-j) added a disposable named-pipe probe.  It checks
  `CurrentUserOnly`, obtains the connected client PID and accepts only the
  expected executable SHA-256.  Its exact head and the merge commit
  `a644df62fd20514261bd43b7e5bb587ff4db62e7` passed CI.

None of these checkpoints creates an operational listener, a default secret
location, a registry entry, an extension installation, or a connection to
BCT LIVE.  PR3-j proves a Windows primitive only; it does not carry a peer
frame, load a binding, invoke Core ingress, or prove logon-session isolation.

## Accepted PR3-k framed-pipe codec

PR3-k's production-disabled codec and isolated tests are merged. It strictly
length-prefixes and decodes one canonical peer frame without creating a pipe,
calling `PeerAdapter`, resolving a binding, loading a secret, or enabling a
runtime path. The later PR3-l and PR3-m checkpoints reuse this exact codec; do
not reimplement or fork the wire format.

## Current isolated checkpoint: PR3-l verified relay composition

PR3-l composes the accepted boundaries behind mandatory injection.  A client
verifier runs before request bytes are read, the verified executable digest is
matched to the canonical peer frame, and PR3-e remains responsible for active
binding, proof and sequence validation before PR3-c ingress.  A transport
failure while publishing the result is surfaced as an unknown effect and the
relay performs no resend.

This checkpoint has no listener, real process verifier, default credential
path or runtime entry point.  It uses only an in-memory binding and a fixture
verifier in tests.  Product activation remains blocked on the Bridge-only
Windows credential and final logon-session/DACL policy.

## Current Windows checkpoint: PR3-m disposable relay E2E

PR3-m adds a CI-only C# fixture path.  It loads a newly created temporary
Bridge secret from DPAPI, builds the canonical signed peer and pipe frames,
crosses a random same-user named pipe whose server verifies client PID and
executable SHA-256, and reaches PR3-l authenticated ingress.  Revocation and
temporary-directory cleanup remove the protected secret and the processes
dispose the pipe.

The commands remain unreachable from the normal Native Messaging origin path
and have no runtime registration.  They do not establish the final
logon-session/DACL policy or authorize a real credential/listener deployment.

PR #146 exact head `663cb89dec789f8ab4287ce1697af96e60e26922`
and merge commit `26ace7abc082be8da2484c76bf612738043dfef1` passed
their Windows CI runs. The accepted test covers C# Host DPAPI unprotect,
canonical proof/frame creation, a random same-user named pipe, connected PID
and executable-digest verification, authenticated PR3-l ingress, wrong-digest
denial, revocation and temporary-resource cleanup.

## Remaining product path, in order

PR3-m completes the reusable Core, credential-lifecycle, framing and disposable
Windows transport prerequisites. It does **not** complete the user-facing
product. Continue in bounded checkpoints:

1. Finalize and independently review the activation contract: Bridge-owned
   persistent credential root, restrictive directory/file ACL evidence,
   logon-session SID/DACL policy, provision/rotate/revoke/recovery semantics and
   exact cleanup ownership. Do not create operational resources in this step.
2. Add a production-disabled listener composition that injects the accepted
   binding lifecycle, DPAPI store, process verifier and PR3-l relay through
   explicit configuration. It needs bounded startup/shutdown, restart and
   tamper tests and must remain disabled by default.
3. Replace fixture-only authority with a real, narrowly scoped capability
   issuer and independently authenticated recipient-processing evidence. Bind
   session, node, attachment, origin, expiry, revocation and replay state; a
   deterministic command ID or caller-supplied proof is not an ACK authority.
4. Integrate the independent extension/Native Host route: real ChatGPT
   completion observation, completion report/result retrieval, delivery and
   recipient ACK, and durable manager wake/outbox continuation. Preserve
   user-created tab ownership and do not close a tab merely because work ended.
5. Run the approved isolated Chrome acceptance with a fresh profile, test-only
   HKCU registration, temporary Core/token/port and exact cleanup receipts.
   Cover disconnect, restart, duplicate, wrong identity, rotation/revocation,
   post-send UNKNOWN no-retry and result-to-follow-up continuation.
6. Only after the isolated acceptance passes, prepare a separately approved
   packaging/deployment checkpoint with verifiable artifacts, rollback and
   operational observability. CI success alone never enables the listener.

## Read-only Windows credential feasibility

The currently running Core process and a representative user Chrome process
were observed under the same Windows user principal. User-scope DPAPI is
therefore a technically viable candidate for a future per-user peer binding;
this is not an approval to create, read, migrate, or deploy a credential.

Existing BCT runtime control/MCP tokens are unrelated authority and must never
be reused as a Bridge peer secret. The RCC Native Host pipe is also not a
candidate: it is a different product boundary and its current server does not
provide the Bridge-specific credential lifecycle or peer-process verification.

User-scope DPAPI can protect a stored value at rest, but it does not by itself
prove that a request came from the approved Host process: another process under
the same Windows user can normally invoke user-scope protection APIs. Therefore
user-scope DPAPI plus a user-ACL named pipe is not sufficient activation
evidence for this product path.

No reusable BCT credential lifecycle (provision, rotation, revocation, recovery
and restrictive storage ACL proof) was found. Before implementation, the design
must establish all of the following:

1. a Bridge-only credential target and a stable binding generation;
2. mutually consistent Host/Core access without putting plaintext in command
   lines, environment, SQLite, receipts, or logs;
3. rotation/revocation behavior for in-flight frames and persisted sequence
   rows; and
4. a failure and removal procedure that deletes only newly created Bridge
   resources and never alters the existing BCT or RCC credentials.

`modules/browser-bridge/docs/CREDENTIAL_IPC_GATE.md` now records the required
Bridge-only metadata, lifecycle transitions, IPC properties and isolated
acceptance cases. It deliberately selects no Windows secret store or IPC
implementation and creates no OS artifact.

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

## Deferred flow-improvement observations

Do not change the project-wide delivery rules as part of this Browser Bridge
work. When a concrete avoidable wait or ceremony is observed, record only its
evidence, affected scope, and a proposed safe relaxation here or in the
appropriate backlog issue. It must not interrupt the current implementation,
create a side task, or weaken any current protection. Review these observations
together during the later cross-project rule review.

The PR3-m implementation exposed four non-blocking flow items now recorded in
GitHub issue #82: fail-fast ordering should run import/compile, C# build and the
changed focused E2E before the full suite; exact-head and merge-main full-suite
duplication needs a safe reuse or merge-queue study; local worktree tests must
prove that imports resolve inside the current checkout rather than an older
installed package; and the current machine's missing .NET SDK delays C#
feedback until Windows CI. These are optimization candidates, not permission
to skip coverage, trust another SHA's result or install tooling implicitly.
