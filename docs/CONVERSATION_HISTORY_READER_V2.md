# Conversation History Reader V2 — isolated adapter checkpoint

This is **not** an accepted ChatGPT history loader. The new module is a bounded, read-only adapter for a separately authorized test document. It is **not** loaded by the live RCC manifest, sends no messages, and changes no browser profile.

## Coverage contract

- Record actual observed turns keyed by `data-message-id` (or conversation-turn test identifier).
- Deduplicate repeated observations; scrolling can virtualize away previously observed messages.
- Stop after a bounded number of scroll samples; no-progress is a diagnostic, never proof of completeness.
- Always return `PARTIAL` with `full_history_verified: false`.
- Reject empty views with `NO_IDENTIFIED_TURNS`.
- Missing IDs, mixed virtualized DOM, and page navigation remain unresolved until real authenticated isolated ChatGPT E2E validates selectors and identity.
- No capture is silently persisted; an approved V1 cache call must separately save source text.

## CI coverage

`node modules/rcc/extension/test_conversation_history_reader_v2.js` covers two visible IDs, duplicates, changed virtualized observations, and missing identifiers. The fixture is not a physical ChatGPT browser E2E. A real separate-profile run remains a gate and must not disturb operational Chrome.

## Existing encoding evidence

A prior acceptance snapshot contains valid Hangul in `page_text`, while its `title` and `summary` fields already contain literal U+003F question marks. The downstream JSON reader preserved those bytes faithfully. This localizes irreversible loss to **at or before initial metadata capture**; it does not prove whether the upstream terminal command, argument encoding, or another source produced the question marks. Never reconstruct missing words by guessing.

For a future authorized capture, obtain title and summary as UTF-8 file content (not ad hoc shell arguments), verify expected code points **before** V1 capture, and keep the original snapshot immutable. This is a proposed improvement, not a live-installed change.

## Acceptance gates

Actual authenticated isolated Chrome session; explicit target conversation; recorded scroll and observed turn IDs; boundary evidence for earliest loaded message and any gaps; cross-check with actual UI; no live tab changes; CI and later exact-SHA deployment checks. None of these physical gates may be declared PASS from this unit fixture.
