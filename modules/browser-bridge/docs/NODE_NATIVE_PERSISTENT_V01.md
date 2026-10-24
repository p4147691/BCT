# Browser Bridge: independent persistent Native Messaging mailbox V0.1

Status: **SOURCE + REAL WINDOWS NATIVE-HOST PROCESS E2E PASS**
Production Chrome installation and model-to-model delivery: **NOT ACCEPTED**

## Purpose

Reuse the original pinned **BCT Browser Bridge** extension ID
`acdgnmbgpkfjkckccbhmccojgigbfcge` and Host identity
`com.bct.browser_bridge.prototype`, without sharing the RCC extension,
RCC message channel, live BCT Core port 18790, BCT MCP token or a GitHub
operation. The original read-only BCT file tool/receipt route remains
separate. A second Native Messaging port carries only exact
`node_relay_*` mailbox envelopes. No new host registration or Chrome
permissions are applied by this change.

## Native mailbox lifecycle

Each message uses a 32-character request ID and exact 32-character
`delivery_id`, source/target node labels (e.g. N23 / N14),
source/target ChatGPT conversation UUIDs and SHA-256 of at most 2,000
characters / 8,192 UTF-8 bytes. Message plaintext is encrypted at rest
using current-Windows-user DPAPI and a delivery-specific context, stored
in an explicitly configured SQLite WAL database.

- `node_relay_enqueue` — create once as QUEUED, or replay matching
  stored receipt without enqueueing a second copy
- `node_relay_claim` — fetch the encrypted message for the exact target
  once and change state to CLAIMED; never redeliver a claimed item automatically
- `node_relay_ack` — persist the target's mailbox acknowledgement
- `node_relay_reply` — record exact ACK-bound, hash-checked reply (app
  data, not a cryptographically verified model completion)
- `node_relay_inspect` — exact sender-only receipt and optional completed
  reply read, preserving response SHA-256

On effect ambiguity, transport disconnection, or a process crash after
CLAIMED, stop. **Never automatically resend the original effect**.
Host and Chrome extension use different pending-request maps for existing
BCT-read commands and independent node mailbox commands.

## Actual physical tests

A Windows test created a disposable mailbox DB under a temporary
directory, launched the real Python `persistent_host.py` as an OS child
process with actual length-prefixed Chrome Native Messaging frames,
submitted a synthetic Korean N23-to-N14 message, terminated the child,
restarted a fresh child and recovered the request. It then claimed,
verified duplicate CLAIM denial, ACKed, recorded a synthetic response,
and returned it from a further fresh child. No Core URL/token was
provided and no RCC or operating Chrome tab was accessed. DPAPI ciphertext
was verified not to contain the synthetic request/response plaintext.

The pinned-ID extension's **separate** Native Messaging port was also
tested with deterministic Chrome API stubs: exact request framing,
Host response correlation, disconnect => UNKNOWN, no resend, and
receipt lookup after a fresh port connection. Existing Bridge regression
suites must remain green.

## Important limitations

- `ACKED` **only confirms Browser Bridge mailbox pickup**, not that
  the ChatGPT editor was clicked. `REPLIED` is source-provided data;
  it is **not** verified proof of a completed assistant response.
- Source/target UUIDs and node labels are currently envelope identities,
  **not** authorization or attestation of the real target Chrome tab.
- Production enablement defaults **off**. The Host requires explicit
  `BCT_BRIDGE_NODE_RELAY_ENABLED=1`, a Windows process, and an existing
  absolute `BCT_BRIDGE_NODE_MAILBOX_DB` path in a preexisting directory.
  The supplied code checks for symlinks but does **not yet independently
  attest that directory's Windows DACL**. Do not activate it for private
  conversation content until a separately reviewed ownership/DACL
  preflight and retention policy are implemented and accepted.
- No existing HKCU Native Host registration, manifest allowlist, Chrome
  extension, RCC instance, operating Core or ChatGPT conversation was
  modified in testing. This is not a live Chrome-to-ChatGPT relay E2E.
- Any future real model delivery requires a separately approved
  exact tab+UUID+request SHA+once-only submit/ACK/completion proof and
  compatible privacy controls. The V0.2 UI-send prototype remains
  independently disabled.

## Source verification

```powershell
python -m unittest discover -s modules/browser-bridge/tests -q
cd modules/browser-bridge
node tests/test_node_native_extension.js
```

Run the disposable Windows process test with
`python -m unittest discover -s modules/browser-bridge/tests -p test_node_relay_process_windows.py -v`
from the repository root. It runs without Chrome/registry/BCT Core/RCC.
