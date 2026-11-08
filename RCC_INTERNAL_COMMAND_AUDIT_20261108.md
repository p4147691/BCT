# RCC command call-site and publication audit (source scan)

Scanned 557 source/test files. Counts are literal occurrences, not proven execution call graphs.

| RCC command | Kind | Source call sites (sample) | Public policy |
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

## Security boundaries
- Existing `_SEALED_BROWSER_COMMANDS` remains unchanged.
- Dedicated read tool uses the original authenticated `bct.operations.run` gateway with Work/Operation IDs.
- RCC validates exact session/tab/window/conversation identity; no alternate send/reconcile path.
- No LIVE installation or restart; no UNKNOWN effect replay.
- This literal scan does not prove all dynamic call sites or command reachability.
