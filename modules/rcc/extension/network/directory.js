(() => {
  'use strict';

  // The conversation network is a directory, not an authority system.
  // Role tags are human/AI routing hints only: any explicitly addressed
  // conversation remains a valid relay target regardless of its tags.
  const Identity = typeof module !== 'undefined' && module.exports
    ? require('../core/identity.js') : globalThis.RccCoreIdentity;
  if (!Identity) throw new Error('RCC_CORE_IDENTITY_REQUIRED');

  const PROJECT_ID = /^[A-Za-z0-9_.:-]{1,80}$/;
  const RELAY_ID = /^[A-Za-z0-9_.:-]{1,80}$/;
  const NODE_ACTIVITY = Object.freeze({ ACTIVE: 'ACTIVE', HOLD: 'HOLD', EXCLUDED: 'EXCLUDED' });
  const RELAY_STATE = Object.freeze({
    DRAFT: 'DRAFT',
    SENDING: 'SENDING',
    DELIVERED: 'DELIVERED',
    AWAITING_REPLY: 'AWAITING_REPLY',
    REPLY_OBSERVED: 'REPLY_OBSERVED',
    RETURNING: 'RETURNING',
    RETURNED: 'RETURNED',
    NOT_APPLIED: 'NOT_APPLIED',
    UNKNOWN: 'UNKNOWN',
    FAILED: 'FAILED',
    CANCELLED: 'CANCELLED',
  });

  const STATE_TRANSITIONS = Object.freeze({
    [RELAY_STATE.DRAFT]: [RELAY_STATE.SENDING, RELAY_STATE.CANCELLED],
    [RELAY_STATE.SENDING]: [RELAY_STATE.DELIVERED, RELAY_STATE.NOT_APPLIED, RELAY_STATE.UNKNOWN, RELAY_STATE.FAILED],
    [RELAY_STATE.DELIVERED]: [RELAY_STATE.AWAITING_REPLY, RELAY_STATE.REPLY_OBSERVED, RELAY_STATE.CANCELLED],
    [RELAY_STATE.AWAITING_REPLY]: [RELAY_STATE.REPLY_OBSERVED, RELAY_STATE.CANCELLED],
    [RELAY_STATE.REPLY_OBSERVED]: [RELAY_STATE.RETURNING, RELAY_STATE.CANCELLED],
    [RELAY_STATE.RETURNING]: [RELAY_STATE.RETURNED, RELAY_STATE.NOT_APPLIED, RELAY_STATE.UNKNOWN, RELAY_STATE.FAILED],
    [RELAY_STATE.RETURNED]: [],
    [RELAY_STATE.NOT_APPLIED]: [],
    [RELAY_STATE.UNKNOWN]: [],
    [RELAY_STATE.FAILED]: [],
    [RELAY_STATE.CANCELLED]: [],
  });

  function text(value, errorCode, maxLength) {
    const normalized = String(value || '').trim();
    if (!normalized || normalized.length > maxLength) throw new Error(errorCode);
    return normalized;
  }

  function project(value) {
    const projectId = String(value?.projectId || '').trim();
    if (!PROJECT_ID.test(projectId)) throw new Error('RCC_NETWORK_PROJECT_ID_INVALID');
    return Object.freeze({ projectId, displayName: text(value?.displayName, 'RCC_NETWORK_PROJECT_NAME_INVALID', 120) });
  }

  function roleTags(value) {
    if (!Array.isArray(value)) throw new Error('RCC_NETWORK_ROLE_TAGS_INVALID');
    const tags = [];
    for (const candidate of value) {
      const tag = text(candidate, 'RCC_NETWORK_ROLE_TAG_INVALID', 48);
      if (!tags.includes(tag)) tags.push(tag);
    }
    if (tags.length > 24) throw new Error('RCC_NETWORK_ROLE_TAGS_TOO_MANY');
    return Object.freeze(tags);
  }

  function activity(value) {
    const normalized = String(value || NODE_ACTIVITY.ACTIVE).trim().toUpperCase();
    if (!Object.values(NODE_ACTIVITY).includes(normalized)) throw new Error('RCC_NETWORK_NODE_ACTIVITY_INVALID');
    return normalized;
  }

  function conversationNode(value) {
    return Object.freeze({
      conversationKey: Identity.conversationUuid(value?.conversationKey),
      displayName: text(value?.displayName, 'RCC_NETWORK_NODE_NAME_INVALID', 120),
      roleTags: roleTags(value?.roleTags || []),
      activity: activity(value?.activity),
      // This is an observation label, never a claim of a current connection.
      lastObservation: value?.lastObservation ? Object.freeze({
        status: text(value.lastObservation.status, 'RCC_NETWORK_OBSERVATION_STATUS_INVALID', 48),
        observedAt: text(value.lastObservation.observedAt, 'RCC_NETWORK_OBSERVATION_TIME_INVALID', 64),
      }) : null,
    });
  }

  function directory(value) {
    const checkedProject = project(value?.project);
    if (!Array.isArray(value?.nodes)) throw new Error('RCC_NETWORK_NODES_INVALID');
    const nodes = value.nodes.map(conversationNode);
    const keys = new Set(nodes.map((node) => node.conversationKey));
    if (keys.size !== nodes.length) throw new Error('RCC_NETWORK_NODE_DUPLICATE');
    return Object.freeze({ version: 1, project: checkedProject, nodes: Object.freeze(nodes) });
  }

  function relayId(value) {
    const id = String(value || '').trim();
    if (!RELAY_ID.test(id)) throw new Error('RCC_NETWORK_RELAY_ID_INVALID');
    return id;
  }

  function relayState(value) {
    const state = String(value || '').trim().toUpperCase();
    if (!Object.values(RELAY_STATE).includes(state)) throw new Error('RCC_NETWORK_RELAY_STATE_INVALID');
    return state;
  }

  // A relay record represents the factual transport of one direction. A
  // Worker return is a separate record linked through parentRelayId, so the
  // two immutable originals can never overwrite each other.
  function relayRecord(value) {
    const sourceConversationKey = Identity.conversationUuid(value?.sourceConversationKey);
    const targetConversationKey = Identity.conversationUuid(value?.targetConversationKey);
    if (sourceConversationKey === targetConversationKey) throw new Error('RCC_NETWORK_RELAY_ENDPOINTS_MUST_DIFFER');
    const parentRelayId = value?.parentRelayId == null ? null : relayId(value.parentRelayId);
    return Object.freeze({
      relayId: relayId(value?.relayId),
      parentRelayId,
      sourceConversationKey,
      targetConversationKey,
      originalText: text(value?.originalText, 'RCC_NETWORK_RELAY_TEXT_INVALID', 12000),
      guidance: value?.guidance == null ? null : text(value.guidance, 'RCC_NETWORK_RELAY_GUIDANCE_INVALID', 2000),
      state: relayState(value?.state || RELAY_STATE.DRAFT),
      lastObservedAt: value?.lastObservedAt == null ? null : text(value.lastObservedAt, 'RCC_NETWORK_RELAY_TIME_INVALID', 64),
    });
  }

  function transitionRelay(recordValue, nextState, observedAt) {
    const record = relayRecord(recordValue);
    const next = relayState(nextState);
    if (!STATE_TRANSITIONS[record.state].includes(next)) {
      throw new Error('RCC_NETWORK_RELAY_TRANSITION_INVALID');
    }
    return Object.freeze({
      ...record,
      state: next,
      lastObservedAt: text(observedAt, 'RCC_NETWORK_RELAY_TIME_INVALID', 64),
    });
  }

  const api = Object.freeze({
    NODE_ACTIVITY,
    RELAY_STATE,
    STATE_TRANSITIONS,
    project,
    roleTags,
    conversationNode,
    directory,
    relayRecord,
    transitionRelay,
  });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccConversationNetwork = api;
})();
