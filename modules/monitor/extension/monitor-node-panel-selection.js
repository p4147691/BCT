// Monitor NodePanel selection state. UI projection only, never an RCC routing authority.
(() => {
  "use strict";
  function key(value) {
    const instanceId = String(value?.instanceId || "").trim();
    const sessionId = String(value?.sessionId || "").trim();
    const windowId = String(value?.windowId || "").trim();
    const tabId = String(value?.tabId || "").trim();
    if (!windowId || !tabId) return "";
    return instanceId && sessionId
      ? `${instanceId}:${sessionId}:${windowId}:${tabId}`
      : `tab:${windowId}:${tabId}`;
  }
  function create() {
    let selectedKey = "";
    return Object.freeze({
      key,
      get: () => selectedKey,
      set: next => (selectedKey = String(next || "").trim()),
      clear: () => (selectedKey = ""),
      matches: value => !!selectedKey && key(value) === selectedKey
    });
  }
  globalThis.MonitorNodePanelSelection = Object.freeze({ create });
})();
