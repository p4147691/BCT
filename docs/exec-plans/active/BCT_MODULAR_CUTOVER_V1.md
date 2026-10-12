# BCT Modular Cutover V1

Status: `CORE_RELEASE_BOUNDARY_LIVE_ACCEPTED`

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
5. RCC installed-path migration with extension identity/state evidence.
6. Monitor ACT/AI_TOOLS dependency retirement and focused window/node/status acceptance.
7. BDC parity for the retained desktop primitives, then ADC retirement.
8. Reduce runner pool; replace/retire ACT scheduled tasks.
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
- RCC installed-path migration is in progress with a committed fixed extension identity
  (`ocbidbaplechjjdacmokhnfbdmgjkphf`). The transition accepts the old path-derived origin only long
  enough to prove and rebind exact open registrations; pending sends are never copied or retried.

Every live cutover is reversible, exact-SHA fenced and single-writer. An installed component is not
retired merely because its source has moved.
