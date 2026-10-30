// Monitor Recovery: bounded desktop undo session. Only owns private stack/expiry.
(() => {
  "use strict";
  function create({ maxEntries, ttlMs } = {}) {
    if (!Number.isInteger(maxEntries) || maxEntries <= 0 || !Number.isFinite(ttlMs) || ttlMs < 0) {
      throw new TypeError("Desktop undo requires positive max entries and nonnegative TTL");
    }
    const stack = [];
    let expiresAt = 0;
    function resetExpiry(now) {
      expiresAt = stack.length ? now + ttlMs : 0;
    }
    function push(snapshot, now) {
      stack.push({ ...snapshot });
      while (stack.length > maxEntries) stack.shift();
      resetExpiry(now);
    }
    function pop(now) {
      if (stack.length) stack.pop();
      resetExpiry(now);
    }
    function expire(now) {
      if (!stack.length || !expiresAt || now < expiresAt) return false;
      stack.length = 0;
      expiresAt = 0;
      return true;
    }
    function peek(now) {
      expire(now);
      return stack[stack.length - 1] || null;
    }
    function remainingMs(now) {
      return Math.max(0, expiresAt - now);
    }
    return Object.freeze({ push, pop, expire, peek, resetExpiry, remainingMs });
  }
  globalThis.MonitorRecoveryUndoSession = Object.freeze({ create });
})();
