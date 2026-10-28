# BCT PC P2 후속 개발 — 안전 계획·승인 경계 인수인계

- Work: \`BCT-PC-P2-SAFETY-ISOLATED-20261029\`
- Branch: \`feature/pc-safe-action-plans-20261029\`
- Base: origin/main \`4819c29\` (Explorer PR #344 merged); PR #346 file discovery/diagnostic is still **OPEN**, not incorporated.
- Purpose: safe read-only preflight for explicit file reorganization and exact-process stop requests. **No irreversible effects were implemented or performed.**

## Existing capabilities reused
- \`read\` scoped file read/directory tree/snapshot (PR #346 adds discovery, comparison).
- \`write\` atomic text write with SHA proof only (not arbitrary binary move/delete).
- \`process_session.stop\` already safely stops **owned** BCT process sessions, with identity and receipt checks; do not duplicate.
- \`system_inspect.process\` obtains process identity (PID, executable, creation time).
- \`Policy.decide\` has approval-required actions, but returns \`APPROVAL_VERIFIER_UNAVAILABLE\` when an approval reference is supplied. **This is not permission to bypass approval.**

## Changes implemented in this PR
- \`file_action_plan\`: work-scoped \`move_preview\` or \`quarantine_preview\` using exact source and destination paths. Reject reparse links, destination collisions, changed or oversized source, cross-device operations. Fully hash up to 64 MiB; return stable plan SHA256 and explicit proposed rollback path. **No rename, delete, folder create, copy, ACL modification, or real effects.**
- \`process_stop_plan\`: read-only exact PID/process-birth/executable comparison. Report identity; \`stop_available=false\`, \`ownership_verified=false\`, and existing owned \`process_session.stop\` guidance. **No terminate, kill, service-stop, or child-process signal.**
- Both are ordinary Work+Operation capabilities with durable receipt and principal scoping; the new capabilities grant **only observation**, not actual cleanup authority.
- MCP descriptions and explicit release-file list included. Existing unrelated APIs/Chrome/RCC/Monitor untouched.

## Calls (future after deployment)

\`bct_file_action_plan({work_id,operation_id,arguments:{"operation":"quarantine_preview","source":"D:\\path\\one.bin","destination":"D:\\quarantine\\one.bin"}})\`

\`bct_process_stop_plan({work_id,operation_id,arguments:{"pid":1234,"expected_created_at":1700000000.0,"expected_executable":"C:\\Program Files\\App\\app.exe"}})\`

The model should first obtain exact paths/process identity, confirm scope, request Work authorization and only then plan. The plan is a **non-executable proposal**.

## Required follow-up BEFORE destructive P2 implementation

1. Build independent authenticated and auditable approval-verifier store for \`file_action_apply\`, \`process_force_stop\` bound to exact principal, Work, operation/request digest, expiration and one-time consumption. No plain \`approval_ref\` bypass.
2. Add a reversible, owner-approved, atomic same-device file move/quarantine effect (never permanent deletion by default). Preflight precise inode/hash/mtime, no overwrite, original path and rollback receipt. Reconcile UNKNOWN via exact read-only outcome before resubmission.
3. Add conditional process stop only for explicitly owned and eligible processes with PID+birth+binary+user-session guard; prevent Core/Chrome/RCC/Monitor/Runner/other Work termination; verify descendants, stop result, and rollback impossibility clearly.
4. Test mock plans, approval denial, authorized ephemeral sandbox E2E, versioned end-to-end receipts and physical real-user test after supervisor-controlled deployment.
5. Supervisor checks required GitHub CI, merges main, exact LIVE deploy and physical E2E. This node does **not** merge/deploy.

## Acceptance status

- New isolated tests: 17 PASS (file preview, collisions, scope, symlink, PID identity, no termination, Work receipt reuse, deny unauthorized action).
- Deployment import closure and module-layout tests PASS.
- GitHub CI: must be verified against final head before merge-ready.
- Final acceptance is **P2 planning ready**, not destructive-action ready, not LIVE.
