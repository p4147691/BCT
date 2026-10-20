(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccLifecycle = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi) {
    if (!chromeApi?.runtime) throw new Error('RCC_LIFECYCLE_RUNTIME_API_REQUIRED');
    return Object.freeze({
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
