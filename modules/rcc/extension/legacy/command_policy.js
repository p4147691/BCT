(() => {
  'use strict';

  const NEW_RELAY_COMMANDS = new Set([
    'simple-relay-bind', 'simple-relay-send', 'simple-relay-return',
    'new-chat-send',
  ]);
  const CONVERSATION_COMMANDS = new Set([
    'rename-conversation',
  ]);
  const READ_ONLY_COMMANDS = new Set([
    'ping', 'state', 'result', 'rename-receipt', 'probe', 'probe-tabs',
    'diagnose-activity', 'diagnose-composer', 'diagnose-conversation-ui',
    'api-probe', 'main-capture-get',
  ]);
  // This is lifecycle maintenance, not a product relay path. Its caller is
  // still subject to the external deploy/reload approval gate.
  const MAINTENANCE_COMMANDS = new Set(['reload-extension']);
  const LEGACY_MUTATION_COMMANDS = new Set([
    'clear-relay-state', 'close-conversation-tab', 'conversation-bind',
    'conversation-bootstrap-bind', 'create-chat-tab', 'create-chat-window',
    'ensure', 'main-capture-install', 'manager-promote', 'move-tab',
    'recover-created-result', 'recover-pending', 'register', 'reload-workers',
    'result-ack', 'send', 'send-to-created-tab',
    'send-to-tab', 'send-wakeback',
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

  function nativeCommand(command) {
    const value = String(command || '');
    if (NEW_RELAY_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'NEW_RELAY' });
    if (CONVERSATION_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'CONVERSATION' });
    if (READ_ONLY_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'LEGACY_READONLY' });
    if (MAINTENANCE_COMMANDS.has(value)) return Object.freeze({ allowed: true, kind: 'MAINTENANCE' });
    if (LEGACY_MUTATION_COMMANDS.has(value)) return Object.freeze({ allowed: false, kind: 'LEGACY_MUTATION' });
    return Object.freeze({ allowed: false, kind: 'UNSUPPORTED' });
  }

  function runtimeMessage(type) {
    const value = String(type || '');
    if (READ_ONLY_MESSAGES.has(value)) return Object.freeze({ allowed: true, kind: 'READONLY' });
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
