# RCC command call-site and publication audit (source scan)

Scanned 557 source/test files. Counts are literal occurrences, not proven execution call graphs.

All commands in this table are now discoverable through
`bct_rcc_command_catalog` and callable externally through `bct_browser` with
`arguments.command`.  The historical policy column records the earlier sealed
surface decision only; it is retained for the change audit, not as current
availability.

| RCC command | Kind | Source call sites (sample) | Historical policy before public catalogue |
|---|---|---|---|
| `add-tab-to-group` | mutating | src/bct/features/rcc.py (4); modules/rcc/extension/test_browser_tab_group_adapter_v1.js (1); modules/rcc/extension/test_legacy_command_policy_v6.js (3); modules/rcc/extension/browser/tab_group_adapter.js (2) | Keep sealed; separate security review |
| `close-conversation-tab` | mutating | src/bct/mcp_server.py (2); src/bct/features/rcc.py (5); modules/rcc/extension/browser/tab_close_contract.js (1); modules/rcc/extension/domain/atomic_chat_service.js (2) | Keep sealed; separate security review |
| `create-and-send` | mutating | src/bct/mcp_server.py (3); src/bct/core/operations.py (9); src/bct/features/rcc.py (14); modules/rcc/extension/domain/new_chat_service.js (1) | Keep sealed; separate security review |
| `create-chat-tab` | mutating | src/bct/chain_direction.py (1); src/bct/chain_worker_preparation.py (2); src/bct/chain_worker_provision.py (1); src/bct/mcp_server.py (5) | Existing public contract only |
| `create-chat-window` | mutating | src/bct/chain_worker_preparation.py (2); src/bct/mcp_server.py (4); src/bct/send_delayed_message.py (1); src/bct/features/rcc.py (5) | Existing public contract only |
| `create-tab-group` | mutating | src/bct/features/rcc.py (4); modules/rcc/extension/test_browser_tab_group_adapter_v1.js (3); modules/rcc/extension/test_legacy_command_policy_v6.js (3); modules/rcc/extension/browser/tab_group_adapter.js (1) | Keep sealed; separate security review |
| `delivery-cancel` | mutating | src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/rcc.py (10); modules/rcc/extension/test_delivery_ledger_service_v1.js (5) | Keep sealed; separate security review |
| `delivery-manager-status` | special | src/bct/delivery_continuation_recovery.py (1); src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/rcc.py (13) | Keep sealed; separate security review |
| `delivery-preview` | special | src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/rcc.py (5); tests/test_relay_prompt_delivery.py (1) | Keep sealed; separate security review |
| `delivery-recovery-inspect` | special | src/bct/mcp_server.py (1); src/bct/features/rcc.py (9); modules/rcc/extension/domain/readonly_diagnostics.js (1); modules/rcc/extension/legacy/command_policy.js (1) | Keep sealed; separate security review |
| `delivery-response-read` | special | src/bct/mcp_server.py (1); src/bct/features/rcc.py (9); modules/rcc/extension/domain/readonly_diagnostics.js (1); tests/test_rcc_response_read_contract.py (2) | Keep sealed; separate security review |
| `delivery-return` | mutating | src/bct/delivery_continuation_recovery.py (1); src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/rcc.py (9) | Keep sealed; separate security review |
| `delivery-start` | mutating | src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/claim_reconciliation.py (1); src/bct/features/rcc.py (8) | Keep sealed; separate security review |
| `delivery-status` | mutating | src/bct/delivery_continuation_recovery.py (1); src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/features/rcc.py (8) | Keep sealed; separate security review |
| `inspect-rename-receipt` | special | src/bct/core/operations.py (4); src/bct/features/rcc.py (1); tests/test_rcc_integration.py (2) | Keep sealed; separate security review |
| `move-tab` | mutating | src/bct/chain_worker_provision.py (1); src/bct/mcp_server.py (2); src/bct/features/rcc.py (10); src/bct/features/window_layout_commands.py (1) | Keep sealed; separate security review |
| `move-tab-group` | mutating | src/bct/features/rcc.py (4); modules/rcc/extension/test_browser_tab_group_adapter_v1.js (1); modules/rcc/extension/test_legacy_command_policy_v6.js (3); modules/rcc/extension/browser/tab_group_adapter.js (3) | Keep sealed; separate security review |
| `node-continue` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (11); tests/test_node_continue.py (1); tests/test_rcc_direct_tab.py (1) | Keep sealed; separate security review |
| `node-label-notify` | mutating | src/bct/node_label_notifications.py (1); src/bct/features/rcc.py (6); modules/rcc/extension/domain/readonly_diagnostics.js (1); modules/rcc/extension/legacy/command_policy.js (1) | Keep sealed; separate security review |
| `presence` | read | src/bct/chain_direction.py (1); src/bct/chain_supervisor_route.py (1); src/bct/conversation_network.py (13); src/bct/current_nodes.py (2) | Keep sealed; separate security review |
| `quarantine-legacy-rename-claim` | special | src/bct/core/operations.py (5); src/bct/core/store.py (1); src/bct/features/rcc.py (1); tests/test_rcc_integration.py (1) | Keep sealed; separate security review |
| `read-latest-assistant` | read | src/bct/mcp_server.py (2); src/bct/send_delayed_message.py (3); src/bct/core/operations.py (1); src/bct/features/rcc.py (3) | Dedicated guarded MCP read only |
| `reclassify-rename-claim` | reconcile | src/bct/core/operations.py (5); src/bct/features/rcc.py (6); tests/test_rcc_integration.py (2) | Keep sealed; separate security review |
| `reconcile-create-and-send` | reconcile | src/bct/mcp_server.py (1); src/bct/core/operations.py (4); src/bct/features/rcc.py (5); tests/test_rcc_integration.py (2) | Keep sealed; separate security review |
| `reconcile-rename-conversation` | reconcile | src/bct/core/operations.py (3); src/bct/features/rcc.py (5); tests/test_rcc_integration.py (4) | Keep sealed; separate security review |
| `reconcile-send` | reconcile | src/bct/mcp_server.py (2); src/bct/send_delayed_message.py (2); src/bct/core/operations.py (7); src/bct/features/rcc.py (6) | Keep sealed; separate security review |
| `reconcile-send-to-created-tab` | reconcile | src/bct/mcp_server.py (1); src/bct/send_delayed_message.py (1); src/bct/core/operations.py (3); src/bct/features/rcc.py (1) | Keep sealed; separate security review |
| `reload-extension` | mutating | src/bct/rcc_protected_install.py (1); src/bct/runtime_server.py (1); src/bct/features/deploy.py (1); src/bct/features/owned_extension_action.py (1) | Keep sealed; separate security review |
| `remove-tab-from-group` | mutating | src/bct/features/rcc.py (4); modules/rcc/extension/test_browser_tab_group_adapter_v1.js (1); modules/rcc/extension/test_legacy_command_policy_v6.js (3); modules/rcc/extension/browser/tab_group_adapter.js (1) | Keep sealed; separate security review |
| `rename-conversation` | mutating | src/bct/runtime_server.py (1); src/bct/core/operations.py (4); src/bct/features/rcc.py (9); modules/rcc/extension/test_legacy_command_policy_v6.js (1) | Keep sealed; separate security review |
| `result` | read | src/bct/approval_issuer.py (12); src/bct/background_operations.py (4); src/bct/bottleneck_ack.py (2); src/bct/chain_direction.py (15) | Keep sealed; separate security review |
| `result-of-create-and-send` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (4); src/bct/features/rcc.py (4) | Keep sealed; separate security review |
| `retire-composer-draft` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (7); modules/rcc/extension/domain/readonly_diagnostics.js (1); modules/rcc/extension/legacy/command_policy.js (1) | Keep sealed; separate security review |
| `retire-recovered-execution` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (7); modules/rcc/extension/domain/readonly_diagnostics.js (1); modules/rcc/extension/legacy/command_policy.js (1) | Keep sealed; separate security review |
| `send` | mutating | src/bct/bottleneck_ack.py (3); src/bct/chain_derived_tasks.py (1); src/bct/chain_direction.py (6); src/bct/chain_entry_policy.py (2) | Keep sealed; separate security review |
| `send-message` | mutating | src/bct/chain_worker_provision.py (1); src/bct/continuation_primitives.py (1); src/bct/mcp_server.py (11); src/bct/send_delayed_message.py (2) | Existing public contract only |
| `send-to-created-tab` | mutating | src/bct/mcp_server.py (2); src/bct/send_delayed_message.py (3); src/bct/core/operations.py (4); src/bct/features/rcc.py (7) | Keep sealed; separate security review |
| `send-to-self` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (4) | Keep sealed; separate security review |
| `send-to-tab` | mutating | src/bct/bottleneck_ack.py (1); src/bct/mcp_server.py (1); src/bct/relay_executor.py (1); src/bct/send_delayed_message.py (1) | Keep sealed; separate security review |
| `simple-relay-bind` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (4); modules/rcc/extension/test_core_shadow_protocol_v3.js (1); modules/rcc/extension/test_legacy_command_policy_v6.js (1) | Keep sealed; separate security review |
| `simple-relay-return` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (4); modules/rcc/extension/test_legacy_command_policy_v6.js (1); modules/rcc/extension/domain/readonly_diagnostics.js (1) | Keep sealed; separate security review |
| `simple-relay-send` | mutating | src/bct/mcp_server.py (1); src/bct/features/rcc.py (4); modules/rcc/extension/test_legacy_command_policy_v6.js (2); modules/rcc/extension/domain/readonly_diagnostics.js (1) | Keep sealed; separate security review |
| `state` | read | src/bct/approval_issuer.py (3); src/bct/background_operations.py (10); src/bct/bottleneck_ack.py (14); src/bct/chain_direction.py (9) | Keep sealed; separate security review |
| `tab-get` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (2); modules/rcc/extension/test_browser_tab_create_adapter_v1.js (1) | Keep sealed; separate security review |
| `tab-group-get` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (2); modules/rcc/extension/test_legacy_command_policy_v6.js (2) | Keep sealed; separate security review |
| `tab-groups-list` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (3); modules/rcc/extension/test_legacy_command_policy_v6.js (2) | Keep sealed; separate security review |
| `target-discover` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (6); tests/test_rcc_integration.py (4) | Keep sealed; separate security review |
| `update-tab-group` | mutating | src/bct/features/rcc.py (4); modules/rcc/extension/test_browser_tab_group_adapter_v1.js (1); modules/rcc/extension/test_legacy_command_policy_v6.js (3); modules/rcc/extension/browser/tab_group_adapter.js (2) | Keep sealed; separate security review |
| `window-get` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (2); modules/rcc/extension/test_browser_tab_create_adapter_v1.js (1) | Keep sealed; separate security review |
| `windows-list` | read | src/bct/mcp_server.py (1); src/bct/core/operations.py (1); src/bct/features/rcc.py (1); modules/rcc/extension/test_legacy_command_policy_v6.js (2) | Keep sealed; separate security review |

