(() => {
  "use strict";
  if (globalThis.__desktopWindowMonitorBootstrapLoaded) return;
  globalThis.__desktopWindowMonitorBootstrapLoaded = true;
  const directGenerationType = "desktop-window-generation-telemetry";
  const directSystemNode = false;
  let directLastSig = "", directLastSentAt = 0;
  let directAssistantSnapshot = null, directAssistantActivityAt = 0;
  const directLastAssistantText = () => {
    const nodes=[...document.querySelectorAll('[data-message-author-role="assistant"]')];
    // Telemetry must not request rendered text/layout while ChatGPT is streaming.
    return String(nodes.at(-1)?.textContent || "").trim().slice(-2400);
  };
  const directCompletionCues = () => {
    const text=directLastAssistantText(), lower=text.toLowerCase();
    const orange=/(중단|보류|재개|권한|로그인|직접 .*필요|수동 .*필요|승인 .*필요|permission|sign in|manual action|resume)/i.test(text);
    const yellow=/(추가 (정보|입력)|정보가 필요|입력이 필요|업로드|첨부|제공해|보내줘|알려줘야|need (more|additional)|provide|upload|attach|send me)/i.test(text);
    const question=/[?？]\s*$/.test(text) || /(할까|해줄까|원해\??|괜찮을까|어떻게 할까|선택해|확인해줘|알려줘\??|would you like|want me to|should i|please confirm|which (one|option))/i.test(text);
    let attentionCue=orange?"action":yellow?"input":question?"question":"";
    let completionCue="general";
    if (/(needs_review|needs review|검토 필요|검토가 필요)/i.test(text)) completionCue="review";
    else if (/(fail(ed)?|blocked|실패|오류|에러)/i.test(text)) completionCue="failure";
    else if (/(pass|succeeded|성공|정상 완료|완료했습니다|완료됐|완료됨)/i.test(text)) completionCue="success";
    return {attentionCue,completionCue};
  };
  const directUserAttention = () => {
    const retryPattern = /^(?:다시 시도|retry|try again)$/i;
    const timeoutPattern = /(?:메시지\s*전송\s*시간이\s*초과되었습니다|메시지\s*전송.*초과|message.*(?:send|sending|transmission).*(?:timed out|timeout)|(?:request|message).*(?:timed out|timeout))/i;
    for (const button of document.querySelectorAll("button")) {
      const buttonText=String(button.textContent||button.getAttribute("aria-label")||"").replace(/\s+/g," ").trim();
      if(!retryPattern.test(buttonText)) continue;
      const alertScope=button.closest('[role="alert"], [aria-live="assertive"], [aria-live="polite"], [data-testid*="error"]');
      if(alertScope){
        const alertText=String(alertScope.textContent||"").replace(/\s+/g," ").trim();
        if(timeoutPattern.test(alertText)) return {kind:"RETRY_REQUIRED",label:"메시지 전송 시간 초과 · 다시 시도 필요"};
      }
      let scope=button;
      for(let depth=0;scope&&depth<12;depth++,scope=scope.parentElement){
        const text=String(scope.textContent||"").replace(/\s+/g," ").trim();
        if(timeoutPattern.test(text)) return {kind:"RETRY_REQUIRED",label:"메시지 전송 시간 초과 · 다시 시도 필요"};
      }
    }
    return null;
  };
  const directConversationKey = () => { const m=location.pathname.match(/^\/c\/([^/?#]+)/); return m ? m[1] : ""; };
  const directActivityIndicatorId = "desktop-window-activity-indicator";
  const directSetActivityIndicator = (active) => {
    let node=document.getElementById(directActivityIndicatorId);
    if (!active) { node?.remove(); return; }
    if (!node) {
      node=document.createElement("div"); node.id=directActivityIndicatorId; node.textContent="● 활동 중";
      node.setAttribute("aria-hidden","true");
      node.style.cssText="position:fixed;top:10px;right:12px;z-index:2147483647;padding:5px 9px;border-radius:999px;background:rgba(15,23,42,.88);border:1px solid rgba(74,222,128,.58);box-shadow:0 2px 10px rgba(0,0,0,.28);color:#86efac;font:700 12px/1.2 'Segoe UI','Malgun Gothic',sans-serif;letter-spacing:.01em;pointer-events:none;user-select:none";
      (document.body||document.documentElement).appendChild(node);
    }
  };
  document.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.isTrusted !== true) return;
    const key = directConversationKey(); if (!key) return;
    try { chrome.runtime.sendMessage({ type:"desktop-window-user-click", conversationKey:key, at:Date.now() }).catch(()=>{}); } catch (_) {}
  }, true);
  const reportDirectTabSelection = () => {
    if (document.hidden) return;
    const key = directConversationKey();
    try { chrome.runtime.sendMessage({ type:"monitor-chat-tab-selected", conversationKey:key, at:Date.now() }).catch(()=>{}); } catch (_) {}
  };
  const directGenerating = () => {
    const stopSelectors = [
      "button[data-testid='stop-button']",
      "button[data-testid='stop-generating-button']",
      "button[data-testid='composer-stop-button']",
      "button[aria-label='Stop generating']",
      "button[aria-label='Stop streaming']",
      "button[aria-label='Stop']",
      "button[aria-label='\uB2F5\uBCC0 \uC911\uC9C0']",
      "button[aria-label='\uC911\uC9C0']",
      "button[aria-label*='\uC0DD\uC131 \uC911\uC9C0']"
    ];
    if (stopSelectors.some((selector) => !!document.querySelector(selector))) return true;
    const nodes=[...document.querySelectorAll('[data-message-author-role="assistant"]')];
    const node=nodes.at(-1);
    if (!node) return false;
    const streaming='.result-streaming, [data-message-status="streaming"], [data-is-streaming="true"]';
    if (node.matches(streaming) || !!node.querySelector(streaming)) return true;
    const now=Date.now();
    const text=String(node.textContent || "");
    const snapshot=`${nodes.length}:${text.length}:${text.slice(-160)}`;
    if (directAssistantSnapshot===null) directAssistantSnapshot=snapshot;
    else if (snapshot!==directAssistantSnapshot) { directAssistantSnapshot=snapshot; directAssistantActivityAt=now; }
    const scope=node.closest('[data-testid^="conversation-turn-"]') || node.parentElement || node;
    const completionSelectors=[
      'button[data-testid="copy-turn-action-button"]',
      'button[data-testid*="copy"]',
      'button[aria-label="Copy"]',
      'button[aria-label="복사"]',
      'button[aria-label="복사하기"]'
    ];
    if (completionSelectors.some((selector)=>!!scope.querySelector(selector))) return false;
    return directAssistantActivityAt>0 && now-directAssistantActivityAt<10000;
  };
  let directGenerationRecheckTimer = 0;
  const directReport = (force=false) => {
    const key=directConversationKey(), userAttention=directUserAttention(), generating=userAttention?false:directGenerating(), now=Date.now(), cues=generating?{attentionCue:"",completionCue:"general"}:directCompletionCues(), sig=`${key}:${generating}:${cues.attentionCue}:${cues.completionCue}:${String(userAttention?.kind||"")}:${String(userAttention?.label||"")}`;
    if (directGenerationRecheckTimer) { clearTimeout(directGenerationRecheckTimer); directGenerationRecheckTimer=0; }
    if (key && generating && directAssistantActivityAt>0) {
      const remaining=10050-(now-directAssistantActivityAt);
      if (remaining>0) directGenerationRecheckTimer=setTimeout(() => { directGenerationRecheckTimer=0; directReport(true); }, Math.max(50,remaining));
    }
    // Diagnostic isolation: keep telemetry active without mutating the ChatGPT page with an activity badge.
    if (!key || (!force && sig===directLastSig && now-directLastSentAt<2200)) return;
    directLastSig=sig; directLastSentAt=now;
    try { chrome.runtime.sendMessage({type:directGenerationType, conversationKey:key, generating, attentionCue:cues.attentionCue, completionCue:cues.completionCue, userAttention, systemNode:directSystemNode, at:now}).catch(()=>{}); } catch (_) {}
  };
  // ChatGPT streaming can produce many DOM mutations per second. Treat mutations as
  // invalidation signals and coalesce them before scanning the conversation DOM.
  const DIRECT_MUTATION_REPORT_DELAY_MS = 160;
  let directMutationReportTimer = 0;
  const scheduleDirectReport = (force=false) => {
    if (force) {
      if (directMutationReportTimer) {
        clearTimeout(directMutationReportTimer);
        directMutationReportTimer = 0;
      }
      directReport(true);
      return;
    }
    if (directMutationReportTimer) return;
    directMutationReportTimer = setTimeout(() => {
      directMutationReportTimer = 0;
      directReport(false);
    }, document.hidden ? 450 : DIRECT_MUTATION_REPORT_DELAY_MS);
  };
  new MutationObserver(()=>scheduleDirectReport(false)).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:["data-testid","aria-label","disabled"]});
  window.addEventListener("focus", () => { reportDirectTabSelection(); scheduleDirectReport(true); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { reportDirectTabSelection(); scheduleDirectReport(true); } });
  directReport(true);
})();
