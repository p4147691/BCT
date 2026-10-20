"use strict";

// Exact, user-initiated Chrome tab selection for the Monitor node list.
// The caller must already have resolved the native HWND. This adapter only
// selects the already-observed ChatGPT tab and focuses its existing window.
(function installMonitorTabFocusAdapter(root) {
  const RECEIPT_SCHEMA = "monitor.browser.tab-focus.receipt.v1";

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
      return match ? decodeURIComponent(match[1]) : "";
    } catch (_) {
      return "";
    }
  }

  function receipt(status, target, details = {}) {
    return Object.freeze({
      schema: RECEIPT_SCHEMA,
      ok: status === "APPLIED",
      status,
      tabId: target.tabId,
      windowId: target.windowId,
      conversationKey: target.conversationKey,
      ...details,
    });
  }

  function create(chromeApi) {
    if (!chromeApi?.tabs?.get || !chromeApi?.tabs?.update || !chromeApi?.windows?.get || !chromeApi?.windows?.update) {
      throw new Error("MONITOR_TAB_FOCUS_CHROME_API_REQUIRED");
    }

    async function focus(targetValue = {}) {
      const target = Object.freeze({
        tabId: integer(targetValue.tabId),
        windowId: integer(targetValue.windowId),
        conversationKey: String(targetValue.conversationKey || "").trim(),
      });
      if (target.tabId === null || target.windowId === null || !/^[0-9a-f-]{20,}$/i.test(target.conversationKey)) {
        return receipt("NOT_APPLIED", target, { error: "MONITOR_TAB_FOCUS_TARGET_INVALID" });
      }

      let before;
      try {
        before = await chromeApi.tabs.get(target.tabId);
      } catch (error) {
        return receipt("NOT_APPLIED", target, { error: error?.message || "MONITOR_TAB_FOCUS_TAB_NOT_FOUND" });
      }
      const observedKey = conversationKeyFromUrl(before?.url);
      if (integer(before?.windowId) !== target.windowId || observedKey !== target.conversationKey) {
        return receipt("NOT_APPLIED", target, {
          error: "MONITOR_TAB_FOCUS_IDENTITY_MISMATCH",
          observedWindowId: integer(before?.windowId),
          observedConversationKey: observedKey,
        });
      }

      let effectStarted = false;
      try {
        effectStarted = true;
        await chromeApi.tabs.update(target.tabId, { active: true });
        await chromeApi.windows.update(target.windowId, { focused: true });
        const [afterTab, afterWindow] = await Promise.all([
          chromeApi.tabs.get(target.tabId),
          chromeApi.windows.get(target.windowId),
        ]);
        if (
          integer(afterTab?.windowId) !== target.windowId ||
          conversationKeyFromUrl(afterTab?.url) !== target.conversationKey ||
          afterTab?.active !== true ||
          afterWindow?.focused !== true
        ) {
          return receipt("UNKNOWN", target, { error: "MONITOR_TAB_FOCUS_POSTCONDITION_FAILED" });
        }
        return receipt("APPLIED", target, { active: true, focused: true });
      } catch (error) {
        return receipt(effectStarted ? "UNKNOWN" : "NOT_APPLIED", target, {
          error: error?.message || "MONITOR_TAB_FOCUS_FAILED",
        });
      }
    }

    return Object.freeze({ focus });
  }

  root.MonitorTabFocusAdapter = Object.freeze({ create, conversationKeyFromUrl, RECEIPT_SCHEMA });
})(globalThis);
