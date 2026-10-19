# BCT desktop clipboard — 2026-10-19

Status: `complete` — VTL Agent 2.2 / BCT MCP LIVE accepted.

## Delivered contract

- Authenticated `desktop_clipboard` `get` and `set` require the caller's exact
  active `session` Lease and a clear emergency-stop latch.
- Text crosses the named pipe as explicit UTF-8 JSON and Windows Clipboard is
  accessed on a bounded STA thread using `UnicodeText`; the Windows system
  ANSI/UTF-8 locale setting is not consulted.
- Set is APPLIED only after rereading and matching exact Unicode text. An
  unprovable postcondition is UNKNOWN and is never retried automatically.
- Durable BCT evidence contains only operation, Unicode scalar/UTF-8 byte
  counts, SHA-256, Lease ID and timestamp. Clipboard text exists only in the
  first successful get response; a duplicate receipt cannot reproduce it.
- Empty set clears clipboard text. Reads and writes are bounded by explicit
  character and 64-KiB transport-envelope limits before mutation.

## Verification and rollout

- VTL PR #47 passed required CI and merged as
  `0a151a36e1d772ce0215eb8df732603209b54ec0`. Its immutable release is current
  and the persistent Supervisor recovered Agent 2.2.0 from that release.
- VTL compile/static, all-PowerShell parse, simulated CP949/UTF-8 and explicit
  encoding checks passed. The broad GUI smoke reached an unrelated transient
  `WINDOW_ACTIVATION_FAILED` before the clipboard stage; it was not repeatedly
  rerun against the user's foreground. Dedicated current-session Agent
  acceptance then passed Korean plus supplementary-plane Unicode set/get/hash
  and restored the original clipboard in `finally`.
- BCT PR #228 and default-policy correction PR #229 passed all required CI and
  merged. Local focused desktop/MCP tests passed 48/48 and the four-way full
  regression passed 609/609.
- Durable `bct_deploy` applied exact main
  `15cf1e75e62f3befc48b34b9c25a667b29d4c58e` as Generation 141. Health was
  READY with 39 MCP tools including `bct_desktop_clipboard`.
- Authenticated MCP LIVE acceptance wrote/read a 21-scalar, 36-byte Unicode
  marker, matched SHA-256, restored the clipboard value observed immediately
  before the test, and released the Lease. Final control state had null Lease
  and inactive emergency stop.
