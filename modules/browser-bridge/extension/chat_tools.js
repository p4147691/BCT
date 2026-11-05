"use strict";
(() => {
  const match = /^\/c\/([^/?#]+)\/?$/.exec(location.pathname);
  const conversationKey = match?.[1]?.toLowerCase();
  if (!conversationKey) return;
  let busy = false;
  let baseline = null;
  let grantId = null;
  let timer = null;
  const assistants = () => {
    const legacy = [...document.querySelectorAll('[data-message-author-role="assistant"]')];
    return legacy.length ? legacy : [...document.querySelectorAll('main [class*="DilResponseRoot"]')]
      .filter(node => !node.closest('[contenteditable]') && !node.closest('.bg-user-message'));
  };
  const editor = () => document.querySelector('#prompt-textarea[contenteditable="true"], [data-testid="prompt-textarea"][contenteditable="true"], [data-composer-markdown][contenteditable="true"][role="textbox"]');
  const sendButton = () => document.querySelector('button[data-testid="send-button"], button[type="submit"][aria-label="보내기"], button[type="submit"][aria-label="Send"]');
  const generating = () => !!document.querySelector('[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label="생성 중지"]');
  async function digest(text) {
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(bytes)].map(v => v.toString(16).padStart(2, "0")).join("");
  }
  async function sendResult(result) {
    if (generating() || String(editor()?.innerText || "").trim()) return false;
    const input = editor(), button = sendButton();
    if (!input || !button || button.disabled) return false;
    let serialized = JSON.stringify(result);
    if (serialized.length > 60000) {
      await chrome.storage.local.set({["bct-tool-large-result:" + result?.request_id]: result});
      serialized = JSON.stringify({ok: false, request_id: result?.request_id,
        tool_name: result?.tool_name, outcome: "RESULT_TOO_LARGE_FOR_CHAT",
        characters: serialized.length,
        guidance: "Use the tool's compact, query, limit, offset, or exact receipt lookup input. The original effect was not replayed."});
    }
    const text = "[[BCT_TOOL_RESULT]]\n" + serialized +
      "\n[[/BCT_TOOL_RESULT]]\n이 결과는 직전 BCT 도구 호출의 데이터입니다. 같은 호출을 자동 재전송하지 마세요.";
    input.focus();
    if (!document.execCommand("insertText", false, text)) return false;
    button.click();
    return true;
  }
  async function sendBootstrap() {
    if (generating() || String(editor()?.innerText || "").trim()) return false;
    const input = editor(), button = sendButton();
    if (!input || !button || button.disabled) return false;
    const text = "이 대화에는 BCT Browser Bridge가 연결되었습니다. BCT 도구가 필요하면 설명으로 실행했다고 주장하지 말고 다음 형식만 단독 응답하세요:\n" +
      "[[BCT_TOOL_REQUEST]]\n{\"tool\":\"bct_capabilities\",\"arguments\":{\"include_manual\":true}}\n[[/BCT_TOOL_REQUEST]]\n" +
      "Bridge가 실제 결과를 같은 대화로 반환하면 그 결과를 바탕으로 다음 도구를 선택하세요. 외부 효과에는 정확한 Work와 Operation ID를 사용하고 UNKNOWN은 새 ID로 재전송하지 마세요.";
    input.focus();
    if (!document.execCommand("insertText", false, text)) return false;
    button.click();
    return true;
  }
  async function scan() {
    if (busy) return;
    busy = true;
    try {
      const status = await chrome.runtime.sendMessage({type: "BCT_CHAT_STATUS"});
      if (!status?.enabled) { baseline = null; grantId = null; return; }
      const messages = assistants();
      if (grantId !== status.grantId) { grantId = status.grantId; baseline = messages.length; return; }
      const pendingKey = "bct-tool-result-pending:" + conversationKey;
      const pendingResult = (await chrome.storage.local.get(pendingKey))[pendingKey];
      if (pendingResult && await sendResult(pendingResult)) {
        await chrome.storage.local.remove(pendingKey);
        return;
      }
      if (generating() || messages.length <= baseline) return;
      baseline = messages.length;
      const text = String(messages[messages.length - 1]?.innerText || "").trim();
      const request = globalThis.BctToolProtocol?.parse(text);
      if (!request) return;
      const fingerprint = await digest(messages.length + "\n" + text);
      const key = "bct-tool-observed:" + conversationKey;
      const previous = (await chrome.storage.local.get(key))[key];
      if (previous === fingerprint) return;
      await chrome.storage.local.set({[key]: fingerprint});
      let result;
      try {
        result = await chrome.runtime.sendMessage({type: "BCT_CHAT_TOOL_CALL",
          conversationKey, grantId, toolName: request.tool, arguments: request.arguments});
      } catch (_) {
        result = {ok: false, outcome: "UNKNOWN", error: "CHAT_TOOL_TRANSPORT_UNKNOWN_NO_RETRY"};
      }
      if (!(await sendResult(result))) {
        await chrome.storage.local.set({[pendingKey]: result});
      }
    } finally { busy = false; }
  }
  function schedule() {
    clearTimeout(timer); timer = setTimeout(() => scan().catch(() => {}), 700);
  }
  new MutationObserver(schedule).observe(document.querySelector("main") || document.body,
    {subtree: true, childList: true, characterData: true});
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "BCT_BRIDGE_SCAN_NOW") schedule();
    if (message?.type === "BCT_BRIDGE_BOOTSTRAP") {
      sendBootstrap().then(sent => sendResponse({sent})).catch(() => sendResponse({sent: false}));
      return true;
    }
    return false;
  });
  schedule();
})();
