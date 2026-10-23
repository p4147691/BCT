# BWM runtime layout V2 - AI-driven, no visible editor

BWM reuses the five existing toolbar buttons and their handlers. The only
layout authority is D:\BCT\data\bwm-ui-layout.json.
The file is presentation-only and can be changed through BCT work-scoped
exact-hash file writes, not by editing Chrome profile state.

Core exposes GET /monitor/ui-layout, read-only, on existing localhost port.
BWM checks on startup and at 3-second intervals while its screen is visible.
No UI editor is shown, and the layout file does not trigger source/CI/deploy.
Default: five buttons beside the BWM version, inline, compact, gap 2.
No combo box or dropdown. In narrow monitors the button strip scrolls within
the header, never overlaps the worker/node panel.

The file uses an allowlisted JSON schema: version=1, toolbar placement
inline/below, full order of the five registered button IDs, hidden subset,
density compact/normal, gap integer 0-16. Arbitrary CSS, scripts, URL commands
and unknown identities are rejected. Existing node-column preferences remain
untouched.

Unicode support accepts strict UTF-8 with or without BOM and BOM-marked
UTF-16 LE/BE. CRLF and LF differences do not affect JSON. It does not guess
legacy code pages and never silently corrupts text. Receipt tokens should
likewise be compared as decoded Unicode (PowerShell Get-Content handles BOM).

Deployment: syntax, targeted Node + Python checks, Monitor structure,
existing regressions, CI, local-main exact merge, GitHub publication,
backed-up exact-file monitor staged deployment and versioned loaded runtime
observation. Core release changes must pass effectful service delivery gates.
Future layout-only changes use BCT file write + readback and no code changes.

## V3: Additional presentation-only settings (allowlisted)

Existing JSON files without the optional presentation object remain valid and
retain original visual defaults. BCT /monitor/ui-layout normalizes the fields.

Optional presentation JSON mapping:
    nodeTitleFontPx: 12
    nodeCardMinHeightPx: 36
    nodeGapPx: 6
    panelPaddingPx: 10
    thumbnailStatusIconPx: 20

Accepted integer ranges: title 10..16, card min-height 30..56, list gap
2..14, panel horizontal padding 5..16, thumbnail (non-warning) status SVG
16..32. CSS custom properties are applied only under the BWM Monitor root.

Node columns (existing 3), browser tab identity, Native HWND, window control,
capture pixels, work/role/attention status, warnings, ACK and task completion
must not be affected. Unsupported values fail closed. Do not expose script,
CSS, code, URL, state-machine or authority mutations as UI configuration.

Once initially deployed, normal BCT exact-hash writes to the existing
D:\BCT\data\bwm-ui-layout.json file followed by Core API readback change
presentation without main/CI/redeploy. Isolated Chrome computed-style E2E
checks presentation rendering where live extension page inspection is blocked.
