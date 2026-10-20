(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabCloseAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity) {
    if (typeof chromeApi?.tabs?.get !== 'function'
        || typeof chromeApi?.tabs?.remove !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CLOSE_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CLOSE_CONTRACT_REQUIRED');
    }
    if (typeof identity?.isChatTab !== 'function'
        || typeof identity?.conversationKey !== 'function') {
      throw new Error('RCC_BROWSER_TAB_CLOSE_IDENTITY_REQUIRED');
    }

    function identityMatches(tab, intent) {
      return !!tab
        && Number(tab.id) === intent.tabId
        && (intent.expectedWindowId === null
          || Number(tab.windowId) === intent.expectedWindowId)
        && identity.isChatTab(tab)
        && String(identity.conversationKey(tab.url || '') || '') === intent.conversationKey;
    }

    function provesAbsence(error) {
      const message = String(error?.message || error || '');
      return /no tab with id|invalid tab id|tab (?:was )?not found/i.test(message);
    }

    async function closeTab(value) {
      const intent = contract.normalizeIntent(value);
      let before = null;
      try {
        before = await chromeApi.tabs.get(intent.tabId);
        if (!identityMatches(before, intent)) {
          return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
            before, error: 'TAB_CLOSE_TARGET_IDENTITY_MISMATCH',
          });
        }
      } catch (error) {
        return contract.receipt(intent, contract.STATES.NOT_APPLIED, {
          before, error: String(error?.message || error || 'TAB_CLOSE_PRECHECK_FAILED'),
        });
      }

      try {
        await chromeApi.tabs.remove(intent.tabId);
      } catch (error) {
        return contract.receipt(intent, contract.STATES.CLOSE_UNKNOWN, {
          before, error: String(error?.message || error || 'TAB_CLOSE_EFFECT_UNKNOWN'),
        });
      }

      try {
        const after = await chromeApi.tabs.get(intent.tabId);
        return contract.receipt(intent, contract.STATES.CLOSE_UNKNOWN, {
          before, after, error: 'TAB_CLOSE_POSTCONDITION_UNPROVEN',
        });
      } catch (error) {
        if (provesAbsence(error)) {
          return contract.receipt(intent, contract.STATES.CLOSED_CONFIRMED, { before });
        }
        return contract.receipt(intent, contract.STATES.CLOSE_UNKNOWN, {
          before, error: String(error?.message || error || 'TAB_CLOSE_POSTCHECK_FAILED'),
        });
      }
    }

    return Object.freeze({ closeTab });
  }

  return Object.freeze({ create });
});
