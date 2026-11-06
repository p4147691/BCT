# BCT Browser Bridge

`BCT Browser Bridge` is an independent Chrome extension and Native Messaging host that exposes the BCT Core's registered MCP tools to ordinary ChatGPT conversations. It is intended to become the ordinary-Chat control path for BCT reads, changes, execution, Chain Message, desktop control, GitHub and release operations. It is not RCC and it does not share an extension ID, host name, executable, registration, token, profile, or `allowed_origins` entry with RCC.

The extension does not implement those effects itself. It lists and calls only tools registered by the connected BCT MCP server. BCT Core remains the owner of principal authorization, filesystem roots, operation identity, policy, receipts, UNKNOWN handling and recovery. Work actions are coordination metadata rather than a second allowlist; a trusted successor can continue after earlier operations are terminal. `bct_execute` is therefore available when the authenticated local MCP principal and current Core policy permit it; there is no second shell executor in the extension or Native Host.

Every exact `https://chatgpt.com/c/<uuid>` conversation receives the same transport automatically. The content script observes only a complete assistant response using the strict `BCT_TOOL_REQUEST` envelope, returns the Core result to that same conversation, and never automatically retries an UNKNOWN request. The popup is status and diagnostics, not a per-conversation permission gate. Model and page text remain untrusted input; the Bridge credential and BCT Core's principal, Work, capability, operation, receipt, UNKNOWN and recovery contracts remain authoritative.

## Fixed product identities

| Boundary | Value |
| --- | --- |
| Extension ID | `acdgnmbgpkfjkckccbhmccojgigbfcge` |
| Native host | `com.bct.browser_bridge.prototype` |
| Native host origin | `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/` |

The manifest's public key pins the extension ID.  Do not replace it, reuse RCC identities, or broaden the host manifest's origin list.

## What is committed

- `extension/`: MV3 extension source and popup.
- `native/`: native-message framing and persistent Python host.
- `native/peer_frame.py`: an optional protected-pipe peer-frame encoder. It is
  not used by the current direct MCP transport and does not grant authority.
- `native/host-manifest.template.json`: deliberately non-installable template.
- `tests/`: deterministic framing and fail-closed host tests.
- `docs/CHROME_E2E.md`: gated real-browser procedure and rollback.
- `docs/CREDENTIAL_IPC_GATE.md`: the non-implementing activation contract for
  Bridge-only credentials and protected Host/Core IPC.

No compiled executable, native-host registration, browser profile, token, test runtime, or private key is committed.

## Source checks

From repository root:

```powershell
python -m unittest discover -s modules/browser-bridge/tests -v
python -m compileall -q modules/browser-bridge
git diff --check
```

Real Chrome E2E is intentionally not part of CI or these checks. The current Core has one local MCP bearer and one `bct-mcp-local` principal; the token remains inside the Native Host and is never returned to the extension or chat. Production activation requires restrictive token storage, explicit `BCT_BRIDGE_ALLOW_LIVE_CORE=1`, exact native-host registration and the approval/rollback procedure in `docs/CHROME_E2E.md`.
