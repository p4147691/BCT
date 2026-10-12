# BCT deployment and service contract

## Boundary

BCT deploys only a named profile stored in `bct.toml`. A caller cannot supply a source
path, destination path, file list, service name, executable, command, or port. The
`bct_runtime_v1` profile is the sole production profile and lists every copied file.
Wildcards, directories, path traversal, symlinks, and uncommitted source are rejected.

## Deployment lifecycle

1. Verify the source is the clean `main` checkout at the exact requested commit.
2. Hash the exact profile file set.
3. Copy into an immutable staging directory and verify every copied hash.
4. Atomically rename staging into `releases/<source-head>`.
5. Atomically update `current.json`.
6. Start or replace only the profile's service and require exact health identity.
7. Commit a durable deployment receipt.

If activation or readiness fails, BCT restores the previous `current.json` and the
previous running release. A verified rollback is `FAILED`; an unverified rollback is
`UNKNOWN` and retains the operation's resource claim.

An older immutable release is verified against its own fenced manifest, while the new
release must exactly match the current named profile. This permits a reviewed profile to
add or remove files without weakening either old-release rollback or new-release bounds.

When deployment or core service control is requested through BCT's own MCP endpoint, a durable
one-shot worker executes it after the request has returned.  This avoids asking the service being
replaced to synchronously wait for its own PID to exit.  The common operation ID is fenced before
the worker is launched, duplicate calls return the same `RUNNING`/terminal receipt, and the worker
finishes that exact operation in the shared state store after restart and health verification.

## Service ownership

The controller launches one fixed Python module from the immutable release. It records
and verifies the PID, executable, OS process creation marker, derived fingerprint,
release SHA, manifest SHA, generation, and random instance ID. Health is accepted only
when every field matches both the durable service receipt and the current OS process.
An endpoint without the matching receipt is never adopted.

Shutdown uses a per-runtime random control token and then verifies both process exit and
endpoint disappearance. Restart records the previous PID and fingerprint and requires a
new identity. Operation IDs are handled by the core receipt store, so replay returns the
original result without repeating deployment, start, stop, or restart.

## Stable paths

- Source: `D:\PROJECTS\BCT`
- Runtime: `D:\BCT\runtime`
- Releases: `D:\BCT\runtime\releases\<source-head>`
- Active pointer: `D:\BCT\runtime\current.json`
- Service ownership: `D:\BCT\runtime\service.json`
- Operation state: `D:\BCT\runtime\state\state.sqlite`
- Health: `http://127.0.0.1:18790/health`

The runtime directory contains generated state and is never a source-of-truth checkout.
GitHub `main` remains the source of truth.
