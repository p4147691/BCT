# BCT Monitor module instructions

Apply the common BCT policy from `D:\BCT\source\AGENTS.md` first. This file
contains **Monitor-specific additions only**.

## Runtime boundary

- Canonical Monitor source is `D:\BCT\source\modules\monitor`.
- Installed Chrome payload is `D:\ChromeExtensions\DesktopWindow-Monitor`.
- Native-host authority is the actually registered manifest path, not the
  newest-looking directory.
- Keep source, staged payload, installed payload and loaded runtime distinct.
  Never copy installed bytes back over source as an authority shortcut.
- Deploy/reload only with an exact expected-live-SHA guard and verify the
  installed/loaded post-state after the effect.
- Google Chrome's current user profile is the supported ChatGPT profile.
  Do not recreate retired alternate profiles or ACT ownership paths.
- Monitor owns observation, exact window controls and presentation. BCT Core
  owns Work, policy, Operation receipts and conflict handling.

## Mutation and acceptance

- Window actions require exact HWND/endpoint evidence and BCT Operation fencing.
  Do not silently retry uncertain mutations.
- Do not write `.reload-token` directly. Use the bounded publication/reload path
  and verify the loaded version/state after reload.
- Run `tools/check_monitor_structure.py`, bundle checks and affected focused
  tests before publication. Physical UI claims require real running evidence.
- Compatibility-only organization behavior is documented in
  `MONITOR_ORGANIZATION_MODEL.md`; do not extend retired ACT organization paths.

## Human-edit source ownership

- Compatibility-bundle functions are owned by `domains/*.js`.
- Global/bootstrap statements remain in `source-parts/*.js`; use
  `source-parts/SOURCE_FUNCTION_INDEX.md` to locate their owner.
- Extracted features own implementation under `extension/features/<feature>/`.
  Do not copy them back into domains/source-parts.
- `extension/monitor.js` is generated output. Never edit it directly; rebuild
  with `tools/build_monitor_bundle.py`.
- Source ownership is not proof of independent state/API modularity; cross-domain
  globals still need their own acceptance.
