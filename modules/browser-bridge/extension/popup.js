const result = document.getElementById("result");
const show = value => { result.textContent = JSON.stringify(value, null, 2); };
document.getElementById("enable").addEventListener("click", async () => {
  try { show(await chrome.runtime.sendMessage({type: "BCT_CHAT_ENABLE_CURRENT"})); }
  catch (error) { result.textContent = String(error); }
});
document.getElementById("list").addEventListener("click", async () => {
  try { show(await chrome.runtime.sendMessage({type: "BCT_TOOL_LIST"})); }
  catch (error) { result.textContent = String(error); }
});
document.getElementById("call").addEventListener("click", async () => {
  try {
    const args = JSON.parse(document.getElementById("arguments").value);
    show(await chrome.runtime.sendMessage({type: "BCT_TOOL_CALL", toolName: document.getElementById("tool").value, arguments: args}));
  } catch (error) { result.textContent = String(error); }
});
document.getElementById("read").addEventListener("click", async () => {
  result.textContent = "요청 중";
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "READ_FIXTURE", path: document.getElementById("path").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
document.getElementById("lookup").addEventListener("click", async () => {
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "RECEIPT_LOOKUP", operationId: document.getElementById("operationId").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
