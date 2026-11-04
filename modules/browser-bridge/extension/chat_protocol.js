"use strict";
// Data-only schema; authorization remains exclusively in the BCT Core.
(function (root) {
  const PREFIX = "[[BCT_LOCAL_READ_REQUEST]]";
  const SUFFIX = "[[/BCT_LOCAL_READ_REQUEST]]";
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const OP_ID = /^[0-9a-f]{32}$/;
  // One canonical two-field JSON shape; duplicate keys and extra properties are rejected.
  const READ_SHAPE = /^\{\s*"operation"\s*:\s*"read"\s*,\s*"path"\s*:\s*"(?:\\.|[^"\\])*"\s*\}$/;

  function conversationKey(value) {
    try {
      const url = new URL(value);
      if (url.origin !== "https://chatgpt.com") return null;
      const match = /^\/c\/([^/?#]+)\/?$/.exec(url.pathname);
      return match && UUID.test(match[1]) ? match[1].toLowerCase() : null;
    } catch (_) { return null; }
  }

  function parseReadMarker(text) {
    if (typeof text !== "string" || text.length > 4096) return null;
    const trimmed = text.trim();
    if (!trimmed.startsWith(PREFIX) || !trimmed.endsWith(SUFFIX)) return null;
    const body = trimmed.slice(PREFIX.length, -SUFFIX.length).trim();
    if (!READ_SHAPE.test(body) || body.length > 2048) return null;
    let value;
    try { value = JSON.parse(body); } catch (_) { return null; }
    if (typeof value.path !== "string" || value.path.length < 1 ||
        value.path.length > 1024 || value.path.includes("\0")) return null;
    return Object.freeze({operation: "read", path: value.path});
  }

  function validChatSender(sender, extensionId, suppliedKey) {
    if (!sender || sender.id !== extensionId || sender.frameId !== 0 || !sender.tab) return false;
    const fromSender = conversationKey(sender.url);
    const fromTab = conversationKey(sender.tab.url);
    return !!(fromSender && fromSender === fromTab && fromSender === suppliedKey);
  }

  function validOperationId(value) {
    return typeof value === "string" && OP_ID.test(value);
  }

  const api = Object.freeze({conversationKey, parseReadMarker, validChatSender, validOperationId});
  if (typeof module === "object" && module.exports) module.exports = api;
  root.BctBridgeChat = api;
})(typeof globalThis === "object" ? globalThis : this);
