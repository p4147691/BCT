// Diagnostics refresh view state and rendering; no direct Native, BCT, Chrome or ACT access.
(() => {
  "use strict";
  const controllers = new WeakMap();

  function create({ button, getActiveView, ports }) {
    if (!button || typeof getActiveView !== "function" ||
        !ports || ["refreshOverview", "refreshAct", "actStatus", "autoStatus",
          "renderMonitor", "show"].some(key => typeof ports[key] !== "function")) {
      throw new TypeError("Diagnostics requires a button, view reader and typed injected ports");
    }

    const previous = controllers.get(button);
    if (previous) return previous;
    let refreshing = false;

    async function refresh() {
      if (refreshing || button.disabled) return false;
      const selected = getActiveView() || {};
      const view = String(selected.view || "overview");
      const label = String(selected.label || view);
      refreshing = true;
      button.disabled = true;
      button.classList.add("is-refreshing");
      try {
        if (view === "overview") {
          await ports.refreshOverview();
          ports.show(`종합 관제\n${ports.actStatus()} · ${ports.autoStatus()}\n현재 관제 상태를 다시 확인했습니다.`);
        } else if (view === "act") {
          await ports.refreshAct();
          ports.show(`ACT 관제\n${ports.actStatus()}`);
        } else if (view === "monitor") {
          ports.show(ports.renderMonitor());
        } else {
          ports.show(`${label} 관제 · 세부 수집기 연결 전`);
        }
        return true;
      } finally {
        refreshing = false;
        button.disabled = false;
        button.classList.remove("is-refreshing");
      }
    }

    const controller = Object.freeze({ refresh, destroy() { controllers.delete(button); } });
    controllers.set(button, controller);
    return controller;
  }

  globalThis.MonitorDiagnosticsViewFeature = Object.freeze({ create });
})();
