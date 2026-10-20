(() => {
  'use strict';

  const Identity = typeof module !== 'undefined' && module.exports
    ? require('./identity.js') : globalThis.RccCoreIdentity;
  if (!Identity) throw new Error('RCC_CORE_IDENTITY_REQUIRED');

  const OPERATION_ID = /^[A-Za-z0-9_.:-]{1,80}$/;
  const MAX_TEXT_LENGTH = 12000;

  function operationId(value) {
    const id = String(value || '').trim();
    if (!OPERATION_ID.test(id)) throw new Error('RCC_CORE_OPERATION_ID_INVALID');
    return id;
  }

  function messageText(value) {
    const text = String(value || '');
    if (!text || text.length > MAX_TEXT_LENGTH) throw new Error('RCC_CORE_TEXT_INVALID');
    return text;
  }

  // Intent is pure evidence. It does not choose a tab, invoke a content
  // script, persist storage, or retry a previous effect.
  function submissionIntent(value) {
    return Object.freeze({
      operationId: operationId(value?.operationId),
      targetConversationKey: Identity.conversationUuid(value?.targetConversationKey),
      text: messageText(value?.text),
    });
  }

  function classifySubmissionAck(ack, targetConversationValue) {
    const targetConversationKey = Identity.conversationUuid(targetConversationValue);
    if (ack?.ok === true && ack?.submitted === true
        && String(ack?.conversationKey || '').toLowerCase() === targetConversationKey) {
      return Object.freeze({ state: 'SUBMITTED', targetConversationKey });
    }
    if (ack?.effectState === 'NOT_APPLIED' || ack?.submitted === false) {
      return Object.freeze({ state: 'NOT_APPLIED', targetConversationKey });
    }
    return Object.freeze({ state: 'UNKNOWN', targetConversationKey });
  }

  // This mirrors the current V0 return gate without querying the DOM. The DOM
  // adapter remains in content.js until a later, separately accepted cutover.
  function classifyReplyRead(value) {
    const targetConversationKey = Identity.conversationUuid(value?.conversationKey);
    const afterAssistantCount = Number(value?.afterAssistantCount);
    if (!Number.isInteger(afterAssistantCount) || afterAssistantCount < 0) {
      throw new Error('RCC_CORE_ASSISTANT_COUNT_INVALID');
    }
    if (value?.generating === true) return Object.freeze({ state: 'NOT_APPLIED', reason: 'REPLY_STILL_GENERATING' });
    const assistantCount = Number(value?.assistantCount);
    const responseText = String(value?.responseText || '');
    if (!Number.isInteger(assistantCount) || assistantCount <= afterAssistantCount || !responseText) {
      return Object.freeze({ state: 'NOT_APPLIED', reason: 'NEW_REPLY_NOT_READY' });
    }
    if (responseText.length > MAX_TEXT_LENGTH) {
      return Object.freeze({ state: 'NOT_APPLIED', reason: 'REPLY_TOO_LARGE' });
    }
    return Object.freeze({ state: 'REPLY_CAPTURED', conversationKey: targetConversationKey, assistantCount, responseText });
  }

  const api = Object.freeze({
    MAX_TEXT_LENGTH, operationId, messageText, submissionIntent, classifySubmissionAck, classifyReplyRead,
  });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccCoreConversation = api;
})();
