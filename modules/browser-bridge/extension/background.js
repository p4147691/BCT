"use strict";
importScripts("chat_protocol.js");
const HOST = "com.bct.browser_bridge.prototype";
let port = null;
const pending = new Map();
const identifier = () => crypto.randomUUID().replace(/-/g, "");
const unknown = code => ({ok: false, outcome: "UNKNOWN", error: code});
const consentKey = (key, tabId) => "bct-chat-consent:" + key + ":" + tabId;

function connect() {
  if (port) return port;
  const current = chrome.runtime.connectNative(HOST);
  port = current;
  current.onMessage.addListener(reply => {
    const id = reply?.request_id;
    if (typeof id !== "string" || !pending.has(id)) return;
    const callback = pending.get(id);
    pending.delete(id);
    callback(reply);
  });
  current.onDisconnect.addListener(() => {
    if (port === current) port = null;
    for (const [id, callback] of pending) {
      pending.delete(id);
      callback(unknown("NATIVE_DISCONNECTED_NO_RETRY"));
    }
  });
  return current;
}
function nativeRequest(requestId, kind, args, respond) {
  if (pending.has(requestId)) return respond(unknown("OPERATION_ALREADY_IN_FLIGHT"));
  pending.set(requestId, respond);
  try {
    connect().postMessage({
      schema_version: 1, type: kind, request_id: requestId, operation_id: requestId,
      capability: "read", arguments: args
    });
  } catch (_) {
    const callback = pending.get(requestId);
    pending.delete(requestId);
    if (callback) callback(unknown("POST_UNKNOWN_NO_RETRY"));
  }
}
function validContentSender(message, sender) {
  return BctBridgeChat.validChatSender(sender, chrome.runtime.id, message?.conversationKey) &&
    Number.isInteger(sender.tab.id) && sender.tab.id >= 0;
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender?.id !== chrome.runtime.id) return false;

  if (message?.type === "BRIDGE_CHAT_STATUS") {
    if (Object.keys(message).sort().join(",") !== "conversationKey,type" ||
        !validContentSender(message, sender)) {
      sendResponse({enabled: false}); return false;
    }
    chrome.storage.session.get(consentKey(message.conversationKey, sender.tab.id))
      .then(flags => {
        const grantId = flags[consentKey(message.conversationKey, sender.tab.id)];
        sendResponse({
          enabled: BctBridgeChat.validOperationId(grantId),
          grantId: BctBridgeChat.validOperationId(grantId) ? grantId : null,
          tabId: sender.tab.id
        });
      }).catch(() => sendResponse({enabled: false}));
    return true;
  }

  if (message?.type === "BRIDGE_CHAT_READ") {
    if (Object.keys(message).sort().join(",") !== "conversationKey,grantId,path,requestId,type" ||
        !validContentSender(message, sender) ||
        !BctBridgeChat.validOperationId(message.grantId) ||
        !BctBridgeChat.validOperationId(message.requestId) ||
        typeof message.path !== "string" || message.path.length < 1 ||
        message.path.length > 1024 || message.path.includes("\0")) {
      sendResponse({ok: false, outcome: "INPUT_DENIED", error: "CHAT_REQUEST_DENIED"});
      return false;
    }
    const flag = consentKey(message.conversationKey, sender.tab.id);
    chrome.storage.session.get(flag).then(values => {
      if (values[flag] !== message.grantId) {
        sendResponse({ok: false, outcome: "INPUT_DENIED", error: "CHAT_GRANT_REVOKED"});
        return;
      }
      nativeRequest(message.requestId, "bridge_read", {path: message.path}, sendResponse);
    }).catch(() => sendResponse(unknown("CHAT_CONSENT_UNAVAILABLE")));
    return true;
  }

  if (!["READ_FIXTURE", "RECEIPT_LOOKUP"].includes(message?.type) ||
      sender.url !== chrome.runtime.getURL("popup.html") || sender.frameId !== 0) return false;
  const lookup = message.type === "RECEIPT_LOOKUP";
  if (!lookup && (typeof message.path !== "string" || !message.path || message.path.length > 1024)) {
    sendResponse({ok: false, error: "INVALID_PATH"}); return false;
  }
  if (lookup && !BctBridgeChat.validOperationId(message.operationId)) {
    sendResponse({ok: false, error: "INVALID_OPERATION_ID"}); return false;
  }
  const id = lookup ? message.operationId : identifier();
  nativeRequest(id, lookup ? "receipt_lookup" : "bridge_read",
    lookup ? {} : {path: message.path}, sendResponse);
  return true;
});