## Confirmation and safety boundaries
- **Confirmation procedure** here means checking the exact Work, Operation,
  instance, session, tab, window and Conversation UUID before this one read is
  performed.  It is not a Manager/Worker/Supervisor role gate and it does not
  treat ownership history as an execution rank.
- `bct_rcc_command_catalog` lists all feature commands, and `bct_browser`
  accepts each of them through the same `bct.operations.run` confirmation
  path. There is no separate role or ownership gate in the MCP route.
- `read-latest-assistant` is a direct public `bct_browser` command, using the
  same command name and feature contract as BCT's own callers; it has no
  separate convenience wrapper.
- RCC validates exact session/tab/window/conversation identity; no alternate send/reconcile path.
- No LIVE installation or restart; no UNKNOWN effect replay.
- This literal scan does not prove all dynamic call sites or command reachability.

## RCC-native router inventory and BCT wiring

This is the separate inventory the BCT feature table alone cannot show. The
Native Messaging router has **47 implemented command handlers**. All 47 are
now listed as active in `RccLegacyCommandPolicy`; the audit found two handlers
(`presence`, `delivery-response-read`) that had been omitted from the active
list and restores them in this change.

| Wiring result | Count | Commands |
|---|---:|---|
| Same command name from BCT Feature to RCC router | 47 | `add-tab-to-group`, `api-probe`, `close-conversation-tab`, `conversation-bind`, `create-chat-tab`, `create-chat-window`, `create-tab-group`, `delivery-cancel`, `delivery-manager-status`, `delivery-recovery-inspect`, `delivery-response-read`, `delivery-return`, `delivery-start`, `delivery-status`, `diagnose-activity`, `diagnose-composer`, `diagnose-conversation-ui`, `main-capture-get`, `move-tab`, `move-tab-group`, `new-chat-send`, `node-label-notify`, `ping`, `presence`, `probe`, `probe-tabs`, `read-latest-assistant`, `reload-extension`, `remove-tab-from-group`, `rename-conversation`, `rename-receipt`, `result`, `retire-composer-draft`, `retire-recovered-execution`, `send`, `send-to-created-tab`, `send-to-tab`, `simple-relay-bind`, `simple-relay-return`, `simple-relay-send`, `state`, `tab-get`, `tab-group-get`, `tab-groups-list`, `update-tab-group`, `window-get`, `windows-list` |
| BCT alias or local orchestration, not same-name router command | 14 | `create-and-send` -> `new-chat-send`; `send-message` -> `send-to-tab` or `send-to-created-tab`; `target-discover` -> `state`; `result-of-create-and-send`/`reconcile-*` -> `result` or `rename-receipt`; `inspect-rename-receipt`, `quarantine-legacy-rename-claim`, `reclassify-rename-claim`, `node-continue`, `send-to-self`; `delivery-preview` is local BCT preview only |
| Active RCC router command without a current BCT Feature command | 0 | None: every active Native Messaging handler has a direct public `bct_browser(arguments.command=...)` name. |
| Retired command names with no active RCC handler | 11 | `clear-relay-state`, `conversation-bootstrap-bind`, `ensure`, `main-capture-install`, `manager-promote`, `recover-created-result`, `recover-pending`, `register`, `reload-workers`, `result-ack`, `send-wakeback` |

