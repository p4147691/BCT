(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccObservationGateway = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi) {
    if (!chromeApi?.tabs) throw new Error('RCC_OBSERVATION_GATEWAY_TABS_API_REQUIRED');
    return Object.freeze({
      registerTabListeners(handlers = {}) {
        chromeApi.tabs.onCreated?.addListener((tab) => handlers.onCreated?.(tab));
        chromeApi.tabs.onUpdated?.addListener((tabId, changeInfo, tab) =>
          handlers.onUpdated?.(tabId, changeInfo, tab));
        chromeApi.tabs.onRemoved?.addListener((tabId, removeInfo) =>
          handlers.onRemoved?.(tabId, removeInfo));
      },
    });
  }

  return Object.freeze({ create });
});
