# Browser Bridge credential and local-IPC activation gate

This is a design gate, not an implementation or deployment instruction.  It
does not create a secret, registry value, profile, listener, or Core release.
It exists because PR3-e needs a Bridge-specific `PeerBindingProvider`, whereas
the existing read-only Native Host only reads an isolated MCP token from a
staging environment variable.

## Non-reuse rule

The following identities are deliberately incompatible with a PR3-e peer
binding and must never be copied, derived, or repurposed as one:

- BCT Core control and MCP bearer tokens;
- the read-only Browser Bridge test token and `BCT_BRIDGE_*` environment
  variables;
- every RCC extension, Native Host, manifest, executable, profile, or token;
- a Chrome extension origin by itself.

PR3-e proof is a Host/Core possession check.  It is not a replacement for the
Core capability grant, Chrome extension identity, or OS process protection.

## Required binding record

A future provisioning operation may create exactly one Bridge-owned binding
record per approved Host identity.  Its durable non-secret metadata is:

| Field | Requirement |
| --- | --- |
| `peer_id` | Opaque, bounded Bridge-only identifier. |
| `binding_generation` | Positive, monotonic generation; never reused for the same peer. |
| `launcher_sha256` | Exact approved launcher executable digest. |
| `origin` | The fixed Browser Bridge origin only. |
| `state` | `ACTIVE`, `REVOKED`, or `RETIRED`; no implicit fallback. |
| `created_at` / `revoked_at` | Audit metadata only; never a plaintext secret. |

The 32-byte proof secret is separate from this record.  On the present
same-user Windows topology, user-scope DPAPI is a candidate protection
mechanism, but selecting it requires a separate implementation review.  No
command line, environment variable, SQLite row, receipt, log, error response,
or browser extension storage may contain the plaintext secret.

## Lifecycle and fencing

```text
unprovisioned --provision--> ACTIVE(generation N)
ACTIVE(N) --rotate--> ACTIVE(N+1) + RETIRED(N)
ACTIVE(N) --revoke--> REVOKED(N)
RETIRED/REVOKED --remove--> absent
```

- Provisioning must verify the exact Bridge launcher digest and fixed origin
  before secret creation.  It must fail if any target Bridge resource already
  exists with different ownership or values.
- Rotation creates and verifies `N+1` before retiring `N`; it never overwrites
  a secret in place.  New frames must use `N+1`.  Frames signed by a retired or
  revoked generation are denied.
- PR3-e replay state is keyed by `(peer_id, binding_generation)`.  Retirement
  therefore cannot make an old sequence valid for the new generation.
- Revocation is fail-closed: provider lookup must return no usable binding
  before Core accepts another frame.  A frame in transit may be denied or
  become an auditable unknown transport effect, but it must not be retried
  automatically.
- Recovery starts by inspecting only Bridge-owned metadata and the release
  receipt.  It may not infer that a missing reply means no previous Core
  effect; receipt lookup governs recovery.

## Protected local IPC contract

The future transport must carry the canonical bytes from
`native/peer_frame.py` to the Core PR3-e adapter without exposing the proof
secret to Chrome or another user process.  It must additionally prove, before
dispatch, all of the following:

1. the server accepts only the current Windows user and the approved
   Bridge-owned Host process boundary;
2. the launching executable matches `launcher_sha256` at connection time;
3. the endpoint is newly Bridge-owned, has no pre-existing foreign listener,
   and cannot collide with RCC or the read-only Bridge host;
4. peer binding lookup and sequence reservation fail closed if credential or
   process inspection fails; and
5. endpoint removal is possible using only its recorded Bridge ownership
   receipt.

An arbitrary loopback HTTP port, inherited environment secret, or an existing
BCT/RCC native host does not satisfy this contract.  The transport choice
(for example a Windows named pipe with restricted ACL plus peer-process
inspection) remains a separately reviewed implementation decision.

PR3-n records the first disposable proof of that decision: the intended
logon SID is placed on a protected pipe DACL, the connected client session is
queried and compared before payload read, and separately protected temporary
credential root/file ACLs are revalidated after connect. This does not create
or enable a production listener. `CurrentUserOnly` remains insufficient as the
sole activation evidence, and a same-account malicious-process boundary still
requires the independent executable proof and peer/capability checks.

## Activation acceptance

Before production code is enabled, an isolated test must prove:

1. provisioned Host → signed frame → PR3-c success;
2. wrong user/process/origin/launcher digest/secret/generation is denied
   without exposing a secret;
3. sequence replay, retired generation, and revoked generation are denied;
4. rotation accepts the new generation and refuses the old one;
5. an interrupted post-send exchange is recovered through existing immutable
   delivery/receipt contracts, never by resending the same request; and
6. cleanup deletes only artifacts created by that test and leaves BCT LIVE,
   RCC, existing Chrome, Issue #111, UNKNOWN records, and Claims unchanged.

Only after this gate, exact-head CI, an independent review, and a separate
explicit activation approval may a listener, credential provider, registry
entry, or Chrome E2E be implemented or run.
