# BCT desktop clipboard — 2026-10-19

Status: `active`

## Goal

Expose Unicode text clipboard read/write through authenticated BCT MCP and the
current-login-session VTL Agent. The feature must behave identically whether the
Windows **Beta: Use Unicode UTF-8** system-locale option is enabled or disabled.

## Contract

- Both `get` and `set` require the caller's exact active `session` Lease and a
  clear emergency-stop latch.
- Text crosses the named pipe as explicit UTF-8 JSON and Windows Clipboard is
  accessed on a bounded STA thread using `UnicodeText`; the system ANSI code page
  is never consulted.
- A set is successful only after rereading and matching the exact Unicode text.
  An unprovable postcondition is `UNKNOWN` and is never retried automatically.
- Durable BCT evidence contains only operation, character/UTF-8 byte counts,
  SHA-256, Lease ID and timestamp. Clipboard text exists only in the immediate
  successful `get` response; duplicate receipts cannot reproduce it.
- Empty set clears clipboard text. Bounded request and response sizes fail
  without attempting a mutation.

## Verification and rollout

1. Pass VTL compile/static/encoding tests and BCT focused desktop/MCP tests.
2. Run each repository's local regression, open PRs, require CI and merge exact
   heads.
3. Install the exact merged VTL release and roll the idle Agent through its
   Supervisor; deploy exact merged BCT main.
4. Under an exact session Lease, save the current clipboard in memory, perform a
   Korean/ASCII Unicode round trip, restore the original value in `finally`, and
   prove final null Lease / clear emergency stop.
5. Move this record to completed and update both handoffs only after LIVE
   acceptance.
