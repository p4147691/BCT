(() => {
  'use strict';

  const Conversation = typeof module !== 'undefined' && module.exports
    ? require('./conversation.js') : globalThis.RccCoreConversation;
  if (!Conversation) throw new Error('RCC_CORE_CONVERSATION_REQUIRED');

  const INSTANCE_ID = /^[A-Za-z0-9_-]{8,64}$/;
  const REQUEST_ID = /^[A-Za-z0-9_.:-]{1,80}$/;

  function stateRequest(value) {
    const instanceId = String(value?.instanceId || '').trim();
    const requestId = String(value?.requestId || '').trim();
    if (!INSTANCE_ID.test(instanceId)) throw new Error('RCC_CORE_INSTANCE_ID_INVALID');
    if (!REQUEST_ID.test(requestId)) throw new Error('RCC_CORE_REQUEST_ID_INVALID');
    return Object.freeze({ instanceId, requestId, command: 'state' });
  }

  // A failed write or an invalid post-write response is not eligible for an
  // automatic alternate-path attempt. The caller must retain UNKNOWN evidence.
  function classifyDelivery(value) {
    const intent = Conversation.submissionIntent(value?.intent);
    if (value?.transportError) {
      return Object.freeze({ state: 'UNKNOWN', operationId: intent.operationId, targetConversationKey: intent.targetConversationKey });
    }
    return Object.freeze({
      ...Conversation.classifySubmissionAck(value?.ack, intent.targetConversationKey),
      operationId: intent.operationId,
    });
  }

  function mayAutomaticallyRetry() {
    return false;
  }

  // NOT_APPLIED can be considered by a future caller only after it creates a
  // linked new operation and rechecks fresh preconditions. This function does
  // not authorize dispatch and keeps automatic retry impossible.
  function requiresNewOperationForRetry(effectState) {
    return String(effectState || '') === 'NOT_APPLIED';
  }

  const api = Object.freeze({
    stateRequest, classifyDelivery, mayAutomaticallyRetry, requiresNewOperationForRetry,
  });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccCoreTransport = api;
})();
