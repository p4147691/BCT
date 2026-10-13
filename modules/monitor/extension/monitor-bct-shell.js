"use strict";

// Small BCT-facing boundary for the Monitor header. Physical window truth stays
// in the Native Host; this module only reads BCT health and opens explicit UIs.
(function installMonitorBctShell(root) {
  const URLS = Object.freeze({
    health: "http://127.0.0.1:18790/health",
    monitorState: "http://127.0.0.1:18790/monitor/state",
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

    async function monitorState() {
      if (typeof fetcher !== "function") throw new Error("BCT_MONITOR_FETCH_UNAVAILABLE");
      const response = await fetcher(URLS.monitorState, { cache: "no-store" });
      if (!response?.ok) throw new Error(`BCT_MONITOR_HTTP_${Number(response?.status || 0)}`);
      const state = await response.json();
      if (state?.service?.status !== "OK" || state?.service?.ready !== true ||
          state?.service?.service !== "bct-core" || !Array.isArray(state?.rcc?.instances)) {
        throw new Error("BCT_MONITOR_CONTRACT_INVALID");
      }
      return state;
    }

    function windowNodes(state) {
      if (!Array.isArray(state?.rcc?.instances)) throw new Error("BCT_RCC_STATE_INVALID");
      const nodes = [];
      for (const instance of state.rcc.instances) {
        const instanceId = String(instance?.instance_id || "").trim();
        const instanceState = String(instance?.state || "UNKNOWN").trim().toUpperCase();
        for (const tab of Array.isArray(instance?.tabs) ? instance.tabs : []) {
          const tabId = Number(tab?.tab_id || 0);
          const windowId = Number(tab?.window_id || 0);
          if (!Number.isSafeInteger(tabId) || tabId <= 0 ||
              !Number.isSafeInteger(windowId) || windowId <= 0) continue;
          const url = String(tab?.url || "").trim();
          const conversationMatch = url.match(/\/c\/([a-z0-9-]+)/i);
          nodes.push(Object.freeze({
            instanceId,
            instanceState,
            tabId,
            windowId,
            title: String(tab?.title || "ChatGPT").trim() || "ChatGPT",
            url,
            conversationKey: conversationMatch?.[1] || "",
            presence: String(tab?.presence || "UNKNOWN").trim().toUpperCase(),
            active: tab?.active === true,
            generating: tab?.generating === true,
          }));
        }
      }
      nodes.sort((left, right) =>
        left.windowId - right.windowId || left.tabId - right.tabId ||
        left.instanceId.localeCompare(right.instanceId));
      return Object.freeze(nodes);
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
      monitorState,
      windowNodes,
      openStatus: () => open(URLS.status, { width: 1120, height: 820 }),
      openLocalLlm: () => open(URLS.localLlm, { width: 1200, height: 820 }),
    });
  }

  root.MonitorBctShell = Object.freeze({ URLS, create });
})(globalThis);
