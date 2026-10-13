# BCT Modular Cutover V1

Status: `RUNNERS_MIGRATED_MONITOR_V2_LIVE_ACCEPTED_ARCHIVE_CLEANUP_REMAINS`

## Goal

Make BCT understandable and independently operable without retaining ACT as a hidden runtime
dependency. BCT is the product root; Core is the small deterministic kernel; installable or
replaceable capabilities are modules.

## Fixed boundaries

- `src/bct/core`: authentication-derived principal, policy decision, work, operation, receipt,
  conflict and durable state only.
- `modules/bdc`: desktop/native UI control.
- `modules/rcc`: browser conversation control. RCC is the product name; Relay is its transport.
- `modules/monitor`: window observation and simple node/status UI.
- `modules/decision`: optional Laya lifecycle and recommendation.
- `modules/github`: GitHub and runner operating contract.
- `modules/mcp`: existing ChatGPT App/tunnel ingress retargeted to BCT.
- `modules/status-ui`: read-only Core status page.
- `D:\ChromeExtensions`: installed Chrome payloads only.
- `D:\PROJECTS`, `D:\TOOLS`, `D:\MODELS`, `D:\Archive`: user projects, shared tools/assets,
  model assets and recoverable history.

## Acceptance order

1. Source layout and tests.
2. GitHub integration and exact official-main sync.
3. BCT runtime release and status UI.
4. Existing ChatGPT App identity retargeted to BCT MCP without a duplicate plugin and renamed to
   `BCT Control`; the same App ID and connection are preserved.
5. RCC installed-path migration with extension identity/state evidence. **Complete.**
6. Monitor ACT/AI_TOOLS dependency retirement and focused window/status acceptance. **Complete.**
7. BDC parity for retained desktop primitives; retire the isolated ADC runtime. **Runtime retirement complete.**
8. Reduce runner pool; replace/retire ACT scheduled tasks. **Active pool and path migration complete.**
9. Archive profiles and legacy tools only after all references and active processes are absent.
10. Cold-start acceptance, then archive and delete ACT.

## 2026-10-13 progress

- GitHub main is the sole official source; local source and Core runtime were verified at one exact
  release before this slice.
- `bct_runtime_v1` now excludes DesktopWindow Monitor, RCC and BDC module payloads. Core keeps only
  the runtime implementation and its read-only status UI; module source remains maintained in Git.
- Legacy `D:\AI_TOOLS` and `D:\ChromeExtensions` staging/verification copies were moved, unchanged,
  into SHA-manifested archives. Active installed extensions, active tools and project candidates were
  retained.
- Old ACT and ADC scheduled starts are disabled; retained ACT-path processes and runners remain
  explicit retirement gates rather than hidden dependencies.
- GitHub PR #33 merged as `558fb2800a2f940aa3de01aa510b267971d91e4f`; local source and live Core
  release match that SHA. The live release contains `modules/status-ui` but no Monitor/RCC/BDC
  payload directories. RCC stayed OPEN with two existing tabs and Laya stayed RUNNING.
- The existing ChatGPT App is `BCT Control` 1.0.0 with the same App ID and connection. Its active
  tunnel is `BCT Control Private`, targets `http://127.0.0.1:18790/mcp`, and an authenticated live
  catalogue check returned server `BCT` with exactly 21 expected tools.
- RCC installed-path and Native Host cutover is complete. Chrome loads `BCT RCC 1.0.0` from
  `D:\ChromeExtensions\RCC\extension` with fixed identity
  `ocbidbaplechjjdacmokhnfbdmgjkphf`. The Native Host accepts only that origin, the old RCC is
  disabled, exact duplicate deployment is fenced, and both pre-existing tabs remained open through
  the restart. The retired ACT relay tree is preserved under
  `D:\Archive\ACT-Relay-Legacy-20261013`.
