# RCC Native Host named-pipe security boundary

Status: **SOURCE-ONLY HARDENING CANDIDATE / DEPLOYMENT_BLOCKED**. This document describes the isolated source-built candidate, **not** the installed RCC Host or a LIVE security acceptance.

## New source behavior

The source Host creates its per-instance pipe with a protected Windows DACL. It grants `FullControl` only to the current process token's exact `TokenLogonSid` (read using `GetTokenInformation(TokenLogonSid)`) and `LOCAL_SYSTEM`. Its owner is the current Windows user. SID lookup and ACL construction fail closed: there is **no** fallback to the default pipe DACL. Existing Native Messaging framing, pipe naming and the benign `presence` command are preserved.

`host:ready-ack` is also fail-closed: before emitting it, the Host synchronously creates the exact first `NamedPipeServerStream` with that protected DACL. A first-listener construction failure emits `host:pipe-failure` and never emits a ready ACK. If a later accept-loop/listener failure occurs, the Host logs it, clears its ready state and emits one `host:pipe-failure`; it does not automatically retry a listener or resend any prior browser command. After any startup or accept-loop failure, a process-local failure latch refuses further ready handshakes; only a separately authorized new Host process could start again. This is not permission to resend past UNKNOWN effects.

Before it creates a reader or parses request bytes, the Host requires both `GetNamedPipeClientSessionId` and `GetNamedPipeClientProcessId` to succeed, a nonzero client PID and an exact match to the server Windows session. Kernel identity lookup failures reject the client before request parsing.

The BCT Core client now performs the reciprocal connection gate before its
`before_write` policy/epoch/lease fence and before writing any request byte. On
the connected Pipe handle it requires `GetNamedPipeServerProcessId` and
`GetNamedPipeServerSessionId` to succeed, opens the actual server process token,
and compares its user SID, `TokenLogonSid`, and process session with the current
Core process. It also reads the Pipe kernel object's owner and DACL and requires
the exact source-Host descriptor: protected DACL, owner equal to the Host/Core
user SID, and exactly two non-inherited `FullControl` allow ACEs for that logon
SID and `LOCAL_SYSTEM`. Missing APIs, inaccessible process tokens, malformed
descriptors, extra principals, duplicate/inherited/deny ACEs, or any mismatch
fail as a pre-write `RelayUnavailable`. Once the write call starts, the existing
UNKNOWN/no-resend rule is unchanged.

The DACL description refers to explicit ACEs, not an OS-level guarantee against owner/admin descriptor changes. Repeated ready handshakes during a healthy listener still return the same exact pipe identity without starting a second listener.

## Observed isolated Windows evidence

- Current installed `RelayNativeHostV2.exe` SHA-256 at the beginning of the investigation: `3ED6B7B3F29B93FE88E7506A51A01A87AEF2CFCD6254101F786D49FBC9FB58EC`. Its byte-identical disposable clone used the default DACL `O:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BA)(A;;FR;;;WD)(A;;FR;;;AN)`, and a separate same-user process completed a benign `presence` request. This is evidence about the old installed binary copied into a random isolated instance; the operating Host was not touched.
- The new source is compiled to an executable in a disposable temporary directory with the Windows .NET Framework C# compiler. Its isolated pipe DACL has exactly two `FullControl` ACEs: the actual logon SID and `LOCAL_SYSTEM`, with no Everyone/Anonymous/broad Administrators ACEs and with the DACL protected.
- A separate same-logon test client gets an exact benign `presence` result from the source-built disposable Host.
- Real Windows `ImpersonateAnonymousToken` on a test thread, followed by `CreateFileW` against the disposable source-built Pipe, returns **ERROR_ACCESS_DENIED (5)**, and `RevertToSelf` restores the thread. No Windows account was created or modified.
- An invalid kernel pipe handle fails closed in the pre-read client identity check. The focused Windows suite includes a bounded immediate post-ACK connection and an isolated byte-copy startup-failure injection which proves that the first protected listener precedes ACK and that construction failure emits no ACK. The historical **3 PASS**/Python **563 PASS**/Browser Bridge **20 PASS** figures predate this follow-up and are not claims for the changed candidate or GitHub exact-head CI.

