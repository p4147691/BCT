# BCT Loop Recipe — isolated candidate review evidence (2026-11-11)

Work: `bct-loop-recipe-20261111`
Direction: `direction-6fdb6878f4484275aafd37b3`
PR: #470
Boundary: isolated feature worktree only; do not merge/deploy from this note.

## Candidate behavior

- Shared Chain state and execute-plan rules are preserved.
- Loop SELF queue, exact RCC send receipts, response-source binding and completion fencing are implemented in the candidate.
- Successor recovery uses two distinct fresh disconnected observations, an exact original creation Operation, an exact first-send receipt, an actual observed conversation UUID, an exact handoff response source and hash, then a canonical NodeRecovery PAUSE fence before one atomic Loop Epoch transfer.
- CREATE_DISPATCHING / SEND_DISPATCHING have no blind retry; missing or uncertain original receipts hold the case.
- Prior owner reconnection takes priority; missing attachment, ambiguous UUID, unresolved effects and unsupported browser authorization fail closed.
- The successor bootstrap is limited to one verifiably created blank tab, never an arbitrary user tab.

## Verification

- Isolated Loop and successor state-machine tests: pass (see exact commit CI and command receipts).
- Fresh detached worktree: Loop 54/54 PASS, Chain and NodeRecovery 42/42 PASS (before follow-up exact-fence hardening).
- Real RCC transport test in a separately scoped test Work: new window creation APPLIED, first send APPLIED, actual UUID verified and expected TURN1 reply observed. Second send to the same exact UUID was NOT_APPLIED with `RELAY_EDITOR_FOCUS_OR_CARET_INVALID`; one retry after confirming NOT_APPLIED failed with the same reason. No UNKNOWN send was replayed and no operating chat was targeted.
- This real RCC test uses the currently installed Core/RCC, not the uninstalled feature candidate. It does not establish physical Loop automatic recovery acceptance.

## Remaining acceptance HOLD

1. Repair and independently validate RCC existing-tab composer focus/caret behavior; repeat physical two-turn Loop E2E.
2. Exercise actual Core/reconnect/crash and automatic successor recovery in a disposable isolation environment with the candidate installed, including Watch identity and no-duplicate guarantees.
3. Obtain genuinely independent Supervisor acceptance for the exact candidate SHA; a detached worktree tested by the author is not independent reviewer sign-off.
4. Check exact SHA full CI and protected integration rules before any main/LIVE change.

Original Work, Direction, unresolved claims, operations and production main/LIVE are protected.