- The unused ACT ADC MCP/controller, the old ACT-path Laya process, the legacy ACT MCP supervisor on
  port 18769, and the isolated ADC agent on port 18766 were retired with exact PID/creation-time/path
  fences and durable receipts. BCT MCP, BCT Laya, RCC and Monitor Native Host remained healthy.
- Twenty-seven offline `AI-CODE-TEAM` runner registrations were removed from GitHub after local
  service evidence was recorded. The active pool was reduced to `ACT-GLOBAL-01`, `ACT-WORKER-01`
  and `SI-2`; four excess services were stopped and disabled with an idempotent receipt. The separate
  `ACT-BOOTSTRAP-01` scheduled runner remains an active recovery dependency.
- Five disabled ACT/ADC scheduled tasks were exported with SHA-256 manifests and removed. The active
  `ACT-BOOTSTRAP-01` runner task remains because it is a current recovery/CI dependency.
- BCT RCC 1.0.0, BCT ChatGPT New Tab 1.0.0 and BCT Auto Proxy 1.0.0 are the enabled installed
  browser modules. Their old extension identities are disabled. NewTab redirect, exact-once RCC tab
  creation/duplicate fencing and the Proxy BCT backend were live accepted. Old ACT relay, new-tab and
  proxy backend payloads are in SHA-manifested archives.
- Before the Monitor 2.0 worktree change, DesktopWindow Monitor main source and installed payload
  matched exactly (excluding policy documentation). The installed Monitor remains the baseline
  compatibility module until the tested 2.0 source is integrated and deployed. The independent BCT
  Monitor is already the default Core status view for BCT, Laya, RCC windows/tabs, work and operation
  state.
- All four active runners now execute from `D:\BCT\runtime\runners\github`: three under
  `AI-CODE-TEAM` and the recovery runner under `BOOTSTRAP`. Their GitHub runner IDs, names and
  labels were preserved and all four were verified `online / busy=false`. Exact migration receipts
  are `BCT-MOVE-RUNNER-SI2-20261013-01`, `BCT-MOVE-RUNNER-BOOTSTRAP-20261013-01` and
  `BCT-MOVE-SERVICE-RUNNERS-20261013-01` under `D:\BCT\data\migrations`.
- Monitor 2.0 source now treats Native HWND/window capture as authoritative, hides the legacy
  organization authority, and projects only the exact RCC-observed Chrome window/tab IDs and
  OPEN/active/generating state in its BCT-native main list. Its `N<n>` labels are display order,
  not role, permission, ownership or HWND identity. It disables retired ACT startup/focus calls,
  exposes BCT and Laya status, and labels extension reload as installed-payload reload. Focused thumbnail/capture/node-write
  regressions and BCT shell checks pass. PR #43 merged as
  `f00510b9c6411b4d6ee8dd5636594f4957f08cc6`; PR and main CI passed. Exact source/live SHA fencing,
  verified backups, atomic replacement and duplicate fencing were recorded by deployment operations
  `BCT-MONITOR-V2-LIVE-20261013-01` and `BCT-MONITOR-V2-INDEX-20261013-02`. Chrome reloaded the
  same extension ID `kaigandfpieiogfbfaemoimenmipedck`; fresh Native Host/Control Host connections,
  BCT/Laya health and the protected RCC tab were verified after reload.

## Remaining ACT deletion gates

- SHA-manifest and archive the old runner directory backups, then remove only the disabled legacy
  runner service registrations whose processes and GitHub registrations are absent. The active
  runners must remain on their current BCT paths.
- Remove the dormant ACT direct-bridge compatibility code from the RCC Native Host only with a
  focused rebuild/reload acceptance. Current BCT RCC named-pipe control does not depend on it.
- The unused remote tunnel named `ACT Control Tunnel Runtime` is not connected to the installed
  BCT Control app. Delete it only in a separate exact remote-resource cleanup operation.

Every live cutover is reversible, exact-SHA fenced and single-writer. An installed component is not
retired merely because its source has moved.
