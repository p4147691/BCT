# PR3-e: production-disabled Browser Bridge peer adapter

PR3-e is the first reusable Host-to-Core framing boundary. It accepts a strict
outer JSON frame only through an explicitly injected `PeerBindingProvider`,
then sends the exact decoded inner bytes to PR3-c. It is not a web endpoint,
Native Host registration, Chrome integration, or credential provisioning flow.

The existing Browser Bridge read-only MCP bearer is deliberately not accepted
by this adapter and is not a `PeerBindingProvider`. A future listener starts
disabled: calling the module entry point without a provider returns
`PEER_ENDPOINT_DISABLED`.

## Required provisioned binding

A provider resolves a binding by `peer_id` from a bounded OS-backed credential
store. The binding contains the peer ID, monotonic credential generation,
approved launcher SHA-256, fixed extension origin, and exactly 32 bytes of
secret material. Secrets must never enter SQLite, operation receipts, logs, or
error replies. Rotation uses a new generation; replay state is fenced by
`(peer_id, binding_generation)`.

The Host signs the exact inner PR3-c bytes and all routing identity values with
HMAC-SHA256. Core compares those values with the provisioned binding and
atomically reserves a strictly increasing sequence before it invokes PR3-c.
Thus a malformed inner request cannot reuse an already authenticated outer
frame. This is proof of possession of a provisioned secret, **not** complete
OS process attestation: caller-provided launcher SHA and origin remain checked
metadata until a future platform-specific IPC/process-protection implementation
is approved.

## Explicitly out of scope

No provider implementation, secret creation, registry entry, file ACL change,
listener, port, Chrome profile, Native Host reload, or live Core change occurs
in PR3-e. Production rollout needs a separately reviewed credential lifecycle
(provision, rotate, revoke, recovery) and local IPC peer-process protections.
