"use strict";
// Any exact ChatGPT conversation may request registered BCT tools. The page
// never receives the Native Messaging port or bearer credential; BCT Core owns
// Work, capability, operation, receipt, UNKNOWN, and recovery authorization.
// Page content never receives the Native Messaging port or bearer credential.
const HOST = "com.bct.browser_bridge.prototype";
let port = null;
const pending = new Map();
const identifier = () => crypto.randomUUID().replace(/-/g, "");
const unknown = code => ({ok: false, outcome: "UNKNOWN", error: code});
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TOOL = /^[A-Za-z0-9_-]{1,128}$/;
const conversationKey = value => {
  try {
    const url = new URL(value);
    const match = url.origin === "https://chatgpt.com" && /^\/c\/([^/?#]+)\/?$/.exec(url.pathname);
    return match && UUID.test(match[1]) ? match[1].toLowerCase() : null;
  } catch (_) { return null; }
};
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
function nativeRequest(type, toolName, args, sendResponse) {
  const id = identifier();
  if (pending.has(id)) { sendResponse(unknown("REQUEST_ALREADY_IN_FLIGHT")); return false; }
  pending.set(id, sendResponse);
  try {
    connect().postMessage({schema_version: 2, type, request_id: id,
      tool_name: toolName, arguments: args});
  } catch (_) {
    const callback = pending.get(id); pending.delete(id);
    if (callback) callback(unknown("POST_UNKNOWN_NO_RETRY"));
  }
  return true;
}
function exactChatSender(sender, suppliedKey) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !sender.tab) return false;
  const key = conversationKey(sender.url);
  return !!key && key === conversationKey(sender.tab.url) && key === suppliedKey;
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "BCT_TOOL_LIST" && sender.id === chrome.runtime.id && !sender.tab) {
    return nativeRequest("tool_list", "", {}, sendResponse);
  }
  if (message?.type === "BCT_TOOL_CALL" && sender.id === chrome.runtime.id && !sender.tab) {
    if (!TOOL.test(message.toolName || "") || !message.arguments || typeof message.arguments !== "object" || Array.isArray(message.arguments)) {
      sendResponse({ok: false, outcome: "INPUT_DENIED", error: "INVALID_TOOL_CALL"}); return false;
    }
    return nativeRequest("tool_call", message.toolName, message.arguments, sendResponse);
  }
  if (message?.type === "BCT_CHAT_TOOL_CALL") {
    (async () => {
      if (!exactChatSender(sender, message.conversationKey)) {
        sendResponse({ok: false, outcome: "AUTH_DENIED", error: "CHAT_SENDER_DENIED"}); return;
      }
      if (!TOOL.test(message.toolName || "") || !message.arguments || typeof message.arguments !== "object" || Array.isArray(message.arguments)) {
        sendResponse({ok: false, outcome: "INPUT_DENIED", error: "INVALID_TOOL_CALL"}); return;
      }
      nativeRequest("tool_call", message.toolName, message.arguments, sendResponse);
    })().catch(() => sendResponse(unknown("CHAT_AUTH_UNKNOWN")));
    return true;
  }
  if (message?.type === "BCT_CHAT_STATUS_CURRENT" && sender.id === chrome.runtime.id && !sender.tab) {
    (async () => {
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      const key = conversationKey(tab?.url);
      if (!key) { sendResponse({ok: false, error: "ACTIVE_TAB_NOT_CHAT_CONVERSATION"}); return; }
      sendResponse({ok: true, enabled: true, automatic: true, tabId: tab.id, conversationKey: key});
    })().catch(() => sendResponse({ok: false, error: "ENABLE_FAILED"}));
    return true;
  }
  if (message?.type === "BCT_CHAT_STATUS" && sender.id === chrome.runtime.id && sender.frameId === 0 && sender.tab) {
    const key = conversationKey(sender.url);
    sendResponse(key && key === conversationKey(sender.tab.url)
      ? {enabled: true, automatic: true, tabId: sender.tab.id, conversationKey: key}
      : {enabled: false});
    return false;
  }
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
