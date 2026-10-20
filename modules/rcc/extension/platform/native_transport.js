(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccNativeTransport = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, options = {}) {
    if (typeof chromeApi?.runtime?.connectNative !== 'function') {
      throw new Error('RCC_NATIVE_TRANSPORT_API_REQUIRED');
    }
    const hostName = String(options.hostName || '');
    if (!hostName) throw new Error('RCC_NATIVE_TRANSPORT_HOST_REQUIRED');
    const reconnectDelayMs = Number(options.reconnectDelayMs || 3000);
    let port = null;
    let reconnectTimer = null;

    function post(message) {
      try {
        if (port) port.postMessage(message);
      } catch (_) {}
    }

    function scheduleReconnect() {
      if (reconnectTimer) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, reconnectDelayMs);
    }

    async function connect() {
      if (port) return;
      try {
        const next = chromeApi.runtime.connectNative(hostName);
        port = next;
        next.onMessage.addListener((message) => options.onMessage?.(message));
        next.onDisconnect.addListener(() => {
          if (port === next) port = null;
          scheduleReconnect();
        });
        await options.onConnected?.({ extensionId: chromeApi.runtime.id });
      } catch (_) {
        port = null;
        scheduleReconnect();
      }
    }

    return Object.freeze({ connect, post });
  }

  return Object.freeze({ create });
});
