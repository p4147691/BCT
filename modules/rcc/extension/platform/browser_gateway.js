(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserGateway = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, options = {}) {
    if (!chromeApi?.tabs || !chromeApi?.scripting) {
      throw new Error('RCC_BROWSER_GATEWAY_CHROME_API_REQUIRED');
    }
    const chatUrls = Array.isArray(options.chatUrls) ? options.chatUrls.slice() : [];
    const receiverFiles = Array.isArray(options.receiverFiles) ? options.receiverFiles.slice() : [];
    if (!chatUrls.length || !receiverFiles.length) {
      throw new Error('RCC_BROWSER_GATEWAY_CONFIGURATION_REQUIRED');
    }

    function isChatTab(tab) {
      return /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(String(tab?.url || ''));
    }

    function isMissingReceiver(error) {
      return /Receiving end does not exist|Could not establish connection/i.test(
        String(error?.message || error || '')
      );
    }

    async function injectReceiver(tabId) {
      const alreadyReady = await chromeApi.scripting.executeScript({
        target: { tabId },
        func: () => globalThis.__RCC_RELAY_RECEIVER_READY__ === true,
      });
      if (alreadyReady?.[0]?.result === true) return false;
      await chromeApi.scripting.executeScript({ target: { tabId }, files: receiverFiles });
      return true;
    }

    async function sendWithReceiver(tabId, message) {
      try {
        return await chromeApi.tabs.sendMessage(tabId, message);
      } catch (error) {
        if (!isMissingReceiver(error)) throw error;
        await injectReceiver(tabId);
        await new Promise((resolve) => setTimeout(resolve, 100));
        return chromeApi.tabs.sendMessage(tabId, message);
      }
    }

    return Object.freeze({
      queryChatTabs: async () => (await chromeApi.tabs.query({ url: chatUrls })).filter(isChatTab),
      isChatTab,
      publicTab: (tab) => ({
        id: tab?.id,
        windowId: tab?.windowId ?? null,
        index: Number.isInteger(tab?.index) ? tab.index : null,
        title: tab?.title || '',
        url: tab?.url || '',
      }),
      getExactTab: (tabId) => chromeApi.tabs.get(tabId),
      getWindow: (windowId) => {
        if (typeof chromeApi.windows?.get !== 'function') {
          throw new Error('RCC_BROWSER_GATEWAY_WINDOWS_API_REQUIRED');
        }
        return chromeApi.windows.get(windowId);
      },
      sendMessage: (tabId, message) => chromeApi.tabs.sendMessage(tabId, message),
      sendWithReceiver,
      executeScript: (spec) => chromeApi.scripting.executeScript(spec),
      probeActivity: (tabId) => chromeApi.tabs.sendMessage(tabId, { type: 'relay:activityProbe' }),
    });
  }

  return Object.freeze({ create });
});
