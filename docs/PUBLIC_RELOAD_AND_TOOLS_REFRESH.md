# Public maintenance commands

These are separate operations. Reloading a Chrome extension does not refresh
ChatGPT's cached MCP tool catalogue. Do not reload Chrome or Core as a substitute.
Use a bounded Work with the indicated capability and one immutable Operation ID.
An UNKNOWN effect must be reconciled from its original receipt, never reissued.

## Existing public commands

- RCC: `bct_owned_extension_action`, arguments
  `{"target":"rcc","action":"reload","instance_id":"<fresh exact instance>"}`.
  Reuses BrowserFeature's exact-instance reload contract.
- Monitor: `bct_owned_extension_action`, arguments
  `{"target":"monitor","action":"reload"}`.
  Verifies the installed extension identity, publishes a reload token and checks
  its ACK plus fresh runtime telemetry. It accepts no arbitrary extension ID.
- The RCC-native equivalent remains discoverable in
  `bct_rcc_command_catalog`: `bct_browser` command `rcc_reload_extension`.

These commands already existed; this candidate does not replace them.

## New candidate: ChatGPT BCT Control tools refresh

`bct_browser_extension_manage`, arguments
`{"operation":"refresh_tools","target":"bct_control"}`.

The bounded adapter reuses the existing enabled CDP policy and dependencies.
It opens only its own background tab in the existing Chrome session, verifies
the fixed BCT Control plugin URL and unique visible heading/button, clicks once,
and closes only that tab. It does not start Chrome, focus another window, alter
permissions, sign in, accept a dialog, or invoke a private platform API.
Unexpected UI or missing existing policy stops the operation.

APPLIED means the click was dispatched and owned-tab cleanup confirmed.
It does **not** mean the new tool definitions reached the calling conversation.
Check a subsequent client tools/list and the expected tool description/schema
separately. A successful BCT server capabilities call alone is not that proof.

Block map:
- reused module: BrowserExtensionManageFeature settings, Work/Operation fence;
- new partial recipe: fixed-plugin owned-tab refresh and cleanup;
- isolated validator: exact origin/path, heading and enabled unique button;
- receipt: click/cleanup proof with client_catalog_verified=false.

## Version and deployment evidence

Every changed RCC payload must use a new numeric manifest version, a matching
human-readable version_name and a unique background build identifier.
Never describe two different payloads solely by the same version string.
Before acceptance, compare source and installed file hashes, then independently
check the running extension's advertised build identifier and fresh session.
A source/installed MATCH is not proof that the old running worker reloaded.

This candidate changes Core's adapter, not RCC's extension payload; it therefore
does not falsely bump RCC or claim to upgrade the operating extension.
Report Core source SHA, installed release SHA/generation, RCC manifest version,
payload hashes and running background_build_id separately.
The CI scope job runs scripts/check_extension_versions.py against an exact Git
baseline. Changed RCC/Monitor extension payloads must increase the numeric
version and show it in version_name. RCC additionally requires matching new
background/content build IDs. Unchanged targets do not require a cosmetic bump.
The gate checks source identity, not installed/running state. Deployment must
still perform the independent runtime checks above. It compares against the
base release and does not allocate versions across concurrent unreleased branches.

## Acceptance boundary

Core changes use GUARDED_CI_FIRST. Isolated Python/Node contract tests are not
physical browser E2E. Before integration/release, run exact-candidate CI and
review. Then obtain any required action-time approval for protected deployment
or restart, verify the exact live UI and permissions, run one refresh operation,
and independently verify the client catalogue. No LIVE refresh, extension reload,
Core restart, shared-main integration or deployment is performed by these tests.
