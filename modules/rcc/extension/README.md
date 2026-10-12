# AI Workspace Relay MVP

A local-only Chrome Manifest V3 extension that relays messages between registered ChatGPT tabs.

## Goals

- No Codex usage.
- No OpenAI API usage.
- No local HTTP server.
- No Tampermonkey/userscript dependency.
- Works across separate Chrome windows, tab groups, and Windows virtual desktops in the same Chrome profile.
- GitHub remains durable state/evidence; this extension is only the live chat transport.

## Safety defaults

- Host permission is limited to `chatgpt.com` and legacy `chat.openai.com`.
- Only manually registered tabs receive relay commands.
- `CONTROL` cannot be used as a worker target.
- Automatic relay starts DISARMED.
- Arming is bounded to 6 commands by the popup (hard cap 12).
- CONTROL directives require a per-install random token.
- Worker reports have relay markers escaped before returning to CONTROL.
## First run

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose **Load unpacked** and select `D:\ChromeExtensions\RCC\extension`.
4. Refresh the ChatGPT tabs that will participate.
5. Open the extension popup and assign one tab `CONTROL`, others `WS2`, `WS3`, etc.
6. First run a manual relay with automatic relay still DISARMED.
7. After manual round-trip succeeds, click **CONTROL 프로토콜 넣기**.
8. Only then arm up to 6 automatic relay turns.

## Validation already run

- `node --check` on all JavaScript files: PASS.
- `manifest.json` JSON parse: PASS.
- `test_relay_core.js`: PASS.
- No live ChatGPT message was sent during build-time validation.

## Update resilience

ChatGPT DOM changes can still break any browser-UI automation. This MVP reduces the blast radius by using several semantic/fallback selectors and by failing closed when the editor cannot be found or the target is already generating. The relay core, registry, safety token, and Chrome tab messaging do not depend on ChatGPT DOM structure; only `content.js` input/reply adapters do.
## Prior art checked

The design was compared against `OLmatter/chatgpt-bridge` (local HTTP + userscript bridge) and `bsamek/blaster` (Manifest V3 background/tab-manager/content-script orchestration). We intentionally kept the useful browser-extension pattern while removing the local server and userscript layers for this use case.

No third-party source code is copied into this MVP; the implementation is purpose-built around the user's registered ChatGPT workspace tabs.
