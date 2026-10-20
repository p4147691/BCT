(() => {
  'use strict';

  const Conversation = typeof module !== 'undefined' && module.exports
    ? require('../core/conversation.js') : globalThis.RccCoreConversation;
  if (!Conversation) throw new Error('RCC_CORE_CONVERSATION_REQUIRED');

  const DIRECTION = Object.freeze({ HANDOFF: 'HANDOFF', RETURN: 'RETURN' });
  const GUIDANCE_VERSION = 'v1';

  function label(value, errorCode) {
    const normalized = String(value || '').trim();
    if (!normalized || normalized.length > 120) throw new Error(errorCode);
    return normalized;
  }

  function direction(value) {
    const normalized = String(value || '').trim().toUpperCase();
    if (!Object.values(DIRECTION).includes(normalized)) throw new Error('RCC_RELAY_ENVELOPE_DIRECTION_INVALID');
    return normalized;
  }

  // These are visible continuation prompts, not hidden instructions and not
  // permissions. The BCT transport records the exact prompt used per relay.
  function defaultGuidance(value) {
    const checkedDirection = direction(value?.direction);
    const sourceLabel = label(value?.sourceLabel, 'RCC_RELAY_ENVELOPE_SOURCE_INVALID');
    const targetLabel = label(value?.targetLabel, 'RCC_RELAY_ENVELOPE_TARGET_INVALID');
    if (checkedDirection === DIRECTION.HANDOFF) {
      return `[BCT 반환 안내 ${GUIDANCE_VERSION}]\n이 요청의 처리 결과 전문은 “${sourceLabel}” 대화창으로 반환됩니다.\n후속 전달이 필요하면 대상·요청·이유를 결과 말미에 적어 주세요.`;
    }
    return `[BCT 후속 판단 안내 ${GUIDANCE_VERSION}]\n위 결과는 “${sourceLabel}” 대화창에서 “${targetLabel}” 대화창으로 반환되었습니다.\n결과를 검토해 후속 전달이 필요하면 다음 전달서를 작성하고, 더 할 일이 없으면 완료와 남은 확인 사항을 정리하세요.`;
  }

  function customGuidance(value) {
    if (value == null) return null;
    const normalized = String(value).trim();
    if (!normalized || normalized.length > 2000) throw new Error('RCC_RELAY_ENVELOPE_GUIDANCE_INVALID');
    return normalized;
  }

  function compose(value) {
    const body = String(value?.body || '');
    // A continuation prompt must never turn an empty handoff into a relay.
    // The original body remains a separately stored, non-empty snapshot.
    Conversation.messageText(body);
    const checkedDirection = direction(value?.direction);
    const sourceLabel = label(value?.sourceLabel, 'RCC_RELAY_ENVELOPE_SOURCE_INVALID');
    const targetLabel = label(value?.targetLabel, 'RCC_RELAY_ENVELOPE_TARGET_INVALID');
    const guidance = customGuidance(value?.guidance)
      || defaultGuidance({ direction: checkedDirection, sourceLabel, targetLabel });
    const text = `${body}\n\n---\n${guidance}`;
    Conversation.messageText(text);
    return Object.freeze({
      version: GUIDANCE_VERSION,
      direction: checkedDirection,
      body,
      guidance,
      text,
    });
  }

  const api = Object.freeze({ DIRECTION, GUIDANCE_VERSION, defaultGuidance, compose });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.RccRelayEnvelope = api;
})();
