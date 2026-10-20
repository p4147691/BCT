(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserWindowCreateAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity, options = {}) {
    if (typeof chromeApi?.windows?.create !== 'function'
        || typeof chromeApi?.windows?.get !== 'function'
        || typeof chromeApi?.tabs?.query !== 'function'
        || typeof chromeApi?.tabs?.get !== 'function') {
      throw new Error('RCC_BROWSER_WINDOW_CREATE_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') {
      throw new Error('RCC_BROWSER_WINDOW_CREATE_CONTRACT_REQUIRED');
    }
    if (typeof identity?.isChatTab !== 'function'
        || typeof identity?.conversationKey !== 'function') {
      throw new Error('RCC_BROWSER_WINDOW_CREATE_IDENTITY_REQUIRED');
    }
    const readyTimeoutMs = Number.isFinite(options.readyTimeoutMs)
      ? Math.max(0, Number(options.readyTimeoutMs)) : 8000;
    const pollIntervalMs = Number.isFinite(options.pollIntervalMs)
      ? Math.max(0, Number(options.pollIntervalMs)) : 50;
    const now = typeof options.now === 'function' ? options.now : Date.now;
    const sleep = typeof options.sleep === 'function' ? options.sleep
      : (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    function isBlankChatTab(tab, windowId) {
      if (!tab || Number(tab.windowId) !== windowId || !identity.isChatTab(tab)) return false;
      const url = String(tab.url || '');
      return !identity.conversationKey(url)
        && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(url);
    }

    async function createWindow(value) {
      const intent = contract.normalizeIntent(value);
      let created = null;
      try {
        created = await chromeApi.windows.create({
          url: intent.url,
          type: intent.type,
          focused: intent.focused,
        });
      } catch (_) {
        return contract.receipt(intent, contract.STATES.CREATE_UNKNOWN);
      }

      const windowId = Number(created?.id);
      let candidate = Array.isArray(created?.tabs)
        ? created.tabs.find((tab) => Number.isSafeInteger(Number(tab?.id))) || null
        : null;
      try {
        if (!Number.isSafeInteger(windowId) || windowId < 1) {
          throw new Error('WINDOW_CREATE_IDENTITY_MISSING');
        }
        if (!candidate) {
          const tabs = await chromeApi.tabs.query({ windowId });
          candidate = tabs.find((tab) => Number.isSafeInteger(Number(tab?.id))) || null;
        }
        const tabId = Number(candidate?.id);
        if (!Number.isSafeInteger(tabId) || tabId < 1) {
          throw new Error('WINDOW_CREATE_TAB_IDENTITY_MISSING');
        }

        const deadline = now() + readyTimeoutMs;
        do {
          try {
            const liveWindow = await chromeApi.windows.get(windowId);
            const liveTab = await chromeApi.tabs.get(tabId);
            if (Number(liveWindow?.id) === windowId && isBlankChatTab(liveTab, windowId)) {
              return contract.receipt(intent, contract.STATES.PENDING_UNBOUND, {
                window: liveWindow,
                tab: liveTab,
                createdObserved: true,
              });
            }
          } catch (_) {}
          if (now() >= deadline) break;
          await sleep(pollIntervalMs);
        } while (true);
      } catch (_) {}

      return contract.receipt(intent, contract.STATES.CREATE_UNKNOWN, {
        window: created,
        tab: candidate,
        createdObserved: true,
      });
    }

    return Object.freeze({ createWindow });
  }

  return Object.freeze({ create });
});
