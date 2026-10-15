# Browser Bridge PR3-g — DPAPI codec boundary

PR3-g adds a Windows-only, in-memory codec for one 32-byte Bridge secret and
an explicit non-secret binding context. It invokes DPAPI with UI forbidden,
frees native result buffers, and fails closed on wrong context, malformed data
or platform/API failure.

It does **not** create or select a credential target, write any file,
registry value, Credential Manager entry, receipt or log, start an IPC server,
or expose a default `PeerSecretStore`. The protected byte blob exists only in
the calling process unless a later, separately reviewed provider persists it.

DPAPI protects a value for the current Windows user/machine at rest; it is not
proof that an arbitrary same-user process is the approved Bridge Host. A later
provider and IPC activation still require exact Host/process verification and
separate approval.
