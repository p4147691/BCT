# BCT Modular Cutover V1

Status: `RCC_CUTOVER_ACCEPTED_ACT_RUNTIME_REDUCTION_IN_PROGRESS`

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
6. Monitor ACT/AI_TOOLS dependency retirement and focused window/node/status acceptance.
7. BDC parity for the retained desktop primitives, then ADC retirement.
8. Reduce runner pool; replace/retire ACT scheduled tasks. **Partially complete.**
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
- The existing ChatGPT App was renamed from `ACT Control` to `BCT Control`, its description now
  names the BCT contracts, and its tool catalogue was refreshed from the BCT MCP endpoint.
- RCC installed-path and Native Host cutover is complete. Chrome loads `BCT RCC 1.0.0` from
  `D:\ChromeExtensions\RCC\extension` with fixed identity
  `ocbidbaplechjjdacmokhnfbdmgjkphf`. The Native Host accepts only that origin, the old RCC is
  disabled, exact duplicate deployment is fenced, and both pre-existing tabs remained open through
  the restart. The retired ACT relay tree is preserved under
  `D:\Archive\ACT-Relay-Legacy-20261013`.
- The unused ACT ADC MCP/controller and the old ACT-path Laya process were retired with exact
  PID/creation-time/path fences and durable receipts. BCT MCP, BCT Laya and RCC remained healthy.
- Twenty-seven offline `AI-CODE-TEAM` runner registrations were removed from GitHub after local
  service evidence was recorded. Seven online registrations remain. Reducing the six running ACT
  runner services to the three required label pools needs one Windows administrator service change;
  no process was force-killed.
- Five disabled ACT/ADC scheduled tasks were exported with SHA-256 manifests and removed. The active
  `ACT-BOOTSTRAP-01` runner task remains because it is a current recovery/CI dependency.
- DesktopWindow Monitor source and installed payload match exactly (excluding policy documentation).
  The installed Monitor remains an external compatibility module because its organization UI still
  calls the old Agent Orchestrator API. The independent BCT Monitor is already the default Core
  status view for BCT, Laya, RCC windows/tabs, work and operation state.

## Remaining ACT deletion gates

- Windows administrator action: stop/disable the excess `ACT-GLOBAL-02..04` and
  `ACT-WORKER-02` services, keeping one global runner, one worker runner and SI-2.
- Controlled Chrome identity migration for the still-active Chrome Auto Proxy. Its unpacked
  extension ID is path-derived, so moving it directly would silently create a different extension.
- Decide the small retained window/status surface of DesktopWindow Monitor, migrate that surface to
  BCT, then disable the old ACT-coupled organization UI.
- Retire the isolated ADC agent on port 18766 and connector on 18769 only after their administrator
  process identity can be read and fenced. Their public MCP/controller front doors are already gone,
  but lack of exact executable evidence keeps this final step fail-closed.

Every live cutover is reversible, exact-SHA fenced and single-writer. An installed component is not
retired merely because its source has moved.
