(() => {
  'use strict';

  const NEW_RELAY_COMMANDS = new Set([
    'simple-relay-bind', 'simple-relay-send', 'simple-relay-return',
    'delivery-start', 'delivery-cancel', 'delivery-status', 'delivery-return',
    'retire-composer-draft', 'retire-recovered-execution',
    'new-chat-send',
  ]);
  const CONVERSATION_COMMANDS = new Set([
    'rename-conversation', 'rename-dot', 'conversation-bind',
  ]);
  // A bounded operator action against one exact, already-open Chrome tab.
  // It neither creates, moves, closes, nor discovers a replacement tab.
  const EXACT_TAB_COMMANDS = new Set(['send-to-tab']);
  // Small, independently receipted browser actions.  They are deliberately
  // separate from orchestration: a caller can inspect the returned exact
  // tab/window identity before choosing a subsequent action.
  const ATOMIC_CHAT_COMMANDS = new Set([
    'create-chat-tab', 'create-chat-window', 'send-to-created-tab', 'move-tab',
    'create-tab-group', 'add-tab-to-group', 'remove-tab-from-group',
    'move-tab-group', 'update-tab-group', 'close-conversation-tab',
  ]);
  const ORCHESTRATION_COMMANDS = new Set(['send']);
  const NODE_LABEL_COMMANDS = new Set(['node-label-notify']);
  const READ_ONLY_COMMANDS = new Set([
    'ping', 'presence', 'state', 'result', 'rename-receipt', 'probe', 'probe-tabs',
    'diagnose-activity', 'diagnose-composer', 'diagnose-conversation-ui',
    'api-probe', 'main-capture-get', 'delivery-manager-status', 'delivery-response-read', 'delivery-recovery-inspect',
    'tab-get', 'windows-list', 'window-get', 'tab-groups-list', 'tab-group-get', 'read-latest-assistant',
  ]);
  // This is lifecycle maintenance, not a product relay path. Its caller is
  // still subject to the external deploy/reload approval gate.
  const MAINTENANCE_COMMANDS = new Set(['reload-extension']);
  const ALL_NATIVE_COMMANDS = new Set([
    ...NEW_RELAY_COMMANDS, ...CONVERSATION_COMMANDS, ...EXACT_TAB_COMMANDS,
    ...ATOMIC_CHAT_COMMANDS, ...ORCHESTRATION_COMMANDS, ...NODE_LABEL_COMMANDS,
    ...READ_ONLY_COMMANDS, ...MAINTENANCE_COMMANDS,
  ]);
  // Canonical wire names are the public RCC command names.  Native hyphen
  // spellings and the previous rcc_<legacy> form remain input aliases only so
  // receipts and already-installed callers can be reconciled without a new
  // browser action.
  const CANONICAL_PUBLIC_BY_NATIVE = Object.freeze({
    'add-tab-to-group': 'rcc_move_tab_to_group',
    'api-probe': 'rcc_get_conversation_api_response',
    'close-conversation-tab': 'rcc_close_conversation_tab',
    'conversation-bind': 'rcc_bind_conversation_to_node',
    'create-chat-tab': 'rcc_create_chat_tab',
    'create-chat-window': 'rcc_create_chat_window',
    'create-tab-group': 'rcc_create_tab_group_from_tabs',
    'delivery-cancel': 'rcc_cancel_delivery',
    'delivery-manager-status': 'rcc_get_delivery_manager_response',
    'delivery-recovery-inspect': 'rcc_get_delivery_recovery_evidence',
    'delivery-response-read': 'rcc_get_delivery_response',
    'delivery-return': 'rcc_return_delivery_to_manager',
    'delivery-start': 'rcc_start_delivery_to_worker',
    'delivery-status': 'rcc_get_delivery_evidence',
    'diagnose-activity': 'rcc_get_conversation_activity',
    'diagnose-composer': 'rcc_get_composer_state',
    'diagnose-conversation-ui': 'rcc_get_conversation_ui_diagnostics',
    'main-capture-get': 'rcc_get_conversation_capture',
    'move-tab': 'rcc_move_tab_to_window',
    'move-tab-group': 'rcc_move_tab_group_to_window',
    'new-chat-send': 'rcc_create_chat_and_send_message',
    'node-label-notify': 'rcc_update_conversation_favicon',
    'ping': 'rcc_get_extension_connection',
    'presence': 'rcc_get_target_availability',
    'probe': 'rcc_check_target_tab_response',
    'probe-tabs': 'rcc_check_chat_tab_responses',
    'read-latest-assistant': 'rcc_get_latest_assistant_message',
    'reload-extension': 'rcc_reload_extension',
    'remove-tab-from-group': 'rcc_move_tab_from_group',
    'rename-conversation': 'rcc_rename_conversation',
    'rename-dot': 'rcc_rename_dot',
    'rename-receipt': 'rcc_get_conversation_rename_evidence',
    'result': 'rcc_get_operation_result',
    'retire-composer-draft': 'rcc_retire_delivery_draft',
    'retire-recovered-execution': 'rcc_retire_recovered_delivery_execution',
    'send': 'rcc_send_message',
    'send-to-created-tab': 'rcc_send_message_to_created_tab',
    'send-to-tab': 'rcc_send_message_to_tab',
    'simple-relay-bind': 'rcc_bind_simple_relay',
    'simple-relay-return': 'rcc_return_simple_relay_response',
    'simple-relay-send': 'rcc_send_simple_relay_message',
    'state': 'rcc_get_extension_state',
    'tab-get': 'rcc_get_tab',
    'tab-group-get': 'rcc_get_tab_group',
    'tab-groups-list': 'rcc_list_tab_groups',
    'update-tab-group': 'rcc_update_tab_group',
    'window-get': 'rcc_get_window',
    'windows-list': 'rcc_list_windows',
  });
  const NATIVE_BY_CANONICAL_PUBLIC = Object.freeze(Object.fromEntries(
    Object.entries(CANONICAL_PUBLIC_BY_NATIVE).map(([native, canonical]) => [canonical, native])
  ));
  const LEGACY_MUTATION_COMMANDS = new Set([
    'clear-relay-state',
    'conversation-bootstrap-bind',
    'ensure', 'main-capture-install', 'manager-promote',
    'recover-created-result', 'recover-pending', 'register', 'reload-workers',
    'result-ack', 'send-wakeback',
  ]);
  const LEGACY_MUTATION_MESSAGES = new Set([
    'relay:actDirectTask', 'relay:actLocalExecution', 'relay:actWorkerOperation',
    'relay:actNaturalCommand', 'relay:actBootstrapResync', 'relay:forceRefresh',
    'relay:authorizeInjection', 'relay:consumeBindingLease', 'relay:register',
    'relay:arm', 'relay:manualSend', 'relay:bootstrap', 'relay:hello',
    'relay:returnDelivered', 'relay:deliveryReady', 'relay:autoDirective',
    'relay:workerResult',
  ]);
  const READ_ONLY_MESSAGES = new Set([
    'relay:getPendingStatus', 'relay:getState', 'relay:activity',
  ]);
  const ORCHESTRATION_MESSAGES = new Set([
    'relay:orchestrationAuthorize', 'relay:orchestrationResult',
  ]);

  function toNativeCommand(command) {
    const value = String(command || '');
    if (NATIVE_BY_CANONICAL_PUBLIC[value]) return NATIVE_BY_CANONICAL_PUBLIC[value];
    if (!value.startsWith('rcc_')) return value;
    const legacyCandidate = value.slice(4).replaceAll('_', '-');
    return ALL_NATIVE_COMMANDS.has(legacyCandidate) ? legacyCandidate : value;
  }

  function toPublicNativeCommand(command) {
    const value = toNativeCommand(command);
    return CANONICAL_PUBLIC_BY_NATIVE[value] || value;
  }

  function nativeCommand(command) {
    const value = toNativeCommand(command);
    if (NEW_RELAY_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'NEW_RELAY' });
    if (CONVERSATION_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'CONVERSATION' });
    if (EXACT_TAB_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'EXACT_TAB' });
    if (ATOMIC_CHAT_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'ATOMIC_CHAT' });
    if (ORCHESTRATION_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'ORCHESTRATION' });
    if (NODE_LABEL_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'NODE_LABEL_NOTIFY' });
    if (READ_ONLY_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'LEGACY_READONLY' });
    if (MAINTENANCE_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'MAINTENANCE' });
    if (LEGACY_MUTATION_COMMANDS.has(value)) return Object.freeze({ allowed: false, kind: 'LEGACY_MUTATION' });
    return Object.freeze({ allowed: false, kind: 'UNSUPPORTED' });
  }

  function runtimeMessage(type) {
    const value = String(type || '');
    if (READ_ONLY_MESSAGES.has(value)) return Object.freeze({ allowed: true, kind: 'READONLY' });
    if (ORCHESTRATION_MESSAGES.has(value)) return Object.freeze({ allowed: true, kind: 'ORCHESTRATION' });
    if (LEGACY_MUTATION_MESSAGES.has(value)) return Object.freeze({ allowed: false, kind: 'LEGACY_MUTATION' });
    return Object.freeze({ allowed: false, kind: 'UNSUPPORTED' });
  }

  function rejectCode(scope, value, decision) {
    return `RCC_${scope}_${decision.kind}_DISABLED:${String(value || '')}`;
  }

  const api = Object.freeze({
    nativeCommand, runtimeMessage, rejectCode,
    toNativeCommand,
    // Compatibility export for callers that have not yet adopted the neutral
    // name. It resolves canonical and old wire aliases to the same native key.
    toLegacyNativeCommand: toNativeCommand,
    toPublicNativeCommand,
  });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccLegacyCommandPolicy = api;
})();
