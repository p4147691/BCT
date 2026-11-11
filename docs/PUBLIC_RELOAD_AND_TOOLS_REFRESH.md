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

## Monitor plugin refresh button

Monitor 2.0.2 replaces the old selected-ChatGPT-tab reload action with the same
fixed BCT Control plugin refresh capability. No selected conversation is needed.
The Monitor-only loopback POST checks the exact extension origin and accepts only
an Operation ID. A dedicated bounded Work routes to refresh_tools/bct_control.
There is no fallback to reloading a conversation. Existing Core/tunnel local
recovery buttons and RCC/extension reloads are unchanged.
The UI reports click acceptance and explicitly leaves client catalogue reflection
unverified. Deploy the Core adapter/route before this Monitor payload; old Core
returns an error instead of triggering another action. No LIVE proof is claimed.

## Public Core and MCP tunnel recovery

Existing public tool `bct_service_control` now also supports:
`{"profile":"bct_runtime_v1","action":"recover","target":"core","expected_release_sha":"<current installed SHA>"}`
or the same input with `target:"mcp_tunnel"`.
The SHA comes from current BCT status, not a candidate source commit.

This adapter mirrors Monitor's two fixed local recovery contracts: run only the
existing BCT Core Supervisor or BCT Tunnel Supervisor Windows scheduled task,
then check readiness. Already-ready targets are a no-op. It never installs or
rewrites a task, changes security settings, kills processes, or restarts Chrome.
The existing Work/Operation, policy and protected profile cutover guards apply.
After a dispatched request, unverified readiness is UNKNOWN and must not be
replayed with another Operation ID. Public availability is not approval to run.

The command requires this MCP server/transport to be callable. It cannot repair
the very connection through which the caller has already lost access. Keep
Monitor's independent local Core/tunnel recovery buttons for that situation.
The tool can be exposed to ordinary Chat through the active BCT plugin and
refreshed client catalogue, but that does not guarantee transport availability.
