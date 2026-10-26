# BCT Monitor module instructions

- Official source authority: local Git main under D:/BCT/source/modules/monitor.
  GitHub p4147691/BCT is publication, backup, CI and review, never a
  remote-to-local source override.
- Never overwrite runtime with an older source or source with installed bytes.
  Reconcile both exact SHA histories and deploy only with an expected-live-SHA guard.
- Installed payload: `D:\ChromeExtensions\DesktopWindow-Monitor`.
- Native host authority is the registered manifest path, not the newest-looking directory.
- Monitor owns observation, exact window controls and presentation only. BCT Core owns identity,
  work, policy, operation receipts and conflicts.
- Do not add dependencies on ACT ports, ACT roles, old node groups, `D:\AI_TOOLS`, or another
  policy/ownership store.
- Google Chrome's current user profile is the only supported ChatGPT profile. Do not recreate the
  retired NAVER profile.
- Window actions require exact HWND/endpoint evidence. Mutations use the BCT operation contract and
  must not be silently retried.
- Keep source, installed payload and loaded runtime distinct. Validate exact files before reload.
- Run `tools/check_monitor_structure.py` and affected Node checks before publishing.
- Do not write `.reload-token` directly. Use the bounded publication path and verify the loaded
  version after reload.
- The former ACT organization projection is compatibility-only. Do not extend it; remove it only
  with focused node-number/status and window-control regression coverage.
- Compatibility-only organization behavior is documented in `MONITOR_ORGANIZATION_MODEL.md`.

## Human-edit authority
- Function edit sources: domains/*.js. Every one of the 588 function declarations has exactly one owner in ten domain files.
- Global/bootstrap statements remain in source-parts/*.js; use source-parts/SOURCE_FUNCTION_INDEX.md to locate the owner.
- extension/monitor.js is generated output. Never edit it directly or restore the former 80k-line historical worktree.
- Always rebuild with tools/build_monitor_bundle.py and validate using --check, check_monitor_structure.py and relevant tests.
- Source ownership alone is NOT independent state/API modularity. The cross-domain globals still need separate acceptance.
- A task is not complete until the exact installed and running version, CI, and physical user E2E are accepted.
