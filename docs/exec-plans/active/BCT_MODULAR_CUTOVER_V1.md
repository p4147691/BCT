# BCT Modular Cutover V1

Status: `SOURCE_RESTRUCTURE_IN_PROGRESS`

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
2. GitHub integration and canonical main sync.
3. BCT runtime release and status UI.
4. Existing ACT Control App identity retargeted to BCT MCP without a duplicate plugin. The App's
   external display name is a compatibility label until it is renamed in the owning App settings;
   the local target and recovery owner are BCT.
5. RCC installed-path migration with extension identity/state evidence.
6. Monitor ACT/AI_TOOLS dependency retirement and focused window/node/status acceptance.
7. BDC parity for the retained desktop primitives, then ADC retirement.
8. Reduce runner pool; replace/retire ACT scheduled tasks.
9. Archive profiles and legacy tools only after all references and active processes are absent.
10. Cold-start acceptance, then archive and delete ACT.

Every live cutover is reversible, exact-SHA fenced and single-writer. An installed component is not
retired merely because its source has moved.
