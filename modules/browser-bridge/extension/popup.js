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
    if (enabled) await chrome.storage.session.set({[flag]: crypto.randomUUID().replace(/-/g, "")});
    else await chrome.storage.session.remove(flag);
    chatStatus.textContent = enabled ? "이 Chrome 탭에서만 읽기 요청을 허용했습니다." : "이 탭의 자동 읽기 요청을 중단했습니다.";
    // Notify on both enable and revoke; status and grant are rechecked by content.
    try { await chrome.tabs.sendMessage(chat.tabId, {type: "BCT_BRIDGE_SCAN_NOW"}); }
    catch (_) { chatStatus.textContent += " 페이지가 로드되어야 감지가 갱신됩니다."; }
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

async function submitMutating(type, args) {
  if (!globalThis.confirm("이 작업은 로컬 BCT에서 실제 변경/실행됩니다. 해당 Work 범위로 한 번 실행할까요?")) return;
  result.textContent = "요청 중 — 오류·연결 끊김 시 자동 재전송하지 않음";
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type, confirmed: true, arguments: args}), null, 2); }
  catch (error) { result.textContent = "UNKNOWN / NO RETRY: " + String(error); }
}
document.getElementById("write").addEventListener("click", () => {
  const path = document.getElementById("writePath").value;
  const content = document.getElementById("writeContent").value;
  const sha = document.getElementById("expectedSha").value.trim();
  submitMutating("WRITE_FIXTURE", {...{path, content}, ...(sha ? {expected_sha256: sha} : {expected_absent: true})});
});
document.getElementById("execute").addEventListener("click", () => {
  let argv;
  try { argv = JSON.parse(document.getElementById("execArgv").value); }
  catch (_) { result.textContent = "argv JSON 형식 오류"; return; }
  submitMutating("EXECUTE_FIXTURE", {cwd: document.getElementById("execCwd").value, argv});
});
