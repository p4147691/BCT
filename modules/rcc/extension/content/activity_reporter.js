let telemetry = (() => { try { return JSON.parse(sessionStorage.getItem(telemetryKey) || '{}'); } catch (_) { return {}; } })();


telemetry.responseSamples = Array.isArray(telemetry.responseSamples) ? telemetry.responseSamples.slice(-20) : [];


function persistTelemetry() { try { sessionStorage.setItem(telemetryKey, JSON.stringify(telemetry)); } catch (_) {} }


function messageNodes(role) { return getMessageUnits(role); }

function sampleJsHeapTelemetry() {
  const memory = performance?.memory;
  if (!memory) return;
  const used = Number(memory.usedJSHeapSize);
  const limit = Number(memory.jsHeapSizeLimit);
  if (Number.isFinite(used) && used >= 0) telemetry.js_heap_used_mb = Math.round((used / 1048576) * 10) / 10;
  if (Number.isFinite(limit) && limit > 0) telemetry.js_heap_limit_mb = Math.round((limit / 1048576) * 10) / 10;
}


function seedConversationUsageOnce(force = false) {


  if (!force && Number.isFinite(Number(telemetry.rendered_chars)) && Number.isFinite(Number(telemetry.turns)) && Number(telemetry.rendered_chars) > 0) return;


  const users = Array.from(messageNodes('user')), assistants = Array.from(messageNodes('assistant'));


  const turnNodes = getConversationTurns();


  const fallbackTurns = turnNodes.length ? turnNodes : Array.from(document.querySelectorAll('main article')).filter((node) => String(node?.innerText || node?.textContent || '').trim());


  const roleNodes = users.length || assistants.length ? [...users, ...assistants] : [];


  const usageNodes = roleNodes.length ? roleNodes : fallbackTurns;


  let chars = 0;


  for (const node of usageNodes) chars += String((node?.querySelector?.('.markdown') || node)?.innerText || node?.textContent || '').length;


  telemetry.user_count = roleNodes.length ? users.length : null;


  telemetry.assistant_count = roleNodes.length ? assistants.length : null;


  telemetry.turns = roleNodes.length ? Math.max(users.length, assistants.length) : fallbackTurns.length;


  telemetry.rendered_chars = chars;


  telemetry.usage_estimate_kind = roleNodes.length ? 'message-role-chars-v2' : 'conversation-turn-chars-v2';


  persistTelemetry();


}


function appendNewMessageUsage(role) {


  const nodes = messageNodes(role);


  const key = role === 'user' ? 'user_count' : 'assistant_count';


  let previous = Number(telemetry[key]);


  if (!Number.isFinite(previous) || previous < 0) previous = 0;


  let chars = Number(telemetry.rendered_chars);


  if (!Number.isFinite(chars) || chars < 0) chars = 0;


  for (let i = previous; i < nodes.length; i += 1) chars += String(nodes[i]?.textContent || '').length;


  telemetry[key] = nodes.length;


  telemetry.turns = Math.min(Number(telemetry.user_count) || 0, Number(telemetry.assistant_count) || 0);


  telemetry.rendered_chars = chars;


  telemetry.usage_estimate_kind = 'incremental-message-chars-v1';


}


seedConversationUsageOnce();


const RELAY_USER_ATTENTION_RULES = [


  { kind:'NEW_CHAT_REQUIRED', label:'새 채팅 필요', re:/(maximum length for (?:this )?conversation|conversation is too long|reached the maximum length|start a new (?:chat|conversation|one)|대화.{0,20}(?:최대 길이|너무 깁니다|길이 제한)|새 (?:채팅|대화).{0,20}(?:시작|계속))/i },


  { kind:'RECOVERY_REQUIRED', label:'새로고침 / 복구 필요', re:/(problem preparing your chat|unable to load (?:the )?(?:chat|conversation)|failed to load (?:the )?(?:chat|conversation)|please (?:reload|refresh)|(?:reload|refresh) the page|대화.{0,30}(?:불러오|로드).{0,20}(?:실패|문제)|페이지.{0,20}(?:새로고침|다시 로드))/i },


  { kind:'RETRY_REQUIRED', label:'다시 시도 필요', re:/(there was an error generating a response|a network error occurred|something went wrong|message.{0,30}(?:timed out|took too long)|request timed out|websocket.{0,30}(?:error|failed)|응답.{0,30}(?:오류|실패|시간.*초과)|네트워크.{0,20}오류|메시지.{0,30}(?:시간.*초과|전송.*실패)|요청.{0,20}시간.*초과|문제가 발생)/i }


];


