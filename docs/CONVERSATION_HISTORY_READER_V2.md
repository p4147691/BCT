# Conversation History Reader V2 — isolated adapter checkpoint

This is **not** an accepted ChatGPT history loader. The new module is a bounded, read-only adapter for a separately authorized test document. It is **not** loaded by the live RCC manifest, sends no messages, and changes no browser profile.

## Recommended read workflow (no custom browser first)

1. Query native ChatGPT cross-conversation context first for previous decisions and work status. This can recover summaries but not guarantee a complete verbatim transcript.
2. Use connected read-only Browser tabs for the portion already rendered, with conversation URL and title identity.
3. When old turns are missing, use official ChatGPT conversation search (Ctrl+K) and open the exact URL in an authorized browser control context; the Chat-mode Browser connector cannot itself scroll, navigate or create tabs.
4. The isolated V2 DOM reader may collect *observed* turns only. Bind its optional `expectedConversationUrl` to the selected conversation; stop on identity mismatch or navigation. Neither scroll exhaustion nor an empty page proves complete server history.
5. Cache only verified loaded evidence. Keep unresolved original sections `PARTIAL` and never resend unknown RCC actions just to retrieve history.

## Coverage contract

- Record actual observed turns keyed by `data-message-id` (or conversation-turn test identifier).
- Deduplicate repeated observations; scrolling can virtualize away previously observed messages.
- Stop after a bounded number of scroll samples; no-progress is a diagnostic, never proof of completeness.
- Always return `PARTIAL` with `full_history_verified: false`.
- Reject empty views with `NO_IDENTIFIED_TURNS`.
- The collector samples **after every scroll including the final scroll**, and retains observed turns that disappear from a virtualized DOM.
- It records both duplicates *inside* one DOM snapshot (`duplicatesInSamples`) and the same IDs observed again after scrolling (`reobserved`); `duplicates` is their sum. A stable ID with changed text increments `conflictingTexts` but is not treated as a new message.
- Potentially unmarked turn candidates with `data-message-author-role` or a bare `data-testid='conversation-turn'` are counted as `unidentified`, excluding nested elements already represented by identified turns. This is **only a bounded candidate heuristic**, not exhaustive coverage of every site layout.
- `gaps_verifiable: false` is always returned: arbitrary/virtualized IDs cannot establish a contiguous complete transcript.
- Missing IDs, mixed virtualized DOM, and page navigation remain unresolved until real authenticated isolated ChatGPT E2E validates selectors and identity.
- No capture is silently persisted; an approved V1 cache call must separately save source text.

## CI coverage

`node modules/rcc/extension/test_conversation_history_reader_v2.js` covers two visible IDs, duplicates, changed virtualized observations, and missing identifiers. The fixture is not a physical ChatGPT browser E2E. A real separate-profile run remains a gate and must not disturb operational Chrome.

## Existing encoding evidence

A prior acceptance snapshot contains valid Hangul in `page_text`, while its `title` and `summary` fields already contain literal U+003F question marks. The downstream JSON reader preserved those bytes faithfully. This localizes irreversible loss to **at or before initial metadata capture**; it does not prove whether the upstream terminal command, argument encoding, or another source produced the question marks. Never reconstruct missing words by guessing.

For a future authorized capture, obtain title and summary as UTF-8 file content (not ad hoc shell arguments), verify expected code points **before** V1 capture, and keep the original snapshot immutable. This is a proposed improvement, not a live-installed change.

## Strict UTF-8 metadata transport (isolated V2 candidate)

The V1 cache serializer correctly preserves valid Hangul and returns ASCII-safe JSON on Windows. Existing corrupted `???` metadata is unrecoverable without the original title/summary. The exact upstream writer that introduced the loss is not identified.

To prevent shell code-page conversions from silently corrupting future title and summary, the isolated CLI now supports `capture --metadata-input <absolute UTF-8 JSON path>` instead of passing title and summary through command arguments. The JSON document is strictly UTF-8 (optional BOM), bounded, and must be:

```json
{"schema":"BCT_CONVERSATION_METADATA_V1","title":"영속 시스템 체크","summary":"이전 작업의 확인된 결정"}
```

`summary` can be null or omitted. Using `--title` with `--metadata-input`, or overriding that file's summary with `--summary`, is rejected. Unknown fields, invalid UTF-8, or a missing title are rejected. The existing `--title` form remains accepted for compatibility. The capture text itself continues to use the existing `--input` UTF-8 JSON/browser text or STDIN contract.

This reduces lossy transport risk but does not establish which original upstream boundary produced the earlier literal question marks. A successful UTF-8 capture proves text integrity only for that capture.

## Acceptance gates

Actual authenticated isolated Chrome session; explicit target conversation; recorded scroll and observed turn IDs; boundary evidence for earliest loaded message and any gaps; cross-check with actual UI; no live tab changes; CI and later exact-SHA deployment checks. None of these physical gates may be declared PASS from this unit fixture.
