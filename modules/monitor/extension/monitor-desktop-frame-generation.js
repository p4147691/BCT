// DesktopStage frame generation fences; owns only GUID-scoped and global epochs.
(() => {
  "use strict";
  function create() {
    let epoch = 0;
    const desktopEpochs = new Map();
    function generation(desktopId) {
      return `${epoch}.${Number(desktopEpochs.get(String(desktopId || "")) || 0)}`;
    }
    function invalidate(desktopIds = []) {
      const ids = new Set(desktopIds.filter(Boolean).map(String));
      if (!ids.size) {
        epoch += 1;
        desktopEpochs.clear();
      } else {
        for (const id of ids) desktopEpochs.set(id, Number(desktopEpochs.get(id) || 0) + 1);
      }
      return ids;
    }
    return Object.freeze({ generation, invalidate });
  }
  globalThis.MonitorDesktopFrameGeneration = Object.freeze({ create });
})();
