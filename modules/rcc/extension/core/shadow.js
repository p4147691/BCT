(() => {
  'use strict';

  const Identity = typeof module !== 'undefined' && module.exports
    ? require('./identity.js') : globalThis.RccCoreIdentity;
  const State = typeof module !== 'undefined' && module.exports
    ? require('./state.js') : globalThis.RccCoreState;
  if (!Identity || !State) throw new Error('RCC_CORE_SHADOW_DEPENDENCY_REQUIRED');

  const BINDING_VERSION = 0;

  function integerOrNull(value) {
    const number = Number(value);
    return Number.isInteger(number) && number >= 0 ? number : null;
  }

  function messageCounts(endpoint) {
    const telemetry = endpoint?.telemetry && typeof endpoint.telemetry === 'object'
      ? endpoint.telemetry : {};
    return Object.freeze({
      user: integerOrNull(telemetry.user_count),
      assistant: integerOrNull(telemetry.assistant_count),
      turns: integerOrNull(telemetry.turns),
    });
  }

  function observedEndpoint(endpoints, tabId) {
    const matches = (Array.isArray(endpoints) ? endpoints : [])
      .filter((endpoint) => Number(endpoint?.tabId) === Number(tabId));
    return matches.length === 1 ? matches[0] : null;
  }

  function legacyStatus(tabs, endpoints, conversationKey) {
    const resolved = Identity.resolveExactConversation(tabs, conversationKey);
    if (resolved.status === 'MISSING') return 'MISSING';
    if (resolved.status === 'AMBIGUOUS') return 'AMBIGUOUS';
    const endpoint = observedEndpoint(endpoints, resolved.match.tabId);
    if (!endpoint) return 'RECEIVER_UNKNOWN';
    if (String(endpoint.conversationKey || '').toLowerCase() !== resolved.conversationKey
        || String(endpoint.presence || '') !== 'OPEN') return 'PROTOCOL_MISMATCH';
    return endpoint.generating === true ? 'BUSY' : 'CONNECTED';
  }

  // This projects existing read-only tab/endpoint observations through the
  // candidate Core. It makes no browser, DOM, storage, pipe, or relay call.
  function inspectConversation(tabs, endpoints, conversationValue) {
    const conversationKey = Identity.conversationUuid(conversationValue);
    const core = State.inspectConversation(tabs, endpoints, conversationKey);
    const resolved = Identity.resolveExactConversation(tabs, conversationKey);
    const endpoint = resolved.status === 'EXACT'
      ? observedEndpoint(endpoints, resolved.match.tabId) : null;
    const legacy = legacyStatus(tabs, endpoints, conversationKey);
    return Object.freeze({
      conversationKey,
      coreStatus: core.status,
      legacyStatus: legacy,
      stateMatches: core.status === legacy,
      messageCounts: messageCounts(endpoint),
    });
  }

  function binding(value) {
    const candidate = value && typeof value === 'object' ? value : null;
    if (!candidate || Number(candidate.version) !== BINDING_VERSION) {
      throw new Error('RCC_CORE_SHADOW_BINDING_INVALID');
    }
    return Object.freeze({
      managerConversationKey: Identity.conversationUuid(candidate.managerConversationKey),
      workerConversationKey: Identity.conversationUuid(candidate.workerConversationKey),
    });
  }

  function snapshot(value) {
    const route = binding(value?.binding);
    const manager = inspectConversation(value?.tabs, value?.endpoints, route.managerConversationKey);
    const worker = inspectConversation(value?.tabs, value?.endpoints, route.workerConversationKey);
    return Object.freeze({
      schemaVersion: 1,
      mode: 'READ_ONLY_SHADOW',
      manager,
      worker,
      matches: manager.stateMatches === true && worker.stateMatches === true,
    });
  }

  const api = Object.freeze({ snapshot, inspectConversation, messageCounts });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccCoreShadow = api;
})();
