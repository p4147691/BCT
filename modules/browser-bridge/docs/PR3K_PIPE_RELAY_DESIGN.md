# Browser Bridge PR3-k — production-disabled framed-pipe relay design

## Scope

This is a design and isolated-test gate for the next Bridge-only IPC step. It
does not add a listener, generate a secret, choose a persistent path, write a
registry value, install an extension, or contact BCT LIVE.

The current components deliberately stop short of a connected path:

- `BridgePipeProbe.cs` proves a disposable same-user named-pipe client can be
  identified by PID and executable digest;
- `peer_frame.py` produces canonical PR3-e bytes;
- `PeerAdapter` verifies a binding, proof and sequence before PR3-c ingress;
- `BindingLifecycle` and `DpapiFileSecretStore` are caller-injected only;
- the existing launcher starts `persistent_host.py` with `BCT_BRIDGE_*`
  read-only-MCP configuration. That legacy route is not a peer relay.

## First source checkpoint

`src/bct/core/bridge_pr3k_pipe_frame.py` is the initial, disconnected
implementation of this design. It provides only a length-prefixed strict
envelope around one canonical peer-frame byte string. It does not create a
pipe, resolve a binding, load a secret, invoke `PeerAdapter` or Core ingress,
or change the C# launcher and legacy Native Messaging host. Its tests cover
only frame acceptance and rejection cases.

## Required future boundary

A future test-only relay must be an explicit, disabled entry point separate
from the Native Messaging origin path. Before reading a framed peer request,
the server must establish all of the following:

1. the pipe is freshly created under a Bridge-owned, collision-resistant name;
2. the connecting process PID is obtained from the pipe and its executable
   hash equals the current binding's `launcher_sha256`;
3. the pipe's access policy additionally restricts the intended logon session
   when the final Windows design requires it; `CurrentUserOnly` alone is not
   sufficient evidence for activation;
4. the raw payload is bounded and is exactly the canonical peer frame accepted
   by `PeerAdapter.ingress`; no second JSON or HMAC representation is created;
5. the binding provider resolves only a Bridge-owned, active generation;
   lookup, proof, sequence, frame parsing and Core ingress failures are
   fail-closed and reveal no secret; and
6. a post-dispatch transport interruption is reported as an auditable unknown
   effect and is never used to resend the same command.

The client may not receive a peer secret from Chrome, command-line arguments,
environment variables, SQLite, receipts or logs. How an approved Host obtains
its own Bridge-only secret is an activation decision outside this design.

## Explicit non-reuse constraints

The relay must never read, derive or accept any of the following as a peer
binding or proof secret:

- `BCT_BRIDGE_*` environment values or the current `persistent_host.py` token;
- BCT Core control/MCP credentials;
- RCC extension, Native Host, profile, manifest, pipe or credential material;
- a Chrome origin by itself.

The ordinary launcher path must remain byte-for-byte behaviorally independent
of any test relay until a separate activation review approves a new path.

## Isolated acceptance plan

The first implementation may use only disposable fixtures. It must prove:

1. an expected same-user test executable carrying a canonical frame reaches a
   fake/in-memory Core ingress once;
2. wrong executable digest, malformed frame, wrong proof, stale generation,
   replayed sequence and revoked binding are denied before an inner command is
   accepted;
3. the legacy Native Messaging launcher cannot invoke the new relay entry
   point and the relay cannot fall back to `persistent_host.py`;
4. a server-side error after the authenticated frame is read creates no retry;
5. test cleanup removes only its generated pipe and temporary files; and
6. the test creates no Chrome profile, registry key, BCT LIVE record, RCC
   resource, existing credential change, Issue #111 change, UNKNOWN/Claim
   change or `consumed_at` change.

## Completion boundary

This design is ready for an independent source review when the frame, process
identity, lifecycle, unknown-result and cleanup contracts above are all
preserved. It is not approval to implement the relay or to activate a real
credential/IPC endpoint. Implementation requires a separate decision on the
Bridge-only Windows credential location and final ACL/logon-session policy.
