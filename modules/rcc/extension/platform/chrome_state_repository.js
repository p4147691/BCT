(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccChromeStateRepository = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, randomUUID) {
    if (!chromeApi?.storage?.local || !chromeApi?.storage?.session) {
      throw new Error('RCC_STATE_REPOSITORY_STORAGE_API_REQUIRED');
    }
    if (typeof randomUUID !== 'function') {
      throw new Error('RCC_STATE_REPOSITORY_UUID_FACTORY_REQUIRED');
    }

    async function getOrCreateSessionId(key) {
      try {
        const data = await chromeApi.storage.session.get([key]);
        let value = String(data?.[key] || '').trim();
        if (!/^[a-f0-9]{32}$/i.test(value)) {
          value = randomUUID().replaceAll('-', '');
          await chromeApi.storage.session.set({ [key]: value });
        }
        return value;
      } catch (_) {
        return randomUUID().replaceAll('-', '');
      }
    }

    return Object.freeze({
      getLocal: (keys) => chromeApi.storage.local.get(keys),
      setLocal: (patch) => chromeApi.storage.local.set(patch),
      getOrCreateSessionId,
    });
  }

  return Object.freeze({ create });
});
