(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.MonitorTabCloseAdapter = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const RECEIPT_SCHEMA = "monitor.browser.tab-close.receipt.v1";

  function integer(value) {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
  }

  function conversationKeyFromUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:") return "";
      if (url.hostname !== "chatgpt.com" && url.hostname !== "chat.openai.com") return "";
      const match = url.pathname.match(/^\/c\/([^/?#]+)\/?$/i);
      return match ? decodeURIComponent(match[1]).trim().toLowerCase() : "";
    } catch (_) {
      return "";
    }
  }

  function receipt(status, target, details = {}) {
    return Object.freeze({
      schema: RECEIPT_SCHEMA,
      ok: status === "CLOSED",
      status,
      tabId: target.tabId,
      windowId: target.windowId,
      conversationKey: target.conversationKey,
      ...details,
    });
  }

  function create(chromeApi) {
    if (!chromeApi?.tabs?.get || !chromeApi?.tabs?.remove) {
      throw new Error("MONITOR_TAB_CLOSE_CHROME_API_REQUIRED");
    }

    async function close(targetValue = {}) {
      const target = Object.freeze({
        tabId: integer(targetValue.tabId),
        windowId: integer(targetValue.windowId),
        conversationKey: String(targetValue.conversationKey || "").trim().toLowerCase(),
      });
      if (target.tabId === null || target.windowId === null ||
          !/^[0-9a-f-]{20,}$/i.test(target.conversationKey)) {
        return receipt("NOT_APPLIED", target, { error: "MONITOR_TAB_CLOSE_TARGET_INVALID" });
      }

      let before;
      try {
        before = await chromeApi.tabs.get(target.tabId);
      } catch (error) {
        return receipt("NOT_APPLIED", target, {
          error: error?.message || "MONITOR_TAB_CLOSE_TAB_NOT_FOUND",
        });
      }
      const observedWindowId = integer(before?.windowId);
      const observedConversationKey = conversationKeyFromUrl(before?.url);
      if (observedWindowId !== target.windowId || observedConversationKey !== target.conversationKey) {
        return receipt("NOT_APPLIED", target, {
          error: "MONITOR_TAB_CLOSE_IDENTITY_MISMATCH",
          observedWindowId,
          observedConversationKey,
        });
      }

      try {
        await chromeApi.tabs.remove(target.tabId);
      } catch (error) {
        return receipt("UNKNOWN", target, {
          error: error?.message || "MONITOR_TAB_CLOSE_EFFECT_UNCONFIRMED",
        });
      }

      try {
        const stillOpen = await chromeApi.tabs.get(target.tabId);
        if (stillOpen) {
          return receipt("UNKNOWN", target, { error: "MONITOR_TAB_CLOSE_POSTCONDITION_FAILED" });
        }
      } catch (_) {
        return receipt("CLOSED", target, { verified: true, closed: true });
      }
      return receipt("UNKNOWN", target, { error: "MONITOR_TAB_CLOSE_POSTCONDITION_FAILED" });
    }

    return Object.freeze({ close });
  }

  return Object.freeze({ create, conversationKeyFromUrl, RECEIPT_SCHEMA });
});
