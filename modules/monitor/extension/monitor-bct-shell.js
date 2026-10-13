"use strict";

// Small BCT-facing boundary for the Monitor header. Physical window truth stays
// in the Native Host; this module only reads BCT health and opens explicit UIs.
(function installMonitorBctShell(root) {
  const URLS = Object.freeze({
    health: "http://127.0.0.1:18790/health",
    status: "http://127.0.0.1:18790/monitor",
    localLlm: "http://127.0.0.1:18790/monitor#local-llm",
  });

  function create(options = {}) {
    const fetcher = options.fetcher || root.fetch?.bind(root);
    const windowsApi = options.windowsApi || root.chrome?.windows;

    async function health() {
      if (typeof fetcher !== "function") throw new Error("BCT_HEALTH_FETCH_UNAVAILABLE");
      const response = await fetcher(URLS.health, { cache: "no-store" });
      if (!response?.ok) throw new Error(`BCT_HEALTH_HTTP_${Number(response?.status || 0)}`);
      const state = await response.json();
      if (state?.status !== "OK" || state?.ready !== true || state?.service !== "bct-core") {
        throw new Error("BCT_HEALTH_CONTRACT_INVALID");
      }
      return Object.freeze({
        status: state.status,
        ready: state.ready,
        service: state.service,
        releaseSha: String(state.release_sha || ""),
        generation: Number(state.generation || 0),
        pid: Number(state.pid || 0),
      });
    }

    async function open(url, size) {
      if (!windowsApi?.create) throw new Error("BCT_WINDOW_CREATE_UNAVAILABLE");
      return windowsApi.create({
        url,
        type: "popup",
        width: size.width,
        height: size.height,
        focused: true,
      });
    }

    return Object.freeze({
      health,
      openStatus: () => open(URLS.status, { width: 1120, height: 820 }),
      openLocalLlm: () => open(URLS.localLlm, { width: 1200, height: 820 }),
    });
  }

  root.MonitorBctShell = Object.freeze({ URLS, create });
})(globalThis);
