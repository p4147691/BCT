# GitHub Completion Inbox V1 — isolated implementation report

## Implemented

- Replaced the process-local daemon thread with the existing detached `operation_worker` pattern. `github_run_watch` is registered in `BACKGROUND_CAPABILITIES`; its dedicated MCP tool and generic MCP selector return after durable registration.
- The detached child performs bounded polling (5–30 seconds; configured bounded timeout) until one terminal Inbox write. It remains independent of the Core server process.
- Extended narrow orphan recovery for durable `github_run_watch` jobs only when the recorded PID/fingerprint is proven absent. It does not create subscriptions, claims, Git/main/deploy actions, or a second live worker.
- Registration is per Work/run/SHA resource; duplicate run/SHA merges recipients without another network poll. Initiator, at most 16 explicit nodes, and an explicit optional manager node are supported.
- SQLite persists per-recipient `next_step`, terminal-only unread state, idempotent terminal ACK, terminal duplicate-recipient merge, and `READY_IN_INBOX` delivery state. Monitor projection is read-only and never changes Work state or leases.
- Validation rejects boolean/non-positive run IDs, non-exact SHA, missing trigger, malformed/bounded recipients/context, and invalid polling configuration.
- `bct_inbox_get` requires an owned Work and node filter; compact `bct_status` bounds its Inbox projection.
- Added a minimal text-only GitHub Inbox panel next to `#monitorWorkers`, sourced from `MonitorBctShell.monitorState()` using `textContent`. Protected thumbnail fallback code was not changed.
- Auto-wake is deliberately safe-only: no fresh exact idle RCC tab/session proof was available, so results remain `READY_IN_INBOX` / `AUTO_WAKE_NOT_CONFIGURED`. Nothing is sent to a user tab and UNKNOWN is never resent.
- Added 14 focused mock/SQLite tests covering outcomes, deduplication, recipients/manager, unread/ACK, per-recipient next steps, validation, and Monitor projection. MCP integration catalogue expectations include the watch and Inbox tools.

## Verification (2026-10-25, N40 isolated worktree)
- Python 3.12.10 at `C:\Users\시우세영\AppData\Local\Programs\Python\Python312\python.exe`, invoked with `-B -X utf8` to avoid bytecode cache and force UTF-8 mode.
- `tests/test_github_inbox.py` via unittest discovery: **21/21 PASS** (6.558s).
- `tests/test_mcp_integration.py` via unittest discovery: **1/1 PASS** (8.057s).
- Combined focused unittest: **22/22 PASS**.
- Python `ast.parse` over 9 changed/new Python source and test files: **PASS**; this is not `compileall`.
- `node --check modules/monitor/extension/monitor.js`: **PASS**.
- `git diff --check`: **PASS**.
- Windows Git line-ending advisory (LF→CRLF) appeared; it was **not** a test failure. Non-UTF-8/default Windows console mode was not separately verified.
- These are isolated tests; no Core restart, end-to-end terminal Inbox notification or physical RCC wake acceptance is claimed.

## Remaining

- No public webhook/tunnel or physical wake is implemented.
- Focused Python unittest verification is complete (22/22 PASS); broader regressions and physical LIVE acceptance remain outstanding.
- No commit, push, PR, deploy, Core restart, or live action was performed.
