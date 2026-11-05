# Browser Bridge Chrome E2E gate

Browser Bridge Chrome acceptance has two separate stages. Neither stage may
reuse RCC identity or erase an existing Native Host registration.

## Stage 1: disposable candidate acceptance

1. Use a new Bridge-owned Chrome profile and load the exact unpacked candidate.
2. Build/stage the exact candidate launcher in a new Bridge-owned directory. Write the strict `bridge-runtime.json` beside the `launcher` directory with restrictive ACLs; do not store the token value in it. This allows Chrome to launch the verified host without a browser restart for inherited environment changes.
3. Register only `com.bct.browser_bridge.prototype` under HKCU with the pinned
   origin `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/`.
4. Start an isolated BCT Core on a random loopback port and create a temporary
   Bridge token and fixture Work.
5. In one ordinary `chatgpt.com/c/<uuid>` conversation, enable Bridge control.
6. Confirm the bootstrap causes an exact `bct_capabilities` tool request, then
   prove tool list, status, Work creation, read, write and bounded execute.
7. Prove malformed tool, wrong origin, missing token and outside-Work effects
   are denied. An interrupted effect is UNKNOWN and is not resent.
8. Close only the owned Chrome/Core and remove only the exact profile, registry,
   manifest, token, runtime and staging artifacts created by the test.

## Stage 2: operating activation

Operating activation is allowed only after exact candidate CI and Stage 1.
Trusted staging must:

- preserve the pinned extension and Host identities;
- install a Bridge-owned launcher/runtime with recorded SHA-256 values;
- provision the current local BCT MCP bearer to the Native Host through a restrictive host-only path (the current Core does not yet issue a separate Bridge principal);
- set the exact loopback MCP URL and `BCT_BRIDGE_ALLOW_LIVE_CORE=1`;
- record the previous registration state and a reversible rollback plan;
- reload only the Browser Bridge extension once;
- verify `bct_capabilities`, `bct_status`, one bounded read and one separately
  approved harmless control effect before broader use.

Source tests, candidate CI, disposable Chrome proof and operating LIVE proof are
reported separately. A successful isolated test is not an installed result.

Chrome references: [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [Load unpacked](https://developer.chrome.com/docs/extensions/get-started/tutorial/scripts-activetab), and [extension E2E testing](https://developer.chrome.com/docs/extensions/how-to/test/end-to-end-testing).

## Rollback

Disable the Bridge manifest/host activation first, close only the owned Host, verify the
current registry value still matches the activation receipt, restore or remove
that exact value, and then remove owned staging files. Do not touch RCC, other
Chrome profiles, operating Core data, UNKNOWN receipts or Claims. Ownership
mismatch is `CLEANUP_BLOCKED`, not permission to delete.
