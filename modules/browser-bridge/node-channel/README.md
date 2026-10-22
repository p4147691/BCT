# Browser Bridge — Independent Node Channel (Lab)

This is a separately loadable **read-only** MV3 lab extension, not the
existing pinned-ID `modules/browser-bridge/extension` product. It uses
only Chrome `tabs`, `scripting`, `storage`, and explicit
`https://chatgpt.com/*` origin access. It has **no** native messaging,
BCT Core/MCP client, RCC, desktop control, CDP/debugging protocol,
filesystem reader, token, network fetch, or public message sender.

## Demonstrated source-level contract

- `BRIDGE_NODE_LIST`: list distinct ChatGPT `/c/<uuid>` tabs; duplicate
  conversation UUIDs are rejected instead of silently picking one.
- `BRIDGE_NODE_BIND`: manually assign a stable node label (e.g. N13,
  N14, N23) to a unique currently open exact conversation UUID. The
  label/UUID mapping is the **only** persistent data.
- `BRIDGE_NODE_READ`: require the registered label, exact tab ID and
  exact conversation UUID both before and *inside* the target page.
  Reads only bounded user/assistant counts, current-generation boolean
  and last assistant text (up to 2,400 characters). Page content is not
  stored or sent outside the browser.
- `BRIDGE_NODE_READ_GROUP`: accept an explicit set of 2–6 registered
  nodes, prevalidate **all** exact labels, UUIDs and tab IDs before making
  any page read, then return per-node bounded snapshots. This is parallel
  observation, not instruction delivery to ChatGPT models.
- `BRIDGE_NODE_SEND` or any other message mutation is unsupported;
  no simulated receipt ever claims that a live ChatGPT prompt was sent.

All calls are internal to the extension origin; false sender IDs are
ignored. The protocol never uses RCC registration/node numbers as
authority. Browser Bridge node labels are user-assigned display aliases.

## Test status / limitations

Run `node test_node_channel.js` and `node test_page_reader.js`
in this folder. Tests simulate three independent tabs and the MV3
`tabs/scripting/storage` boundary. The separate connected browser
read API also independently discovered existing N13, N14 and N23 tabs;
**that fact does not prove this extension has been installed into
the operator's production Chrome.**

Installation into a production Chrome profile, a real DOM read through
this exact extension, and any ChatGPT node-to-node submission require
separate exact-scope authorization and acceptance. Do not overwrite
the original Browser Bridge prototype/native host or RCC configuration.

The extension's sidecar has no pinned Chrome extension ID because this
is an isolated lab artifact, not a registered native host. Any future
Bridge-controlled write/execute flow requires a distinct approved
capability and durable once-only UNKNOWN receipt contract.

## Running manually

Load this folder as unpacked extension into a **new disposable Chrome
profile** (no production profile or native host registration), open
ChatGPT test conversations in that profile, then use the popup
to list, bind, and read. Close only the disposable profile after
testing. The existing operator tabs N13/N14/N23 are not modified.
