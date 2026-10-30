// Monitor desktop-strip management modes. Owns state; storage/notifications are injected.
(() => {
  "use strict";

  const allowed = new Set(["OBSERVE_ONLY", "MANAGED", "PROTECTED"]);
  const clean = value => String(value || "").toUpperCase();
  const normalize = input => {
    const result = {};
    if (!input || typeof input !== "object" || Array.isArray(input)) return result;
    for (const [key, mode] of Object.entries(input)) {
      const id = String(key || "").trim(), value = clean(mode);
      if (id && allowed.has(value)) result[id] = value;
    }
    return result;
  };

  function create({ persist } = {}) {
    if (typeof persist !== "function") throw new TypeError("Desktop modes require a persistence port");
    let modes = {};
    function get(id) {
      return modes[String(id || "").trim()] || "OBSERVE_ONLY";
    }
    function hydrate(snapshot) {
      modes = normalize(snapshot);
      return snapshotModes();
    }
    function snapshotModes() {
      return Object.freeze({ ...modes });
    }
    function next(value) {
      const mode = clean(value);
      return mode === "OBSERVE_ONLY" ? "MANAGED" : mode === "MANAGED" ? "PROTECTED" : "OBSERVE_ONLY";
    }
    function set(desktopId, mode) {
      const id = String(desktopId || "").trim(), value = clean(mode);
      if (!id || !allowed.has(value) || get(id) === value) return false;
      modes = { ...modes, [id]: value };
      persist(snapshotModes());
      return true;
    }
    return Object.freeze({ get, hydrate, snapshot: snapshotModes, next, set });
  }

  globalThis.MonitorDesktopModeController = Object.freeze({ create });
})();