The former eleven RCC-only commands now use the same direct `bct_browser`
route as the established commands. `new-chat-send` retains the existing
opaque target reference contract, and `conversation-bind` requires the exact
instance/session/tab/conversation UUID plus its binding receipt; these are
target-consistency checks, not role or ownership permissions. The retired
names have no implementation to connect, so they remain historical names
rather than being silently re-enabled.

The extension also uses runtime messages between its background and content
scripts. Active messages include `relay:getPendingStatus`, `relay:getState`,
`relay:activity`, `relay:orchestrationAuthorize`, `relay:orchestrationResult`,
and the content routes such as `relay:simpleExecute`, `relay:newChatExecute`,
`relay:readLatestAssistant`, and `relay:renameConversation`. These are
in-extension transport messages, not BCT/RCC Native commands.

## Exact public-wrapper route

`bct_rcc_command_catalog` currently discovers 61 BCT Feature commands: all 47
active RCC Native command names plus 14 explicit BCT composition/recovery
commands. Every listed command is invoked through `bct_browser`; there is no
separate `read-latest-assistant` convenience wrapper or hidden executor.
`bct_rcc_recipe_catalog` only lists visible command sequences; it does not
execute them on the caller's behalf:

`MCP caller identity + Work ID + Operation ID + arguments.command` -> `operations.run(browser)` ->
`RccFeature.prepare/execute` -> `NamedPipeRelayClient`
-> RCC Native Messaging router -> `readLatestAssistant`.

It requires one exact `instance_id`, `session_id`, `tab_id`, `window_id` and
Conversation UUID. A read transport failure is `NOT_APPLIED`/unavailable rather than an
external-effect `UNKNOWN`, and the wrapper has no resend, reconciliation, tab
discovery, creation or message-send fallback.
