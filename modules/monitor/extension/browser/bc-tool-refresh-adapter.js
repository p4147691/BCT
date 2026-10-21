(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.MonitorBcToolRefreshAdapter = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  function create(chromeApi) {
    if (!chromeApi?.tabs?.get || !chromeApi?.tabs?.reload) {
      throw new Error("BC_REFRESH_CHROME_TABS_API_REQUIRED");
    }

    async function refreshExactChatTab(target) {
      const tabId = Number(target?.tabId);
      const windowId = Number(target?.windowId);
      const conversationKey = String(target?.conversationKey || "").trim().toLowerCase();
      if (!Number.isInteger(tabId) || tabId < 0 || !Number.isInteger(windowId) || windowId < 0 ||
          !/^[0-9a-f-]{20,}$/i.test(conversationKey)) {
        throw new Error("BC_REFRESH_EXACT_CHAT_IDENTITY_REQUIRED");
      }
      const tab = await chromeApi.tabs.get(tabId);
      const url = String(tab?.url || "");
      const match = url.match(/^https:\/\/(?:chatgpt\.com|chat\.openai\.com)\/c\/([0-9a-f-]+)/i);
      if (Number(tab?.windowId) !== windowId || String(match?.[1] || "").toLowerCase() !== conversationKey) {
        throw new Error("BC_REFRESH_CHAT_IDENTITY_CHANGED");
      }
      await chromeApi.tabs.reload(tabId, { bypassCache:false });
      return Object.freeze({ ok:true, tabId, windowId, conversationKey, reloaded:true });
    }

    return Object.freeze({ refreshExactChatTab });
  }

  return Object.freeze({ create });
});
