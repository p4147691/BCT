"use strict";
// No content scripts or external web-page command channel.
const HOST = "com.bct.browser_bridge.prototype";
let port = null;
const pending = new Map();
const identifier = () => crypto.randomUUID().replace(/-/g, "");
const unknown = code => ({ok: false, outcome: "UNKNOWN", error: code});
function connect() {
  if (port) return port;
  const current = chrome.runtime.connectNative(HOST);
  port = current;
  current.onMessage.addListener(reply => {
    const id = reply?.request_id;
    if (typeof id !== "string" || !pending.has(id)) return;
    const callback = pending.get(id); pending.delete(id); callback(reply);
  });
  current.onDisconnect.addListener(() => {
    if (port === current) port = null;
    for (const [id, callback] of pending) { pending.delete(id); callback(unknown("NATIVE_DISCONNECTED_NO_RETRY")); }
  });
  return current;
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !["READ_FIXTURE", "RECEIPT_LOOKUP"].includes(message?.type)) return false;
  const lookup = message.type === "RECEIPT_LOOKUP";
  if (!lookup && (typeof message.path !== "string" || !message.path || message.path.length > 1024)) {
    sendResponse({ok: false, error: "INVALID_PATH"}); return false;
  }
  if (lookup && (typeof message.operationId !== "string" || !/^[a-f0-9]{32}$/.test(message.operationId))) {
    sendResponse({ok: false, error: "INVALID_OPERATION_ID"}); return false;
  }
  const id = lookup ? message.operationId : identifier();
  if (pending.has(id)) { sendResponse(unknown("OPERATION_ALREADY_IN_FLIGHT")); return false; }
  pending.set(id, sendResponse);
  try {
    connect().postMessage({schema_version: 1, type: lookup ? "receipt_lookup" : "bridge_read", request_id: id,
      operation_id: id, capability: "read", arguments: lookup ? {} : {path: message.path}});
  } catch (_) {
    const callback = pending.get(id); pending.delete(id); if (callback) callback(unknown("POST_UNKNOWN_NO_RETRY"));
  }
  return true;
});
