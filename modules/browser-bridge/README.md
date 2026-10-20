# BCT Browser Bridge

Independent Chrome MV3 extension and Native Messaging Host. This is NOT RCC.
No RCC extension ID, origin, Host registration, executable, token or Chrome
profile is reused. BCT Core remains the only Work/Policy/receipt authority.

## Source-only Local Bridge parity candidate

The legacy Local Bridge used assistant text markers in a rendered ChatGPT
conversation, a Chrome extension, Native Host and local read result return.
The new independent extension now contains a parallel opt-in flow:

1. The user explicitly enables the current exact ChatGPT tab in the popup.
   Consent is stored in Chrome session storage for that one conversation+tab.
2. A content script on https://chatgpt.com/c/* observes only a completed
   assistant message with the canonical two-field marker below.
3. The background verifies exact origin, main frame, tab/conversation identity,
   session consent, and a lowercase 32-hex operation ID.
4. The request is read-only through the independent Native Messaging Host.
   It still targets only the isolated test MCP endpoint, not BCT LIVE.
5. The same exact ChatGPT conversation receives a bounded result message,
   subject to editor-empty, generation-stopped and stable-conversation checks.

Canonical marker (operation must be read, then path, with no extra keys):

    [[BCT_LOCAL_READ_REQUEST]]
    {"operation":"read","path":"D:\\BCT\\source\\README.md"}
    [[/BCT_LOCAL_READ_REQUEST]]

The extension generates a fresh operation ID and records a fingerprint before
dispatch. An ambiguous Host/Core result is not retried. A pending result is
removed from the queue before possibly effectful ChatGPT UI submission, so an
uncertain result send is also not repeated. Model-produced text and returned
file content remain untrusted data.

No WRITE, EXEC, shell, arbitrary page-command channel, automatic tab creation,
credential storage inside Chrome, model-provided caller identity, RCC wiring
or independent receipt authority is introduced.

## Fixed product identities

- Extension ID: acdgnmbgpkfjkckccbhmccojgigbfcge
- Native Host: com.bct.browser_bridge.prototype
- Native Host origin: chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/

The committed manifest public key pins that extension ID.

## Acceptance state: SOURCE_ONLY / NOT LIVE

The source and Node/host fixture tests are separate evidence from a real
Chrome E2E. The installed Chrome extensions, RCC, Native Host registrations,
Core LIVE, operating tokens and existing conversation tabs are unchanged.
The new content script and automatic editor-submit path have NOT been installed
or used in a real ChatGPT tab, so DOM drift, ACK and result delivery remain
unproven. The production Bridge peer binding/listener, credential lifecycle
and general Manager/Worker delivery remain blocked on the separate product gate.

The existing Python Host accepts ONLY fixture read and receipt lookup through
a non-production loopback MCP URL. Using local MCP does not require an OpenAI
hosted MCP tunnel, but the Bridge is NOT yet a live BCT connector.

## Source checks

From repository root:

- python -m unittest discover -s modules/browser-bridge/tests -v
- node modules/browser-bridge/tests/check_chat_parity.cjs
- node --check modules/browser-bridge/extension/chat_protocol.js
- node --check modules/browser-bridge/extension/chat_content.js
- node --check modules/browser-bridge/extension/background.js
- python -m compileall -q modules/browser-bridge
- git diff --check

Real Chrome acceptance, test-only Native Host registration and cleanup
still require the separate gate in docs/CHROME_E2E.md.
