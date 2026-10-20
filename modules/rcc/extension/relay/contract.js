(() => {
  'use strict';

  // The Relay contract is intentionally separate from Core:
  // - Core decides identity, state, and effect evidence.
  // - This module decides only the two fixed endpoints of a relay request.
  // It must not read the browser, touch storage, send a message, or repeat an effect.
  const ROLE = Object.freeze({ MANAGER: 'manager', WORKER: 'worker' });
  const CONVERSATION_KEY = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const OPERATION_ID = /^[A-Za-z0-9_.:-]{1,80}$/;

  function conversationKey(value) {
    const key = String(value || '').trim().toLowerCase();
    if (!CONVERSATION_KEY.test(key)) throw new Error('SIMPLE_RELAY_CONVERSATION_KEY_INVALID');
    return key;
  }

  function role(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized !== ROLE.MANAGER && normalized !== ROLE.WORKER) {
      throw new Error('SIMPLE_RELAY_ROLE_INVALID');
    }
    return normalized;
  }

  function operationId(value) {
    const id = String(value || '').trim();
    if (!OPERATION_ID.test(id)) throw new Error('SIMPLE_RELAY_OPERATION_ID_INVALID');
    return id;
  }

  function binding(managerConversationKey, workerConversationKey) {
    const manager = conversationKey(managerConversationKey);
    const worker = conversationKey(workerConversationKey);
    if (manager === worker) throw new Error('SIMPLE_RELAY_ENDPOINTS_MUST_DIFFER');
    return Object.freeze({ version: 0, managerConversationKey: manager, workerConversationKey: worker });
  }

  function targetFor(bindingValue, from) {
    const source = role(from);
    const checkedBinding = binding(
      bindingValue?.managerConversationKey, bindingValue?.workerConversationKey
    );
    return Object.freeze({
      from: source,
      to: source === ROLE.MANAGER ? ROLE.WORKER : ROLE.MANAGER,
      sourceConversationKey: source === ROLE.MANAGER
        ? checkedBinding.managerConversationKey : checkedBinding.workerConversationKey,
      targetConversationKey: source === ROLE.MANAGER
        ? checkedBinding.workerConversationKey : checkedBinding.managerConversationKey,
    });
  }

  function request(value) {
    const text = String(value?.text || '');
    if (!text || text.length > 12000) throw new Error('SIMPLE_RELAY_TEXT_INVALID');
    const target = targetFor(value?.binding, value?.from);
    return Object.freeze({ ...target, operationId: operationId(value?.operationId), text });
  }

  const api = Object.freeze({ ROLE, binding, request, targetFor, conversationKey, operationId });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccRelayContract = api;
  // Temporary compatibility name for the existing background adapter. It is
  // removed only after the old mutation paths are cut off in stage 6.
  globalThis.SimpleRelayV0 = api;
})();
