# BWM Runtime UI Layout V1 — AI-directed presentation configuration

## Status and authority
- Engine: `extension/monitor-ui-layout.js`, styles: `extension/monitor-ui-layout.css`.
- The extension's existing button IDs, onclick handlers, BCT/RCC/native protocols, endpoint identities and task receipts remain untouched.
- Configuration is stored in `chrome.storage.local["bwm.monitor.ui.layout.v1"]`; it is **not** Git source, Core policy, or a source of live task truth.
- This is a one-time runtime capability installation. Once installed, ordinary layout edits mutate only the configuration key and require **no source edit, GitHub PR, CI, Core deploy or extension reload**.
- The existing independent worker-list 3-column preference is not read, migrated, overwritten or reset. This V1 engine intentionally does not own node-list column state.

## Supported schema (allowlisted only)
```json
{
  "version": 1,
  "toolbar": {
    "placement": "inline",
    "order": [
      "monitorExtensionReload",
      "monitorRccReload",
      "monitorBctRecover",
      "monitorMcpTunnelRecover",
      "monitorBctControlRefresh"
    ],
    "hidden": [],
    "density": "compact",
    "gap": 2
  }
}
```
- `placement`: `inline` puts the existing five buttons on the BWM version-title line; `below` restores their original row.
- `density`: `compact` or `normal`; `gap`: integer 0..16 pixels.
- `order`: exactly one occurrence of each of the five registered IDs; `hidden`: any unique subset of them.
- Unexpected keys, unknown button IDs, unsafe styles, duplicate entries and invalid values are rejected **before write**. Arbitrary CSS/JS/URL/action payloads are unsupported.
- Header buttons may wrap if the actual BWM window is too narrow. No layout engine can guarantee that all labels fit on one line at any width.

## AI operator path
1. Identify and verify the exact running BWM Chrome window/tab via the existing BCT read-only target and window-control interfaces.
2. Open the small **배치** control in the BWM title, which reveals the JSON input and `배치 적용` control. This is an automation entrypoint; the user need not edit it manually.
3. Read the current value, change only required allowlisted configuration keys, invoke `배치 적용`, and verify actual buttons, positions and storage persistence. BCT desktop automation must honor its exact-window Lease and not send global input without user authorization.
4. If the change is undesirable, choose `기본 배치` or write the previous validated JSON. Configuration changes propagate across BWM views through `chrome.storage.onChanged`; there is no polling loop.
5. Mark applied only with actual readback and visual confirmation. A UIA/BDc action or storage ACK alone is not proof of visual placement.

There is **no exposed BCT Core HTTP write endpoint** in V1. Do not misrepresent in-chat messages as already capable of editing an uninstalled monitor. The JSON editor is a narrow BCT-operable bridge. A direct authenticated BCT command could be considered separately if necessary.

## Initial delivery and rollback
- Test in an isolated BCT worktree first. Preserve the installed extension, RCC, Native Host, Chrome tabs, all node labels, window geometry, and active Work claims.
- Syntax, `check_monitor_ui_layout_config.js`, `check_monitor_structure.py`, button/recovery regressions and real-browser/same-ID loaded-instance validation are gates before declaring LIVE accepted.
- If initial install requires Chrome extension reload, reuse the official bounded monitor deployment path. This is a **one-time engine rollout**, not the per-layout edit path.
- Rollback of layout alone: remove the storage key; it returns buttons to original parent/order and leaves every other preference untouched. Rollback of engine: use precise original deployed payload backup.

## Extensibility
Keep a verified registry of **presentation-only** movable elements. Add further panels, badges, typography and sizes only through separately tested descriptors. New real actions still require code/reviews; layout data must never carry executable code or BCT effects.
