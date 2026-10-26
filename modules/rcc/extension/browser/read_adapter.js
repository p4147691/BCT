(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserReadAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  // This adapter is intentionally limited to observation.  Commands that can
  // create, move, close, reload, focus, or submit to a tab stay outside this
  // boundary until they have their own explicit, receipt-bearing adapter.
  function create(chromeApi, chatUrls) {
    if (!chromeApi?.tabs) {
      throw new Error('RCC_BROWSER_READ_ADAPTER_CHROME_API_REQUIRED');
    }
    const patterns = Array.isArray(chatUrls) ? chatUrls.slice() : [];
    if (!patterns.length) throw new Error('RCC_BROWSER_READ_ADAPTER_CHAT_URLS_REQUIRED');

    function isChatTab(tab) {
      return /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(String(tab?.url || ''));
    }

    return Object.freeze({
      queryChatTabs: async () => (await chromeApi.tabs.query({ url: patterns })).filter(isChatTab),
      isChatTab,
      publicTab: (tab) => ({
        // Chrome calls this field `id`; RCC's public protocol calls the same
        // ephemeral browser identifier `tabId`.  Do not expose both spellings:
        // consumers must never have to guess which one identifies a tab.
        tabId: tab?.id,
        windowId: tab?.windowId ?? null,
        index: Number.isInteger(tab?.index) ? tab.index : null,
        title: tab?.title || '',
        url: tab?.url || '',
      }),
      getWindow: (windowId) => {
        if (typeof chromeApi.windows?.get !== 'function') {
          throw new Error('RCC_BROWSER_READ_ADAPTER_WINDOWS_API_REQUIRED');
        }
        return chromeApi.windows.get(windowId);
      },
      probeActivity: (tabId) => chromeApi.tabs.sendMessage(tabId, { type: 'relay:activityProbe' }),
    });
  }

  return Object.freeze({ create });
});
