(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccLifecycle = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi) {
    if (!chromeApi?.runtime) throw new Error('RCC_LIFECYCLE_RUNTIME_API_REQUIRED');
    const extensionId = String(chromeApi.runtime.id || '');

    function runtimeSenderKind(sender) {
      if (!extensionId || String(sender?.id || '') !== extensionId) return 'UNTRUSTED';
      const tabId = Number(sender?.tab?.id);
      if (Number.isSafeInteger(tabId) && tabId > 0) {
        const url = String(sender?.url || sender?.tab?.url || '');
        const topFrame = Number(sender?.frameId) === 0;
        return topFrame && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(url)
          ? 'CHAT_CONTENT' : 'UNTRUSTED';
      }
      const url = String(sender?.url || sender?.origin || '');
      return (url === `chrome-extension://${extensionId}`
        || url.startsWith(`chrome-extension://${extensionId}/`))
        ? 'EXTENSION_PAGE' : 'UNTRUSTED';
    }

    return Object.freeze({
      runtimeSenderKind,
      registerRuntimeMessage(handler) {
        chromeApi.runtime.onMessage.addListener((message, sender, sendResponse) =>
          handler(message, sender, sendResponse));
      },
      registerStartup(onStart) {
        chromeApi.runtime.onStartup.addListener(onStart);
        chromeApi.runtime.onInstalled.addListener(onStart);
      },
      reload(delayMs = 50) {
        setTimeout(() => chromeApi.runtime.reload(), delayMs);
      },
    });
  }

  return Object.freeze({ create });
});
