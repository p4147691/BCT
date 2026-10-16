# RCC Native Host named-pipe security boundary

Status: **SOURCE-ONLY HARDENING CANDIDATE / DEPLOYMENT_BLOCKED**. This document describes the isolated source-built candidate, **not** the installed RCC Host or a LIVE security acceptance.

## New source behavior

The source Host creates its per-instance pipe with a protected Windows DACL. It grants `FullControl` only to the current process token's exact `TokenLogonSid` (read using `GetTokenInformation(TokenLogonSid)`) and `LOCAL_SYSTEM`. Its owner is the current Windows user. SID lookup and ACL construction fail closed: there is **no** fallback to the default pipe DACL. Existing Native Messaging framing, pipe naming and the benign `presence` command are preserved.

`host:ready-ack` is also fail-closed: before emitting it, the Host synchronously creates the exact first `NamedPipeServerStream` with that protected DACL. A first-listener construction failure emits `host:pipe-failure` and never emits a ready ACK. If a later accept-loop/listener failure occurs, the Host logs it, clears its ready state and emits one `host:pipe-failure`; it does not automatically retry a listener or resend any prior browser command. After any startup or accept-loop failure, a process-local failure latch refuses further ready handshakes; only a separately authorized new Host process could start again. This is not permission to resend past UNKNOWN effects.

Before it creates a reader or parses request bytes, the Host requires both `GetNamedPipeClientSessionId` and `GetNamedPipeClientProcessId` to succeed, a nonzero client PID and an exact match to the server Windows session. Kernel identity lookup failures reject the client before request parsing.

The DACL description refers to explicit ACEs, not an OS-level guarantee against owner/admin descriptor changes. Repeated ready handshakes during a healthy listener still return the same exact pipe identity without starting a second listener.

## Observed isolated Windows evidence

- Current installed `RelayNativeHostV2.exe` SHA-256 at the beginning of the investigation: `3ED6B7B3F29B93FE88E7506A51A01A87AEF2CFCD6254101F786D49FBC9FB58EC`. Its byte-identical disposable clone used the default DACL `O:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BA)(A;;FR;;;WD)(A;;FR;;;AN)`, and a separate same-user process completed a benign `presence` request. This is evidence about the old installed binary copied into a random isolated instance; the operating Host was not touched.
- The new source is compiled to an executable in a disposable temporary directory with the Windows .NET Framework C# compiler. Its isolated pipe DACL has exactly two `FullControl` ACEs: the actual logon SID and `LOCAL_SYSTEM`, with no Everyone/Anonymous/broad Administrators ACEs and with the DACL protected.
- A separate same-logon test client gets an exact benign `presence` result from the source-built disposable Host.
- Real Windows `ImpersonateAnonymousToken` on a test thread, followed by `CreateFileW` against the disposable source-built Pipe, returns **ERROR_ACCESS_DENIED (5)**, and `RevertToSelf` restores the thread. No Windows account was created or modified.
- An invalid kernel pipe handle fails closed in the pre-read client identity check. The focused Windows suite includes a bounded immediate post-ACK connection and an isolated byte-copy startup-failure injection which proves that the first protected listener precedes ACK and that construction failure emits no ACK. The historical **3 PASS**/Python **563 PASS**/Browser Bridge **20 PASS** figures predate this follow-up and are not claims for the changed candidate or GitHub exact-head CI.

## Remaining deployment blockers

**This is not authentication of BCT Core.** Any arbitrary program running in the **same Windows user and logon session** can satisfy the new DACL and session check. The kernel client's PID is only an observed identifier and is **not** a trusted BCT process identity or an authenticated capability. An authorized issuer / exact-core caller binding (or a stronger reviewed mechanism) is still needed before allowing unattended BCT Core-to-RCC messages.

The anonymous denial is **not** a real separate normal-user-account negative E2E and is **not** proof against arbitrary same-user callers. This work does **not** prove the effective DACL of a deployed updated Host, an operational Core-only authorization boundary, real Chrome/RCC delivery/ACK, or an approved schema-2 deployment.

**DEPLOYMENT_BLOCKED** remains in force and schema 2 stays **OFF**. No installation, restart, Chrome/RCC operation, HKCU/Registry mutation, existing Issue #111/UNKNOWN/Claim update or resend is part of this candidate. The existing Browser Bridge PR3-n / PR3-o authorization boundary is separate; its fixture acceptance does not secure the RCC Native Host.
