# Browser Bridge PR3-h — explicit DPAPI file store

PR3-h implements a create-only `PeerSecretStore` for a future Bridge binding.
It uses PR3-g DPAPI with a binding-specific non-secret context and an opaque
SHA-256 filename. A file stores only protected bytes, never the peer ID or
plaintext secret. Reusing a peer/generation fails through exclusive file
creation; deletion targets only the derived Bridge file.

There is deliberately no default location and the constructor never creates a
directory. An activation caller must explicitly supply a pre-created,
Bridge-owned directory after verifying its Windows ACL and ownership. This PR
does not create such a directory outside a disposable test fixture, start IPC,
or provision any real binding.

Same-user DPAPI protects stored bytes at rest, not the identity of an arbitrary
same-user process. The protected pipe/process gate remains required before a
runtime listener can be enabled.
