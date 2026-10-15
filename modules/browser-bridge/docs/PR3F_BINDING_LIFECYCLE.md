# Browser Bridge PR3-f — disabled binding lifecycle

PR3-f adds only the transport-neutral lifecycle metadata required to inject a
future `PeerBindingProvider` into PR3-e. It creates no Windows credential,
registry key, named pipe, listener, Chrome profile, or runtime resource.

The caller injects a create-only `PeerSecretStore` (an already present
peer/generation key must fail rather than overwrite); BCT SQLite persists only peer ID,
binding generation, fixed origin, launcher digest, state and timestamps. Raw
secrets never enter SQLite, receipts, errors or logs. There is intentionally no
default store and no disk-backed fallback.

Lifecycle is fail-closed:

1. provision stores an externally supplied 32-byte Bridge-only secret before
   atomically recording one `ACTIVE` generation; failed metadata writes attempt
   to remove only that new secret;
2. each generation is single-use; rotate accepts only the next generation,
   atomically retires the old metadata
   and activates the new metadata; PR3-e then resolves only the new generation;
3. revoke marks metadata `REVOKED` before attempting external deletion, so a
   failed delete cannot reactivate the peer; and
4. missing, malformed or unavailable secret-store values resolve to no binding.

This proves the lifecycle contract in isolated SQLite/fake-store tests. It does
not choose or approve an OS secret provider, attest a same-user process, or
activate an IPC endpoint. Those remain separate activation work.
