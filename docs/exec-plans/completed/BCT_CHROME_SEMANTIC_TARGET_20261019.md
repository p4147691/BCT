# BCT Chrome semantic target — 2026-10-19

Status: COMPLETE / LIVE ACCEPTED.

## Contract

`desktop_application_target` now accepts optional Chrome `profile_query`,
`tab_title_query` and `tab_scope` (`active` by default or `any`). BCT validates
the full Agent response, filters only current-Session/current-desktop Chrome
windows and binds only one exact HWND/PID/process-birth fingerprint. It returns
no URL and performs no activation, focus, input, launch or close.

Chrome bind fails closed on unavailable/incomplete UI Automation, zero or
multiple candidates, or any truncated window/tab inventory. Explorer rejects
Chrome selectors and Chrome rejects `folder_path`.

## Evidence

- Focused desktop tests passed (32 tests); compileall passed.
- VTL PR #31 merged the first adapter. LIVE rollout exposed a codepage-dependent
  redirected-output decoder, which failed closed without touching Chrome.
- VTL PR #32 fixed the boundary with strict UTF-8 decoding and strong bounded
  response validation. Exact VTL main/runtime is
  `20249554282c1936e9e4430c7a26916024ed3145`; Agent is 1.8.1.
- BCT PR #216 passed scope, preflight, all four core shards and Browser Bridge,
  then merged as `2801d1a138eae014be70fca9975f38b98ed7e7dc`.
- Merged-main CI run `39195053556` passed. Durable deployment applied that exact
  SHA as generation 132 and health reported READY with 34 MCP tools.
- Authenticated MCP LIVE inspected four Chrome windows and selected one exact
  window by Unicode profile plus active-tab title. It acquired and released the
  Window Lease without activation/input. Profile and tab text were retained in
  acceptance output only as SHA-256 values.
- Every pre-existing Chrome process and window fingerprint remained present.
  Final control state had no Lease and emergency stop was false.
