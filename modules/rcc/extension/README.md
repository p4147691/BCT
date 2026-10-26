# BCT RCC extension

RCC is a Chrome Manifest V3 extension that keeps fixed ChatGPT conversations observable and carries
the Simple Relay V0 Manager→Worker handoff and Worker→Manager verbatim return. GitHub/BCT is the
durable authority; the extension is a browser transport and observation boundary.

## Active structure

- `background_loader.js` loads Core, Platform, Relay, Domain, the atomic chat adapters, and the three-line background entrypoint.
- `content/` owns conversation DOM detection, exact submit/read, the accepted message router, and bounded activity observation.
- `platform/` is the only active background boundary for `chrome.storage`, `chrome.tabs`,
  `chrome.scripting`, Native Messaging, observation events, and extension lifecycle.
- `domain/` has no direct `chrome.*` calls.
- `browser/` contains tab/window capability contracts and adapters.  Creating a blank ChatGPT tab or
  window and moving an exact tab are active, independently receipted primitives; close/reload/read
  adapters remain optional source and are not product commands.
- The popup is read-only and sends only `relay:getState`.

The exact V2 Release Candidate file list, loader graph, message matrix, storage/wire contract, and
rollback baseline are in `../release/rcc_v2_rc.json`.

## Chrome API boundary

Content Scripts cannot call the Tabs or Native Messaging APIs. They send bounded messages to the
extension Service Worker, which validates the sender and delegates effects to Platform adapters.
Runtime messages from ChatGPT must come from the same extension, the top frame, and an allowed
ChatGPT origin. Extension-page state reads must come from the same extension origin.

`chrome.storage.local` keeps compatible durable binding/receipt/state keys. The endpoint session ID
uses `chrome.storage.session`, which is intentionally cleared when the extension is disabled,
reloaded, updated, or the browser restarts. Per-page execution and telemetry use page
`sessionStorage` and are not extension-durable state.

Official references used by V2-4:

- https://developer.chrome.com/docs/extensions/reference/api/runtime
- https://developer.chrome.com/docs/extensions/reference/api/tabs
- https://developer.chrome.com/docs/extensions/reference/api/storage
- https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
- https://developer.chrome.com/docs/extensions/develop/concepts/messaging

## Safety defaults

- Host access is limited to `chatgpt.com` and legacy `chat.openai.com`.
- Active permissions are `scripting`, `nativeMessaging`, `storage`, and `tabs`; unused `webRequest`
  permission was removed from the V2 candidate.
- Unknown or legacy mutation messages fail closed. Confirmed or UNKNOWN browser effects are never
  retried automatically.
- Original relay text, conversation UUID, storage keys, Native Host name, extension ID, and wire
  message names remain compatible.
- Loading or reloading the unpacked extension is a LIVE operation. Source validation never reloads Chrome.

## Source-only verification

Run from `D:\BCT\source`:

    python modules/rcc/release/verify_release_candidate.py
    python -m unittest discover -s tests -p test_rcc_release_candidate.py -v
    python -m unittest discover -s tests -p test_rcc_source_baseline.py -v

To verify the already assembled non-LIVE candidate and current rollback baseline without changing
either, add `--candidate-root <rehearsal path>` and `--live-root D:\ChromeExtensions\RCC\extension`.