const RELAY_USER_ATTENTION_TEXT_RE = new RegExp(RELAY_USER_ATTENTION_RULES.map((rule) => rule.re.source).join('|'), 'i');


function relayUserAttentionText(node) {


  if (!node) return '';


  const aria = node.getAttribute?.('aria-label') || '';


  return normalizedUiText([aria, node.innerText, node.textContent].filter(Boolean).join(' ')).slice(0, 1600);


}


function relayUserAttentionUiNode(node) {


  return node instanceof Element && isVisible(node) && !node.closest('[data-message-author-role]');


}


function detectRelayUserAttention() {


  const selector = '[role="alert"],[role="dialog"],[role="status"],[data-testid*="error" i],[data-testid*="retry" i],[data-testid*="reload" i],[data-testid*="refresh" i],main [class*="error" i],main [class*="warning" i]';


  const nodes = [...document.querySelectorAll(selector)].filter(relayUserAttentionUiNode);


  for (const node of nodes) {


    const text = relayUserAttentionText(node);


    for (const rule of RELAY_USER_ATTENTION_RULES) if (rule.re.test(text)) return { kind:rule.kind, label:rule.label };


  }


  const buttons = [...document.querySelectorAll('button')].filter(relayUserAttentionUiNode);


  for (const button of buttons) {


    const text = relayUserAttentionText(button);


    if (/^(retry|try again|다시 시도|재시도|응답 재생성|regenerate(?: response)?)$/i.test(text)) return { kind:'RETRY_REQUIRED', label:'다시 시도 필요' };


    if (/^(reload|refresh|새로고침|페이지 새로고침)$/i.test(text)) return { kind:'RECOVERY_REQUIRED', label:'새로고침 / 복구 필요' };


  }


  return null;


}


let lastReportedGenerating = null;


let lastReportedReadiness = '';


let lastReportedUserAttentionSignature = '';

async function reportGenerationSignal(generating, source = 'dom', force = false) {


  const now = Date.now();


  generating = !!generating;


  if (force) seedConversationUsageOnce(true);


  const readiness = generating ? 'BUSY' : (source === 'network' ? 'READY' : (source === 'network-error' ? 'UNKNOWN' : 'IDLE'));


  const userAttention = detectRelayUserAttention();


  const userAttentionSignature = userAttention ? `${userAttention.kind}:${userAttention.label}` : '';


  if (!force && generating === lastReportedGenerating && readiness === lastReportedReadiness && userAttentionSignature === lastReportedUserAttentionSignature) return;


  const wasGenerating = lastReportedGenerating === true;


  lastReportedGenerating = generating;


  lastReportedReadiness = readiness;


  lastReportedUserAttentionSignature = userAttentionSignature;


  telemetry.userAttention = userAttention;


  telemetry.lastActivityAt = now;


  telemetry.generationState = generating ? 'GENERATING' : 'IDLE';


  telemetry.readiness = generating ? 'BUSY' : (source === 'network' ? 'READY' : (source === 'network-error' ? 'UNKNOWN' : 'IDLE'));


  if (generating) {


    appendNewMessageUsage('user');


    telemetry.generationStartedAt = now;


  }


  if (!generating && wasGenerating) {


    appendNewMessageUsage('assistant');


    telemetry.generationFinishedAt = now;


    if (telemetry.generationStartedAt) telemetry.generationTimeMs = Math.max(0, now - telemetry.generationStartedAt);


  }


  sampleJsHeapTelemetry();
  persistTelemetry();


  try {


    await chrome.runtime.sendMessage({


      type:'relay:activity', generating, url:location.href,

      connection: connectionProblem(),


      telemetry:{generationState:telemetry.generationState,readiness:telemetry.readiness||'IDLE',lastActivityAt:telemetry.lastActivityAt,generationStartedAt:telemetry.generationStartedAt||null,generationFinishedAt:telemetry.generationFinishedAt||null,generationTimeMs:telemetry.generationTimeMs??null,user_count:telemetry.user_count??null,assistant_count:telemetry.assistant_count??null,turns:telemetry.turns??null,rendered_chars:telemetry.rendered_chars??null,js_heap_used_mb:telemetry.js_heap_used_mb??null,js_heap_limit_mb:telemetry.js_heap_limit_mb??null,usage_estimate_kind:telemetry.usage_estimate_kind||'incremental-message-chars-v1',user_attention:telemetry.userAttention||null,signal_source:source}


    });


  } catch (_) {}

}


