// Monitor NodePanel conversation projection cache; BCT/RCC remains identity authority.
(() => {
  "use strict";
  function create({ build } = {}) {
    if (typeof build !== "function") throw new TypeError("Conversation projection requires injected build port");
    let cache = new WeakMap();
    function project(state) {
      if (!state || typeof state !== "object") return build(state);
      if (cache.has(state)) return cache.get(state);
      const result = build(state);
      cache.set(state, result);
      return result;
    }
    function reset() { cache = new WeakMap(); }
    return Object.freeze({ project, reset });
  }
  globalThis.MonitorConversationProjectionController = Object.freeze({ create });
})();
