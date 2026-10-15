# PR3-d: fixture-only Host/Core peer-proof contract

This is a Python/SQLite fixture protocol only.  It creates no listener, Native
Host registration, Chrome profile, production credential, or operating-system
secret.  It must not be treated as a deployment recipe.

Before PR3-c strict ingress is called, the future Host presents its provisioned
`peer_id`, the approved launcher SHA-256 and fixed extension Origin, a strictly
increasing sequence number, the exact PR3-c envelope bytes, and an HMAC-SHA256
proof over all of those values.  The sequence reservation is committed before
inner-envelope processing; no frame can be replayed after a malformed or
ambiguous result.

The fixture issuer is opaque and bound to one in-process test `Store`.  Its
random secret remains process memory and only its fixture peer metadata is
recorded in that isolated SQLite DB.  Production provisioning is deliberately
absent.  A real implementation must obtain the peer secret from a bounded
OS-backed credential store, bind it to a launcher binary verified at startup,
rotate/revoke it, and expose the IPC endpoint with peer-process protections.
Caller-supplied SHA/Origin fields alone are **not** host attestation.

PR3-d does not alter the existing read-only Browser Bridge Host, whose MCP
bearer remains outside this design.  It neither exposes that bearer nor makes
the Browser Bridge a general MCP client.  After peer proof, PR3-c still applies
strict JSON checks, PR3-b grant scope/replay/revocation and PR3-a/PR1/PR2
provenance, fencing and ACK rules.
