# BCT deployment and service contract

## Boundary

BCT deploys only a named profile stored in `bct.toml`. A caller cannot supply a source
path, destination path, file list, service name, executable, command, or port. The
`bct_runtime_v1` remains the production profile and lists every copied file.
The deployment module retains tested support for a separately activated migration
target rooted at `%LOCALAPPDATA%\BCT\runtime`, but the shipped `bct.toml` no longer
declares such a target. `D:\BCT` is the only configured operating root. Historical
protected-path fixtures must not be selected for collaboration activation. If a
future, separately reviewed configuration declares one, its file set must
remain byte-for-byte equal to the production profile, and a cutover requires a
separate operating approval and a quiesced old Core.
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

- Source: `D:\BCT\source`
- Runtime: `D:\BCT\runtime`
- Releases: `D:\BCT\runtime\releases\<source-head>`
- Active pointer: `D:\BCT\runtime\current.json`
- Service ownership: `D:\BCT\runtime\service.json`
- Operation state: `D:\BCT\runtime\state\state.sqlite`

For the protected profile those paths are respectively
`%LOCALAPPDATA%\BCT\runtime\current.json` and
`%LOCALAPPDATA%\BCT\runtime\state\state.sqlite`. The literal
`%LOCALAPPDATA%` token is the only supported deployment-path variable. BCT
resolves it itself and rejects missing, relative, escaping, or other variable
forms. Source remains the exact clean `D:\BCT\source` main checkout.

Before hashing a deployment file BCT compares the worktree blob with the blob
recorded by the requested Git commit. This binds the SHA-256 release manifest
to that exact Git tree in addition to the existing clean-main check.

Protected-path preparation uses SQLite Online Backup, `quick_check`, and logical
digests for operations, unresolved claims, mailbox `consumed_at`, manager wakes,
consumption receipts/decisions, dispatch outbox and reconciliation receipts. It copies only an
active release whose files normalize to the exact Git blobs, Core tokens,
receipts/logs, BCT data and exact Supervisor payload, and writes no active
`service.json`. The old Core must be stopped, its Supervisor explicitly disabled,
and its runtime writer lock held for the whole backup/publish window.

`bct_runtime_protected_v1` cannot be used as a normal deployment shortcut. The
deploy path requires a `PUBLISHED` migration and a separate exact activation
receipt recording ACL, distinct-account denial and RCC canary acceptance. It
revalidates the old Core stop state and writer fence immediately before start.
The operation-owned `PREPARING` receipt is durable before any staging directory
is created; staging failures must be moved to quarantine before a retry. While
the old writer fence is held, an `ACTIVATING` cutover authority is made durable
before the target Core starts. Source starts are then denied even if the deploy
process exits between target health and the final `ACTIVATED` update. Target
starts require `ACTIVATING` or `ACTIVATED`; after a separately approved
`ROLLED_BACK` marker only the source may start. Once `ACTIVATED`, later exact-main
target upgrades validate that current authority instead of incorrectly requiring
the first migration and activation receipts to name every future release SHA.
- Health: `http://127.0.0.1:18790/health`

The runtime directory contains generated state and is never a source-of-truth checkout.
GitHub `main` remains the source of truth.

## Local recovery host

`modules/mcp/ops/BCT-Core-Supervisor.task.xml` is the one user-session recovery host for BCT Core.
It runs the exact runtime supervisor at sign-in and has a bounded Task Scheduler restart policy if
that supervisor exits unexpectedly. The supervisor still makes the final decision: it only starts a
Core process when the current immutable release, service receipt, PID fingerprint and health contract
prove that the previous process is absent or stale. A Chrome extension reload is intentionally not
performed by this host; Chrome owns that boundary and a version mismatch must remain visible to the
user.

`modules/mcp/ops/BCT-Tunnel-Supervisor.task.xml` is the matching user-session recovery host for the
private MCP tunnel. It starts the bounded tunnel supervisor at sign-in and restarts only that
supervisor after an unexpected exit. The task does not connect a tunnel itself; the supervisor
continues to require the exact executable, tunnel ID, target and health safeguards before any connect.
