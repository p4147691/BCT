(() => {
  'use strict';

  const NEW_RELAY_COMMANDS = new Set([
    'simple-relay-bind', 'simple-relay-send', 'simple-relay-return',
    'delivery-start', 'delivery-cancel', 'delivery-status', 'delivery-return',
    'retire-composer-draft', 'retire-recovered-execution',
    'new-chat-send',
  ]);
  const CONVERSATION_COMMANDS = new Set([
    'rename-conversation', 'conversation-bind',
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
    'ping', 'state', 'result', 'rename-receipt', 'probe', 'probe-tabs',
    'diagnose-activity', 'diagnose-composer', 'diagnose-conversation-ui',
    'api-probe', 'main-capture-get', 'delivery-manager-status', 'delivery-recovery-inspect',
    'tab-get', 'windows-list', 'window-get', 'tab-groups-list', 'tab-group-get', 'read-latest-assistant',
  ]);
  // This is lifecycle maintenance, not a product relay path. Its caller is
  // still subject to the external deploy/reload approval gate.
  const MAINTENANCE_COMMANDS = new Set(['reload-extension']);
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

  function nativeCommand(command) {
    const value = String(command || '');
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

  const api = Object.freeze({ nativeCommand, runtimeMessage, rejectCode });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccLegacyCommandPolicy = api;
})();
