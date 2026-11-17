# BCT-owned Desktop Agent/Supervisor extraction — isolation design (2026-11-08)

Status: STAGING ONLY, **NOT DEPLOYED**, independent Supervisor approval NOT obtained.
Work: voice-desktop-rcc-identity-diagnosis-20261108
Direction: direction-b7af829726dc48afa5a99c4d
Task: desktop-extraction-n25-manager-20261108-01, generation 1
Existing N25 Manager: VTL desktop capture recovery, network.a11785d6724d4430b1002429f5d5e349.
This Work owns a distinct BCT staging branch and does NOT replace N25 or the global Supervisor.

## Existing boundaries verified
- BCT Core already owns DesktopSessionClient, desktop_capture and desktop_session_status MCP features, their claims/receipts, and endpoint contract.
- Agent executable, build scripts, the legacy supervision loop, release pointer and installer remain VTL owned.
- VTL PR #53 SHA 5003d1dc1bdf8ed38e156c4741c34e73177d49bd is OPEN; GitHub validate SUCCESS, but previous review flagged broad catch on Get-Process as unsafe and independent review was not present in prior report.
- Local BCT main HEAD at this observation: 5bf2fd620ba000c41ddbfcaa27a3db415c5198f2; clean.
- N25 VTL isolated worktree was clean at SHA 5003d1dc1bdf8ed38e156c4741c34e73177d49bd. That Work remains a separate project.
- Attempt to read D:\TOOLS\VTL\current.json through this Work was denied TARGET_OUTSIDE_WORK_SCOPE; live manifest/version is NOT freshly verified here.

## BCT ownership target
1. BCT source: copy the approved Agent C# source plus its inventory/Chrome/UIA helper sources under a new BCT-owned module, carrying their upstream source SHAs, license and provenance. Do NOT point new runtime to D:\TOOLS\VTL or silently modify the legacy deployment.
2. BCT builds an immutable signed/hash-pinned desktop-agent release manifest and executable. New BCT Supervisor must use only this approved release; existing VTL release is not mutated.
3. BCT runtime Session-bound Agent is created ONLY through an authorized interactive-user lifecycle route. Service Session 0 must not impersonate an interactive Session 2; require verified session, user SID, logon SID and executable/process-birth identity.
4. Endpoint schema migration is staged/opt-in: preserve legacy protocol until new Agent and client negotiate an explicit new version. Prevent two live supervisors from writing the same endpoint.json. Separate state roots and named pipe names during shadow testing.
5. Validate endpoint JSON, pipe server PID/session, owner SID, executable digest, process creation time and heartbeat freshness before accepting an Agent. A stale PID with OS-confirmed nonexistence permits a *candidate* restart; any access-denied or uncertain existence is HOLD. Never auto-stop another session's process.
6. All possible external effects (launch, stop, endpoint swap, scheduled task changes) require exact Work/Operation receipts, ownership proof and an independent authorization gate; UNKNOWN never replays by a new ID.
7. Deployment sequence: source provenance -> isolated build/structural tests -> Windows Session test -> independent global Supervisor review -> exact CI SHA PASS -> protect deployment -> phased cutover verifying old owner release -> verify new endpoint/pipe/session -> desktop_session_status -> desktop_capture image/PNG evidence -> smartphone same-chat render confirmed by user. If any gate fails, rollback to the last verified owner without killing unowned Agents.
8. Preserve N25's PR #53, Codex queues, Browser Bridge, all dirty worktrees and all existing receipts; coordinator remains global Supervisor, not a VTL-only node.

## This isolated implementation
src/bct/desktop_agent_ownership.py is a PURE, read-only state decision helper, with no process launch, stop, endpoint write, file cleanup or ownership takeover. It maps OS-confirmed absent PID to ABSENT, a verified matching live Session Agent to READY, and all foreign/uncertain/identity failures to HOLD. That is only a prerequisite; it does NOT integrate into production feature dispatch and does NOT claim migration completion.
tests/test_desktop_agent_ownership.py covers nine outcomes; existing BCT desktop session tests cover 54; **63/63 PASS** on isolated worktree.

## Mandatory HOLD conditions still active
- No independent global Supervisor signed review for this staging branch.
- No exact BCT PR/CI SHA for this staging change (until publication), and VTL PR #53 is independent.
- No BCT-owned Agent executable or independent BCT Supervisor implementation/pinned release manifest yet.
- No proven protected cutover or actual Session 2 Agent connection.
- No actual desktop_capture PNG or smartphone E2E was produced.

Result: source isolation and a guardrail candidate only. Do not merge/deploy LIVE until these are resolved.
