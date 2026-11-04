"use strict";
const result = document.getElementById("result");
const chatStatus = document.getElementById("chatStatus");
async function activeChat() {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs?.[0];
  const key = BctBridgeChat.conversationKey(tab?.url);
  return key && typeof tab?.id === "number" ? {key, tabId: tab.id} : null;
}
async function setChatConsent(enabled) {
  try {
    const chat = await activeChat();
    if (!chat) {
      chatStatus.textContent = "현재 탭이 ChatGPT 대화(/c/UUID)가 아닙니다.";
      return;
    }
    const flag = "bct-chat-consent:" + chat.key + ":" + chat.tabId;
    if (enabled) await chrome.storage.session.set({[flag]: true});
    else await chrome.storage.session.remove(flag);
    chatStatus.textContent = enabled ? "이 Chrome 탭에서만 읽기 요청을 허용했습니다." : "이 탭의 자동 읽기 요청을 중단했습니다.";
    if (enabled) {
      try { await chrome.tabs.sendMessage(chat.tabId, {type: "BCT_BRIDGE_SCAN_NOW"}); }
      catch (_) { chatStatus.textContent += " 페이지가 로드되어야 감지가 시작됩니다."; }
    }
  } catch (_) { chatStatus.textContent = "대화 활성화 상태를 확인할 수 없습니다."; }
}
document.getElementById("chatEnable").addEventListener("click", () => setChatConsent(true));
document.getElementById("chatDisable").addEventListener("click", () => setChatConsent(false));
document.getElementById("read").addEventListener("click", async () => {
  result.textContent = "요청 중";
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "READ_FIXTURE", path: document.getElementById("path").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
document.getElementById("lookup").addEventListener("click", async () => {
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "RECEIPT_LOOKUP", operationId: document.getElementById("operationId").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
