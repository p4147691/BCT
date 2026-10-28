// Ordered HWND lifecycle event controller; all queue state is private.
(() => {
  "use strict";

  function create({ handle, onError = () => {} } = {}) {
    if (typeof handle !== "function" || typeof onError !== "function") {
      throw new TypeError("Window lifecycle requires injected handle/onError ports");
    }
    const pending = new Map();
    let draining = false;
    let disposed = false;

    async function drain() {
      if (draining || disposed) return;
      draining = true;
      try {
        while (!disposed && pending.size) {
          const first = pending.entries().next().value;
          if (!first) break;
          const [hwnd, event] = first;
          pending.delete(hwnd);
          try {
            await handle(event);
          } catch (error) {
            onError(error, event);
          }
        }
      } finally {
        draining = false;
        if (!disposed && pending.size) void drain();
      }
    }

    function schedule(event) {
      if (disposed) return false;
      const hwnd = String(event?.hwnd || "").trim();
      if (!/^\d+$/.test(hwnd) || hwnd === "0") return false;
      pending.set(hwnd, event);
      if (!draining) void drain();
      return true;
    }

    function destroy() {
      disposed = true;
      pending.clear();
    }

    return Object.freeze({ schedule, drain, destroy });
  }

  globalThis.MonitorWindowLifecycleQueue = Object.freeze({ create });
})();
