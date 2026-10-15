const result = document.getElementById("result");
document.getElementById("read").addEventListener("click", async () => {
  result.textContent = "요청 중";
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "READ_FIXTURE", path: document.getElementById("path").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
document.getElementById("lookup").addEventListener("click", async () => {
  try { result.textContent = JSON.stringify(await chrome.runtime.sendMessage({type: "RECEIPT_LOOKUP", operationId: document.getElementById("operationId").value}), null, 2); }
  catch (error) { result.textContent = String(error); }
});
