(() => {
  'use strict';

  // Compatibility entrypoint only. The canonical Relay contract lives in
  // relay/contract.js; the background loader no longer loads this file.
  const api = typeof module !== 'undefined' && module.exports
    ? require('./relay/contract.js') : globalThis.RccRelayContract;
  if (!api) throw new Error('RCC_RELAY_CONTRACT_REQUIRED');
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  globalThis.SimpleRelayV0 = api;
})();