## Reviewed threat model and source-versus-LIVE boundary

The current BCT mainline is the existing authenticated private MCP tunnel -> BCT Core -> **existing RCC Host** -> Chrome. The single-operator desktop threat model was clarified in [mainline BCT trust-boundary policy](https://github.com/p4147691/BCT/blob/35684e303c1688760edb42f033d519b934984fe5/docs/BCT_MAINLINE_TRUST_BOUNDARY.md) (merged PR #154). **Arbitrary attacker-controlled code already running as the same Windows user in the same logon session is an explicitly accepted residual risk**, not a mandatory Core-to-RCC mutual-authentication requirement for this deployment. That scope decision is not proof that such an attacker is harmless, and it must be revisited for multi-user, service-account or higher-privilege designs.

The protected logon-SID DACL and reciprocal kernel session/PID/token checks
**do not identify the exact BCT Core**. A same-user, same-logon attacker can
create a descriptor satisfying these checks. PID, executable path/hash,
instance ID and logon SID are not cryptographic credentials; the Core verifier
deliberately does not promote image path or hash into authentication. Do not
describe this candidate as providing Core-only issuer or process
authentication, and do not add an SCM service, protected Broker or separate
Browser Bridge solely to solve the excluded same-user attacker model. Existing
Work/Principal/Policy, exact target/epoch/lease, receipt integrity and UNKNOWN
no-resend remain mandatory.

The separate normal Windows user/logon principal and unauthenticated remote MCP entry **remain in scope**. The source candidate is not itself a LIVE install, a trusted bearer-token permission fix, or a real browser-result/ACK acceptance.

## Production acceptance checklist (separate approvals)

| Gate | Required evidence | State of this source-only PR |
| --- | --- | --- |
| Source + Windows tests | Exact source commit; protected DACL limited to TokenLogonSid and SYSTEM; reciprocal Core validation of server PID/session/token/owner/DACL before write; negative Anonymous and broad fake-server cases; same-logon benign `presence`; first-listener-before-ready, failure latch and repeated-ready; Windows CI and independent source audit | **COMBINED EXACT-HEAD CI/AUDIT REQUIRED** before merge |
| Different normal Windows account | Disposable pipe tested from a distinct ordinary Windows logon account/session; access denied before request parsing; no fallback to world-readable DACL | **PENDING**. `ImpersonateAnonymousToken` denial is not a substitute; do not create accounts or modify live HKCU/Registry for this check without approval |
| Runtime and credential-file ACL | Independently verify no unrelated Windows user can read/modify MCP/control tokens, SQLite, release pointers or installed Host image; exact owner/SYSTEM/Admin permissions, path ancestors and compatibility/rollback proof | **PENDING / BROAD CURRENT ACLS OBSERVED**; requires a separate, explicitly approved permissions change if needed |
| Installed RCC Host identity | Exact deployed binary SHA and source-built manifest; effective installed Pipe DACL `D:P`, only intended logon SID and SYSTEM allow ACEs; connection session/PID checks, no startup success before listener; distinct-account negative proof | **NOT INSTALLED / NOT ACCEPTED** |
| Existing Core-RCC compatibility | Verify Core and Host actually use the intended Windows session and Pipe framing; one bounded harmless `presence`/state probe; preserve RCC instance, existing tabs, relay bindings, MCP tunnel and current Core operation receipts | **PENDING AFTER SEPARATELY APPROVED INSTALL** |
| Durable browser E2E | Only on a newly authorized, exact Work-allowlisted Schema 2 session: Worker RESULT_PERSISTED -> Manager Wake/decision -> successor or COMPLETE -> delivery and ACK, no duplicate writes or UNKNOWN resend | **NOT AUTHORIZED / SEPARATE GATE** |

**Read-only Windows ACL preflight (2026-10-17):** the current runtime credential/state files and installed Host image inherit access broader than the in-scope *different-Windows-account* boundary. Pipe hardening alone therefore cannot establish cross-account protection of the surrounding assets. Narrowly scoped file/ancestor ACL correction, negative access checks, rollback proof, and operator approval must be handled separately. Detailed operating-file permissions are intentionally kept in the operator's private preflight report rather than published as a security inventory. No token **contents** were read and no ACLs were changed during this inspection.

**Installed Host baseline:** the actually installed EXE still hashes to `3ED6B7B3F29B93FE88E7506A51A01A87AEF2CFCD6254101F786D49FBC9FB58EC`, so it is the old binary, not this reviewed candidate. A disposable byte-identical clone had default WD/AN read ACEs; this is not an assertion that the installed operating Pipe was directly opened or changed.

## Narrow ACL backup and operating acceptance plan

No ACL is changed by this source PR. The later operating approval must scope
changes to the precise runtime assets that cross the different-Windows-account
boundary: `D:\BCT\runtime\mcp.token`, the SQLite database plus existing WAL/SHM,
`current.json`, `service.json`, the active release/deployment directories, and
`D:\ChromeExtensions\RCC` Native Host/manifest files. For each target and only
the ancestors whose `Modify`/`DeleteChild` rights can replace it, record owner,
inheritance state and exact SDDL before mutation. Do not recursively rewrite
`D:\`, all of `D:\BCT`, or unrelated Chrome extensions.

Store the descriptor inventory and file-hash manifest in a separate
operator-only backup location, create and verify a SQLite online backup with
`quick_check`, and prove descriptor restoration on an isolated fixture. Restore
parent descriptors before child descriptors, restore the exact known-good Host
bytes/configuration, then restore runtime pointers and confirm database health.
Operating acceptance still requires a distinct ordinary Windows account to be
denied read/write/delete/replacement access while the legitimate interactive
Core and RCC Host retain access. Anonymous-token denial is not a substitute.

## Safe cutover and rollback contract

1. **READ-only preflight:** confirm expected GitHub main/source head, candidate exact SHA and Windows tests; record Core PID/generation/session, Host PID/session/binary SHA, RCC exact instance + tab identities and current UNKNOWN/Claim/Issue #111 digests. Do not assume current tab *count* is fixed.
2. **Separate approval for any file/ACL or Host installation:** back up the affected installation files, manifest/configuration and permission descriptors; prove rollback and no conflict with active operations. Restrict only narrowly defined assets; do not recursively rewrite `D:\BCT` or modify `mcp.token` contents, the SQLite DB or other programs.
3. **Host-first compatibility canary:** install the *exact* reviewed protected Host image through the existing RCC deployment mechanism while the currently deployed legacy Core client is still active. The protected Host accepts that legitimate same-session client, so perform only one bounded benign presence/state check and verify effective Pipe DACL, exact process/session identity, stable RCC instance/tab identities and distinct-account denial. Do not create/close Chrome tabs or send Worker messages.
4. **Core second:** only after the Host canary passes, deploy the exact merged Core containing reciprocal server verification. Re-run the same bounded benign probe and prove the request reaches the protected Host. Deploying this Core against the old default-DACL Host is prohibited: it intentionally fails closed before write.
5. **Fail closed / back out:** unexpected Pipe/Host lifecycle, permission denial of the legitimate Core, unexpected RCC binding/tab change, health regression, or unauthorized access means stop. If Core activation failed before write, restore the exact previously approved Core release, then restore only the exact known-good Host image/ACLs as preapproved. A post-write UNKNOWN never authorizes resend; preserve persistent receipts.
6. **Separate Schema 2 approval:** do not activate the global flag or Work allowlist, and do not perform live Manager/Worker E2E, until the above applicable installation gates and isolated acceptance are signed off.

**Current verdict: SOURCE_ACCEPTABLE / DOCUMENTED_PERSONAL_DESKTOP_RESIDUAL_RISK / RUNTIME_ACL_AND_INSTALLATION_ACCEPTANCE_PENDING.** PR #153 stays Draft until separately authorized. Schema 2 remains OFF, the allowlist remains empty, and existing Browser Bridge PR3 work is independent. No LIVE/Core/RCC/Chrome/HKCU/Registry, Issue #111, UNKNOWN, Claim or `consumed_at` mutation is authorized by this document.
