(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabReloadAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity, receiver, options = {}) {
    if (typeof chromeApi?.tabs?.get !== 'function'
        || typeof chromeApi?.tabs?.reload !== 'function'
        || typeof chromeApi?.tabs?.onUpdated?.addListener !== 'function'
        || typeof chromeApi?.tabs?.onUpdated?.removeListener !== 'function') {
      throw new Error('RCC_BROWSER_TAB_RELOAD_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') {
      throw new Error('RCC_BROWSER_TAB_RELOAD_CONTRACT_REQUIRED');
    }
    if (typeof identity?.isChatTab !== 'function'
        || typeof identity?.conversationKey !== 'function') {
      throw new Error('RCC_BROWSER_TAB_RELOAD_IDENTITY_REQUIRED');
    }
    if (typeof receiver?.probe !== 'function') {
      throw new Error('RCC_BROWSER_TAB_RELOAD_RECEIVER_REQUIRED');
    }
    const navigationTimeoutMs = Number.isFinite(options.navigationTimeoutMs)
      ? Math.max(0, Number(options.navigationTimeoutMs)) : 15000;
    const receiverTimeoutMs = Number.isFinite(options.receiverTimeoutMs)
      ? Math.max(0, Number(options.receiverTimeoutMs)) : 8000;
    const pollIntervalMs = Number.isFinite(options.pollIntervalMs)
      ? Math.max(0, Number(options.pollIntervalMs)) : 50;
    const now = typeof options.now === 'function' ? options.now : Date.now;
    const sleep = typeof options.sleep === 'function' ? options.sleep
      : (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    function identityMatches(tab, intent) {
      return !!tab
        && Number(tab.id) === intent.tabId
        && identity.isChatTab(tab)
        && String(identity.conversationKey(tab.url || '') || '') === intent.conversationKey;
    }

    function observeNavigation(tabId) {
      let listener = null;
      let timer = null;
      let settled = false;
      let resolvePromise;
      const finish = (completed) => {
        if (settled) return;
        settled = true;
        if (timer !== null) clearTimeout(timer);
        if (listener) chromeApi.tabs.onUpdated.removeListener(listener);
        resolvePromise(completed);
      };
      const promise = new Promise((resolve) => {
        resolvePromise = resolve;
        listener = (updatedTabId, changeInfo) => {
          if (Number(updatedTabId) === tabId && changeInfo?.status === 'complete') finish(true);
        };
        chromeApi.tabs.onUpdated.addListener(listener);
        timer = setTimeout(() => finish(false), navigationTimeoutMs);
      });
      return Object.freeze({ promise, cancel: () => finish(false) });
    }

    async function reloadTab(value) {
      const intent = contract.normalizeIntent(value);
      let before = null;
      try {
        before = await chromeApi.tabs.get(intent.tabId);
        if (!identityMatches(before, intent)) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            before, error: 'TAB_RELOAD_TARGET_IDENTITY_MISMATCH',
          });
        }
      } catch (error) {
        return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
          before, error: String(error?.message || error || 'TAB_RELOAD_PRECHECK_FAILED'),
        });
      }

      const navigation = observeNavigation(intent.tabId);
      try {
        await chromeApi.tabs.reload(intent.tabId);
      } catch (error) {
        navigation.cancel();
        return contract.receipt(intent, contract.STATES.RELOAD_UNKNOWN, {
          before, error: String(error?.message || error || 'TAB_RELOAD_EFFECT_UNKNOWN'),
        });
      }

      const navigationCompleted = await navigation.promise;
      if (!navigationCompleted) {
        return contract.receipt(intent, contract.STATES.RELOAD_UNKNOWN, {
          before, error: 'TAB_RELOAD_NAVIGATION_UNPROVEN',
        });
      }

      const deadline = now() + receiverTimeoutMs;
      do {
        let after = null;
        try {
          after = await chromeApi.tabs.get(intent.tabId);
          if (identityMatches(after, intent)) {
            const probe = await receiver.probe(intent.tabId);
            if (probe?.ok === true) {
              return contract.receipt(intent, contract.STATES.RELOADED_CONFIRMED, {
                before, after, navigationCompleted: true, receiverReady: true,
              });
            }
          }
        } catch (_) {}
        if (now() >= deadline) break;
        await sleep(pollIntervalMs);
      } while (true);

      return contract.receipt(intent, contract.STATES.RELOAD_UNKNOWN, {
        before, navigationCompleted: true, error: 'TAB_RELOAD_POSTCONDITION_UNPROVEN',
      });
    }

    return Object.freeze({ reloadTab });
  }

  return Object.freeze({ create });
});
