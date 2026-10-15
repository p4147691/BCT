# Browser Bridge PR3-l — verified pipe relay composition

PR3-l joins the accepted, production-disabled boundaries without activating a
listener or choosing an operational credential location:

1. an injected operating-system verifier attests the connected pipe client's
   executable digest and matches it to the endpoint's active peer binding
   before request bytes are read;
2. the PR3-k codec decodes exactly one bounded canonical peer frame;
3. the attested digest must equal the launcher digest carried by the peer
   frame;
4. PR3-e independently resolves the active Bridge-only binding, verifies its
   proof and sequence, then calls PR3-c strict ingress; and
5. a result-publish failure after ingress is reported as an unknown effect and
   is never retried by the relay.

The implementation has no default verifier, provider, secret path, listener,
pipe name, registry entry, Chrome path, or runtime entry point.  Tests use an
in-memory secret and an explicit fixture verifier.  They do not establish a
real Windows-process attestation or authorize deployment.

Activation still requires a separately approved Bridge-only credential and a
Windows listener that implements the PR3-j PID/executable check plus the final
logon-session/DACL policy.  Existing BCT/RCC credentials, Native Hosts and
environment variables remain outside this path.
