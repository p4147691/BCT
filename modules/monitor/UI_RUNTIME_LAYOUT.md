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


## V4: Capture failure presentation settings
Presentation-only optional JSON object named captureFallback. Backward compatible:
old bwm-ui-layout.json without the object is automatically normalized to

    captureFallback: {
      mode: last_good,
      staleAfterSeconds: 20,
      maxAgeSeconds: 180
    }

Accepted modes:
- last_good: keep the previous successfully captured HWND image while fresh
  enough, mark it "이전 화면" immediately when a later WGC read cannot refresh
  it; mark "오래된 화면" after staleAfterSeconds, and fall back to a small
  transparent SVG indicator after maxAgeSeconds.
- compact: always use the small, transparent placeholder when new pixels
  cannot be obtained. The underlying HWND retains its physical rectangle
  and mouse/drag targeting, even though placeholder pixels no longer cover it.
- legacy: show the previous full-size fallback card, for display rollback.

Accept integer seconds only: staleAfterSeconds 5..120, maxAgeSeconds
30..600, and staleAfterSeconds < maxAgeSeconds. This sets display policy
only. WGC one-shot, capture scheduler/worker, HWND identity, Native statuses,
window geometry, physical z order, event transport, RCC and completion semantics
remain unchanged. No automatic desktop switching or unbounded retry.
The timestamp is updated ONLY on an actual fresh capture, never when
reusing an older image. The label/expiry is re-evaluated on the next
existing frame reconciliation, not from a new high-frequency polling loop.
Cached WGC frames retain their original capture timestamp and cannot restart the
retention window. Config mode changes fire a single bounded existing thumbnail
refresh request after exact configuration validation; no new capture timer,
desktop activation or RCC transition is introduced.

Per-window DOM metadata captureFailureReason is observational and distinguishes
CLOAKED / CAPTURE_DISABLED / WGC_UNAVAILABLE; it does not claim to prove
the specific failure cause in an earlier screenshot.

The runtime config is read from the existing Core /monitor/ui-layout endpoint.
Post-install changing this object needs only an exact-hash BCT write to the
existing D:/BCT/data/bwm-ui-layout.json file. Neither main/CI/Core deploy nor
extension reload is needed for *future settings* changes. New capture engines,
capture authorization semantics and endpoint contracts remain code changes.
