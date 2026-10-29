// NodePanel-only interaction state. No BCT/RCC authority and no DOM access.
(() => {
  "use strict";
  function create() {
    const collapsed = new Set();
    let suppressedKey = "", suppressScopeUntil = 0;
    return Object.freeze({
      isCollapsed: key => collapsed.has(String(key || "")),
      toggleCollapsed(key) {
        const id = String(key || "");
        if (collapsed.has(id)) { collapsed.delete(id); return false; }
        collapsed.add(id); return true;
      },
      getSuppressedKey: () => suppressedKey,
      setSuppressedKey: key => { suppressedKey = String(key || ""); },
      clearSuppressedKeyIf(key) {
        if (suppressedKey !== String(key || "")) return false;
        suppressedKey = ""; return true;
      },
      consumeSuppressedKey(key) {
        if (!suppressedKey || suppressedKey !== String(key || "")) return false;
        suppressedKey = ""; return true;
      },
      setScopeSuppressedUntil: epochMs => { suppressScopeUntil = Number(epochMs) || 0; },
      isScopeSuppressed: now => Number(now) < suppressScopeUntil
    });
  }
  globalThis.MonitorNodePanelInteractionState = Object.freeze({ create });
})();
