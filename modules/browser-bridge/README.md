# BCT Browser Bridge

`BCT Browser Bridge` is an independent, manual, read-only Chrome extension and Native Messaging host.  It is not RCC and it does not share an extension ID, host name, executable, registration, token, profile, or `allowed_origins` entry with RCC.

The extension can only request BCT's existing `read` capability and receipt lookup.  BCT Core remains the owner of authorization, work scope, execution, and receipts.  The bridge has no content scripts, host permissions, page-command channel, custom executor, database, or automatic model invocation.

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
- `native/peer_frame.py`: a disconnected PR3-e peer-frame encoder; it does not
  load a credential, dispatch a request, or change the existing read-only Host.
- `native/host-manifest.template.json`: deliberately non-installable template.
- `tests/`: deterministic framing and fail-closed host tests.
- `docs/CHROME_E2E.md`: gated real-browser procedure and rollback.

No compiled executable, native-host registration, browser profile, token, test runtime, or private key is committed.

## Source checks

From repository root:

```powershell
python -m unittest discover -s modules/browser-bridge/tests -v
python -m compileall -q modules/browser-bridge
git diff --check
```

Real Chrome E2E is intentionally not part of CI or these checks.  It needs the explicit approval listed in `docs/CHROME_E2E.md`.