async function reportGenerationState() { return reportGenerationSignal(isGenerating(), 'dom'); }


let relayGenerationConversationKey = currentConversationKey();


let relayGenerationCheckScheduled = false;


function relayGenerationMutationRelevant(mutation) {
  const target = mutation.target instanceof Element ? mutation.target : mutation.target?.parentElement || null;

  if (mutation.type === 'attributes') {
    if (!['class','data-message-status','data-testid','aria-label','data-talvt-turn-state','data-content-search-unit-key'].includes(String(mutation.attributeName || ''))) return false;
    if (!target) return false;
    return target.matches(
      'button[data-testid="stop-button"],button[data-testid*="stop" i],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label*="stop" i],button[aria-label="중지"],button[aria-label*="중지"],button[aria-label*="멈춤"],[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-talvt-turn-state],.result-streaming,[data-message-status]'
    ) || !!target.closest('[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-turn-key]');
  }

  if (mutation.type !== 'childList') return false;
  const selector = 'button[data-testid="stop-button"],button[data-testid*="stop" i],button[aria-label="Stop streaming"],button[aria-label="Stop"],button[aria-label*="stop" i],button[aria-label="중지"],button[aria-label*="중지"],button[aria-label*="멈춤"],[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"],[data-talvt-turn-state],.result-streaming,[data-message-status]';
  return [...mutation.addedNodes, ...mutation.removedNodes].some((node) => {
    if (!(node instanceof Element)) return false;
    return node.matches(selector) || !!node.querySelector(selector);
  });
}

function relayUserAttentionMutationRelevant(mutation) {
  if (mutation.type !== 'childList') return false;
  const selector = '[role="alert"],[role="dialog"],[role="status"],[data-testid*="error" i],[data-testid*="retry" i],[data-testid*="reload" i],[data-testid*="refresh" i]';
  return [...mutation.addedNodes, ...mutation.removedNodes].some((node) => {
    if (node instanceof Text) {
      const parent = node.parentElement;
      if (!parent || parent.closest('[data-message-author-role],[data-content-search-unit-key]')) return false;
      return RELAY_USER_ATTENTION_TEXT_RE.test(normalizedUiText(node.textContent).slice(0, 1600));
    }
    if (!(node instanceof Element)) return false;
    if (node.matches(selector) || !!node.querySelector(selector)) return true;
    if (node.closest('[data-message-author-role],[data-content-search-unit-key]')) return false;
    return RELAY_USER_ATTENTION_TEXT_RE.test(normalizedUiText(node.textContent).slice(0, 1600));
  });
}


function scheduleRelayGenerationStateCheck(force = false) {


  if (relayGenerationCheckScheduled && !force) return;


  relayGenerationCheckScheduled = true;


  queueMicrotask(() => {


    relayGenerationCheckScheduled = false;


    const key = currentConversationKey();


    const routeChanged = key !== relayGenerationConversationKey;


    if (routeChanged) {


      relayGenerationConversationKey = key;


      lastReportedGenerating = null;


      lastReportedReadiness = '';


      lastReportedUserAttentionSignature = '';


    }


    reportGenerationSignal(isGenerating(), 'dom', force || routeChanged).catch(() => {});


  });


}


const relayGenerationObserver = new MutationObserver((mutations) => {
  if (mutations.some(relayGenerationMutationRelevant)) scheduleRelayGenerationStateCheck(false);
});

const relayGenerationRoot = conversationObserveRoot();
if (relayGenerationRoot) {
  relayGenerationObserver.observe(relayGenerationRoot, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class','data-message-status','data-testid','aria-label','data-talvt-turn-state','data-content-search-unit-key']
  });
}

const relayAttentionObserver = new MutationObserver((mutations) => {
  if (mutations.some(relayUserAttentionMutationRelevant)) scheduleRelayGenerationStateCheck(false);
});
relayAttentionObserver.observe(document.documentElement, { childList: true, subtree: true });


window.addEventListener('focus', () => scheduleRelayGenerationStateCheck(false));


document.addEventListener('visibilitychange', () => { if (!document.hidden) scheduleRelayGenerationStateCheck(false); });


window.addEventListener('pageshow', () => scheduleRelayGenerationStateCheck(false));


reportGenerationState().catch(() => {});

window.addEventListener('online', () => reportGenerationState().catch(() => {}));
window.addEventListener('offline', () => reportGenerationState().catch(() => {}));
