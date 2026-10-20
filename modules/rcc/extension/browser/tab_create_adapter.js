(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabCreateAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity, options = {}) {
    if (typeof chromeApi?.tabs?.create !== 'function' || typeof chromeApi?.tabs?.get !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CREATE_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CREATE_CONTRACT_REQUIRED');
    }
    if (typeof identity?.isChatTab !== 'function'
        || typeof identity?.conversationKey !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CREATE_IDENTITY_REQUIRED');
    }
    const readyTimeoutMs = Number.isFinite(options.readyTimeoutMs)
      ? Math.max(0, Number(options.readyTimeoutMs)) : 8000;
    const pollIntervalMs = Number.isFinite(options.pollIntervalMs)
      ? Math.max(0, Number(options.pollIntervalMs)) : 50;
    const now = typeof options.now === 'function' ? options.now : Date.now;
    const sleep = typeof options.sleep === 'function' ? options.sleep
      : (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    function matches(tab, intent) {
      if (!tab || !identity.isChatTab(tab)) return false;
      if (intent.requestedWindowId !== null
          && Number(tab.windowId) !== intent.requestedWindowId) return false;
      const liveKey = String(identity.conversationKey(tab.url || '') || '');
      if (intent.conversationKey) return liveKey === intent.conversationKey;
      return !liveKey
        && /^https:\/\/(chatgpt\.com|chat\.openai\.com)\/?(?:[?#].*)?$/i.test(String(tab.url || ''));
    }

    async function createTab(value) {
      const intent = contract.normalizeIntent(value);
      if (intent.requestedWindowId !== null) {
        try {
          if (typeof chromeApi.windows?.get !== 'function') {
            throw new Error('TAB_CREATE_WINDOWS_API_REQUIRED');
          }
          const targetWindow = await chromeApi.windows.get(intent.requestedWindowId);
          if (!targetWindow || Number(targetWindow.id) !== intent.requestedWindowId) {
            throw new Error('TAB_CREATE_TARGET_WINDOW_MISMATCH');
          }
        } catch (error) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            error: String(error?.message || error || 'TAB_CREATE_TARGET_WINDOW_NOT_FOUND'),
          });
        }
      }

      let created = null;
      try {
        const createOptions = { url: intent.url, active: false };
        if (intent.requestedWindowId !== null) createOptions.windowId = intent.requestedWindowId;
        created = await chromeApi.tabs.create(createOptions);
      } catch (error) {
        return contract.receipt(intent, contract.STATES.CREATE_UNKNOWN, {
          error: String(error?.message || error || 'TAB_CREATE_EFFECT_UNKNOWN'),
        });
      }

      const deadline = now() + readyTimeoutMs;
      do {
        try {
          const tab = await chromeApi.tabs.get(Number(created?.id));
          if (matches(tab, intent)) {
            const state = intent.conversationKey
              ? contract.STATES.CREATED_CONFIRMED : contract.STATES.PENDING_UNBOUND;
            return contract.receipt(intent, state, { tab, createdObserved: true });
          }
        } catch (_) {}
        if (now() >= deadline) break;
        await sleep(pollIntervalMs);
      } while (true);

      return contract.receipt(intent, contract.STATES.CREATE_UNKNOWN, {
        tab: created,
        createdObserved: Number.isSafeInteger(Number(created?.id)),
        error: 'TAB_CREATE_POSTCONDITION_UNPROVEN',
      });
    }

    return Object.freeze({ createTab });
  }

  return Object.freeze({ create });
});
