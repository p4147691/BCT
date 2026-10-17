# BCT protected operating paths

## Purpose and fixed boundary

The current Core deployment under `D:\BCT\runtime` inherits an ancestor
`DELETE_CHILD`/Modify boundary that cannot be repaired safely by changing only
its children. The minimal replacement root is the current interactive user's
`%LOCALAPPDATA%\BCT`. This does not move source, Git worktrees, GitHub runners,
the proxy, unrelated modules, or any other project. `C:\ProgramData` is not
needed while Core and RCC remain in the same interactive logon boundary.

Source support is deliberately non-activating. The existing
`bct_runtime_v1` remains authoritative. `bct_runtime_protected_v1` resolves only
the exact `%LOCALAPPDATA%` prefix and is itself deployment-gated. A protected
deploy requires a published migration plus a separately approved activation
receipt, old Supervisor stop flag, stopped old Core and a free old-runtime
writer lock. The protected start holds that source lock until the new Core is
healthy and a durable `BCT_PROTECTED_CUTOVER_V1` authority marker is published.
The legacy deploy, service-control, Supervisor, and direct runtime-server entry
paths all reject start/restart while that marker is active. An explicit rollback
must stop the target and replace the authority receipt before the old Core can
be started; deleting or ignoring the marker is not a rollback.
`prepare_core_migration()` obtains that same exclusive writer
fence, rechecks the real service state, and stages an exact-Git release, SQLite
Online Backup, tokens, receipts/logs, process-session data and both Supervisor
scripts. It never trusts caller-supplied RUNNING/STOPPED strings.

Core and RCC staging use operation-scoped directories and durable
`PREPARING`/`PREPARED`/`PUBLISHED` or `FAILED` receipts. A partial target cannot
be retried implicitly; the receipt-owned files must first be moved to the
protected quarantine by the bounded rollback helper. No partial copy is ever
eligible for activation.

## Exact operating targets

| Asset | Protected target |
| --- | --- |
| Core releases, current pointer, service/token/log/deployment receipts | `%LOCALAPPDATA%\BCT\runtime` |
| SQLite plus new WAL/SHM and BCT process-session data | `%LOCALAPPDATA%\BCT\runtime\state` and `%LOCALAPPDATA%\BCT\data` |
| RCC Native Host executable and generated manifest | `%LOCALAPPDATA%\BCT\rcc\native` |
| RCC unpacked extension payload | `%LOCALAPPDATA%\BCT\rcc\extension` |
| Git source authority | unchanged `D:\BCT\source` exact clean main |

The runtime migration must not copy `D:\BCT\runtime\runners`, `modules`, proxy
payloads, supervisor locks/stop flags, or the old active `service.json` into an
active role. The deployment manifest remains bound to the exact Git tree and
is verified again after copy.

## One separately approved cutover

1. Re-read main/LIVE SHA, active Work/operations, Core/RCC/tunnel identity and
   Chrome's exact loaded RCC extension path. Abort on drift or active executor.
2. Create external SDDL/file-hash and SQLite Online Backup evidence. Prove that
   rollback material is outside the path being changed and can be read.
3. Create only `%LOCALAPPDATA%\BCT`, disable inheritance there, and grant full
   control only to the exact interactive user SID, SYSTEM and Administrators.
   Collect owner, inheritance, all ACEs and every ancestor through
   `%LOCALAPPDATA%`; validate raw access masks, reject every foreign ACE on the
   protected root, foreign ancestor write/DeleteChild, and lexical reparse
   points before any canonical-path resolution.
4. Stop the old Core and its Core supervisor once. Recheck PID/creation marker,
   port, service receipt, background executor and both old/target stopped state.
   Tunnel and RCC may remain connected but no browser command is sent.
5. Deploy this source to the old path first so the Core writer lock and exact
   Supervisor payload are present. Then run migration preparation once with a new deterministic operation
   ID. Verify release hashes, database `quick_check`, preserved receipt counts
   and hashes, target tokens and the non-activating migration receipt.
6. Stage the exact protected RCC Host and manifest. Extension bytes come from
   the exact Git tree. The Host EXE is compiled inside the protected boundary
   from the exact Git C# blob using the system compiler, then bound to a durable
   operation-scoped source-tree/compiler/artifact receipt; an installed Host
   supplied by the caller is not accepted as build authority. Verify source SHA, Host name,
   sole allowed origin and fixed extension ID
   `ocbidbaplechjjdacmokhnfbdmgjkphf`. A different ID is an immediate stop.
7. The unpacked extension path cannot be changed merely by copying files. In an
   approved Chrome maintenance window, switch the existing unpacked item to the
   protected payload only if Chrome reports the same fixed ID and existing
   storage/instance/conversation/tab identities remain available. Otherwise
   roll back the path and stop; never create a second RCC identity.
8. Render the separate Core and tunnel protected Task templates with the exact
   `%LOCALAPPDATA%\BCT\runtime` path. Change the exact HKCU NativeMessagingHosts
   manifest value and scheduled tasks only in the approved maintenance window,
   supervisor arguments to the protected paths, with exported registry/task XML
   as rollback evidence. Start one protected Core using
   `bct_runtime_protected_v1` and prove exact release, generation increment,
   one listener, MCP 22-tool readiness, RCC benign presence and unchanged
   durable receipt hashes.
9. Keep Schema 2 OFF and the allowlist empty. Only after the protected-path and
   distinct-account acceptance succeeds may a later approval activate the one
   isolated Schema 2 E2E Work.

## Rollback and mandatory stops

Before target Core start, rollback is a receipt-owned atomic move to the
protected quarantine; it never deletes ambiguous paths. Then restart the exact
old release. After target start, stop the target first, restore the exact
registry/task references and old `current.json`/release, prove only one database
writer, atomically record an approved cutover rollback, then start the old Core.
Never merge two databases. RCC pre-publish staging and exact-head Host build
staging are operation-owned and are quarantined before a retry.

Stop on any unknown process identity, ACL/SDDL mismatch, reparse point, source
or manifest hash mismatch, failed SQLite backup/quick-check, receipt-count or
Issue #111 digest change, extension-ID/path mismatch, lost RCC instance/tab
identity, or UNKNOWN external effect. UNKNOWN is inspected from receipts and is
not retried.

The copied legacy token/database remain sensitive. Rotation and verified
retirement of the old copies require a separate destructive operating approval;
the migration receipt records `legacy_sensitive_copies_retired=false` until
that work is completed.

## Security acceptance still required

An isolated ordinary-account fixture must show denial of runtime token/SQLite,
replacement/deletion of protected Core/RCC files, and fake Pipe server access.
Test-account creation or deletion is not authorized by this source change. The
same-logon-user malicious-process risk remains the explicitly accepted residual
risk from the current personal-PC threat model.
