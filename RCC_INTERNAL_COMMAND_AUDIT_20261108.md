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
- `bct_rcc_read_latest_assistant` remains a convenience wrapper for its exact
  read contract; it is no longer the sole public RCC command.
- RCC validates exact session/tab/window/conversation identity; no alternate send/reconcile path.
- No LIVE installation or restart; no UNKNOWN effect replay.
- This literal scan does not prove all dynamic call sites or command reachability.

## Extension router-only commands and messages

The table above is the BCT Feature command inventory.  The RCC extension also
accepts the following command families directly from its Native Messaging
router.  They are not caller-facing BCT MCP commands and do not become public
merely because their browser-side handler is read-only.

| Router family | Commands/messages | Function | Publication decision |
|---|---|---|---|
| Diagnostics | `ping`, `probe`, `probe-tabs`, `api-probe`, `diagnose-activity`, `diagnose-composer`, `diagnose-conversation-ui`, `main-capture-get`, `rename-receipt` | Endpoint/content health and bounded diagnostic observations | Internal: diagnostics reveal browser topology and in some cases page-derived state; expose only after a separate scoped contract review. |
| Browser topology | `tab-get`, `windows-list`, `window-get`, `tab-groups-list`, `tab-group-get` | Exact Chrome tab/window/group observations | Internal: IDs are session-scoped and must not be guessed or used as a target discovery bypass. |
| Conversation/delivery | `conversation-bind`, `new-chat-send`, `delivery-*`, `simple-relay-*` | Bind/relay/durable delivery lifecycle | Internal: must remain coupled to Work, receipt, claim, generation and return fences. |
| Legacy mutation commands | `clear-relay-state`, `conversation-bootstrap-bind`, `ensure`, `main-capture-install`, `manager-promote`, `recover-created-result`, `recover-pending`, `register`, `reload-workers`, `result-ack`, `send-wakeback` | Historical state-changing paths | Disabled by `RccLegacyCommandPolicy`; never publish. |
| Runtime messages | `relay:getPendingStatus`, `relay:getState`, `relay:activity` | Extension content/background observations | Internal transport protocol, not MCP surface. |
| Legacy runtime messages | `relay:actDirectTask`, `relay:actLocalExecution`, `relay:actWorkerOperation`, `relay:actNaturalCommand`, `relay:actBootstrapResync`, `relay:forceRefresh`, `relay:authorizeInjection`, `relay:consumeBindingLease`, `relay:register`, `relay:arm`, `relay:manualSend`, `relay:bootstrap`, `relay:hello`, `relay:returnDelivered`, `relay:deliveryReady`, `relay:autoDirective`, `relay:workerResult` | Historical control/injection and relay actions | Disabled by `RccLegacyCommandPolicy`; never publish. |

## Exact public-wrapper route

`bct_rcc_command_catalog` is the public discovery entry point. Every listed
command is invoked through `bct_browser`; `bct_rcc_read_latest_assistant`
remains an optional convenience wrapper:

`MCP caller identity + Work ID + Operation ID + arguments.command` -> `operations.run(browser)` ->
`RccFeature.prepare/execute(read-latest-assistant)` -> `NamedPipeRelayClient`
-> RCC Native Messaging router -> `readLatestAssistant`.

It requires one exact `instance_id`, `session_id`, `tab_id`, `window_id` and
Conversation UUID.  The generic `bct_browser` route remains sealed for this
command.  A read transport failure is `NOT_APPLIED`/unavailable rather than an
external-effect `UNKNOWN`, and the wrapper has no resend, reconciliation, tab
discovery, creation or message-send fallback.
