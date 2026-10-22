# BCT CDP Chat Send Once — isolated implementation

**Work:** BCT-CDP-CHAT-SEND-ONCE-IMPLEMENT-20261022-01  
**Base:** local main 5c58767a9e5f4e930eb9b1cedddb8714348bfe11  
**Transport:** official Chrome DevTools MCP (NOT RCC, NOT Browser Bridge)

## Supported operation

`bct_cdp_send` with one exact BCT work and operation ID; the work must explicitly authorize `cdp_send`.

Arguments:
- `operation: "send_once"`
- `page_id`: exact positive numeric page ID returned by CDP `list_pages`
- `conversation_uuid`: exact lowercase UUID from an existing `https://chatgpt.com/c/<uuid>` conversation
- `text`: 1–5,000 characters (user message)
- `expected_sha256`: SHA-256 of the exact UTF-8 text
- `expected_connection_generation`: generation from the *same live BCT CDP manager* `cdp_inspect` result

Each operation has an immutable durable BCT receipt. No browser request is sent before BCT policy checks. The browser script validates origin, UUID, blank editor, existing user turns, a disabled/in-progress send control, and a per-tab persistent submit intent. It performs exactly one click and waits for an exact new user turn. `CONFIRMED` requires a visible user turn. If the result after click is uncertain, BCT retains an `UNKNOWN` receipt and Claim; **never retry using a new operation ID**. Only read-only reconciliation may determine the fate of that submission.

A changed MCP connection generation fails before the browser action. The manager only allows `list_pages` and this exact fixed `evaluate_script` function, not arbitrary code evaluation.

## Activation and safety

`[cdp].enabled = false` and `argv = []` by default. Do not enable for LIVE during implementation. A reviewed local Chrome DevTools MCP command using official `--autoConnect` and user Chrome consent is required. Consent dialogs must never be auto-clicked. No Chrome process launches, tab creation, message send or extension reload were performed during these isolated tests.

**Not implemented here:** response completion/return, unsupported changed ChatGPT DOM layouts, and real live Chrome physical E2E. Never use RCC or Browser Bridge as a fallback sender without a new explicit authorization.

**Tests:** `python -m unittest discover -s tests -p "test_cdp*.py" -v`; MCP catalogue test and deployment closure test. Node-backed DOM fixture runs without a browser account.
