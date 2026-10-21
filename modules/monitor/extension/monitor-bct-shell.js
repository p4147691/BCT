"use strict";

// Small BCT-facing boundary for the Monitor header. Physical window truth stays
// in the Native Host; this module only reads BCT health and opens explicit UIs.
(function installMonitorBctShell(root) {
  const URLS = Object.freeze({
    health: "http://127.0.0.1:18790/health",
    monitorState: "http://127.0.0.1:18790/monitor/state",
    renameConversation: "http://127.0.0.1:18790/monitor/conversation-title/rename",
    rccReload: "http://127.0.0.1:18790/monitor/rcc/reload",
    status: "http://127.0.0.1:18790/monitor",
    localLlm: "http://127.0.0.1:18790/monitor#local-llm",
  });

  function create(options = {}) {
    const fetcher = options.fetcher || root.fetch?.bind(root);
    const windowsApi = options.windowsApi || root.chrome?.windows;
    const randomId = options.randomId || (() => root.crypto?.randomUUID?.());

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
        const instanceCached = instance?.cached === true;
        const lastKnownState = String(instance?.last_known_state || "").trim().toUpperCase();
        for (const tab of Array.isArray(instance?.tabs) ? instance.tabs : []) {
          const tabId = Number(tab?.tab_id || 0);
          const windowId = Number(tab?.window_id || 0);
          const tabIndex = Number.isSafeInteger(tab?.tab_index) && tab.tab_index >= 0
            ? tab.tab_index
            : null;
          if (!Number.isSafeInteger(tabId) || tabId <= 0 ||
              !Number.isSafeInteger(windowId) || windowId <= 0) continue;
          const url = String(tab?.url || "").trim();
          // A missing /c/<key> is a pending ChatGPT conversation, not a reason to
          // project an arbitrary browser tab as N?. Only supported ChatGPT hosts
          // may enter the Monitor node list.
          if (!/^https:\/\/(?:chatgpt\.com|chat\.openai\.com)(?:[/?#]|$)/i.test(url)) continue;
          const conversationMatch = url.match(/\/c\/([a-z0-9-]+)/i);
          nodes.push(Object.freeze({
            instanceId,
            sessionId: String(instance?.session_id || "").trim(),
            instanceState,
            instanceCached,
            lastKnownState,
            displayStale: instanceCached && instanceState !== "OPEN",
            tabId,
            windowId,
            tabIndex,
            title: String(tab?.title || "ChatGPT").trim() || "ChatGPT",
            url,
            conversationKey: conversationMatch?.[1] || "",
            nodeLabel: String(tab?.node_label || "").trim(),
            presence: String(tab?.presence || "UNKNOWN").trim().toUpperCase(),
            active: tab?.active === true,
            generating: tab?.generating === true,
          }));
        }
      }
      nodes.sort((left, right) =>
        left.windowId - right.windowId ||
        (left.tabIndex ?? Number.MAX_SAFE_INTEGER) - (right.tabIndex ?? Number.MAX_SAFE_INTEGER) ||
        left.tabId - right.tabId ||
        left.instanceId.localeCompare(right.instanceId));
      return Object.freeze(nodes);
    }

    // The first failed RCC probe can contain no tabs even though the previous
    // exact display snapshot is still valid. Preserve that snapshot only as a
    // stale display candidate. The HWND contract may retain an existing exact
    // binding while Native still observes the same physical Chrome window; it
    // cannot create a new binding from these stale rows.
    function displayWindowNodes(state, previousNodes = []) {
      const current = windowNodes(state);
      if (current.length || !Array.isArray(previousNodes) || !previousNodes.length) return current;
      const instances = Array.isArray(state?.rcc?.instances) ? state.rcc.instances : [];
      const unavailable = new Set(instances.filter((instance) => {
        const value = String(instance?.state || "UNKNOWN").trim().toUpperCase();
        return value !== "OPEN";
      }).map((instance) => String(instance?.instance_id || "").trim()).filter(Boolean));
      if (!unavailable.size) return current;
      const retained = previousNodes.filter((node) => unavailable.has(String(node?.instanceId || "").trim())).map((node) => Object.freeze({
        ...node,
        instanceState: "UNAVAILABLE",
        instanceCached: true,
        lastKnownState: String(node?.lastKnownState || node?.instanceState || "OPEN").trim().toUpperCase(),
        displayStale: true,
      }));
      return Object.freeze(retained);
    }

    async function renameConversation(node, nextTitle, operationId = "") {
      if (typeof fetcher !== "function") throw new Error("BCT_RENAME_FETCH_UNAVAILABLE");
      const title = String(nextTitle || "").trim();
      const instanceId = String(node?.instanceId || "").trim();
      const sessionId = String(node?.sessionId || "").trim();
      const conversationKey = String(node?.conversationKey || "").trim();
      const tabId = Number(node?.tabId || 0);
      if (!instanceId || !sessionId || !conversationKey ||
          !Number.isSafeInteger(tabId) || tabId <= 0) {
        throw new Error("BCT_RENAME_EXACT_IDENTITY_REQUIRED");
      }
      if (!title || title.length > 100) throw new Error("BCT_RENAME_TITLE_INVALID");
      const generated = String(operationId || `monitor.rename.${randomId?.() || ""}`).trim();
      if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(generated)) {
        throw new Error("BCT_RENAME_OPERATION_ID_INVALID");
      }
      const response = await fetcher(URLS.renameConversation, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          instance_id: instanceId,
          session_id: sessionId,
          tab_id: tabId,
          conversation_key: conversationKey,
          title,
          operation_id: generated,
          timeout_s: 30,
        }),
      });
      const receipt = await response?.json?.().catch(() => null);
      if (!response?.ok) {
        throw new Error(String(receipt?.error || `BCT_RENAME_HTTP_${Number(response?.status || 0)}`));
      }
      if (String(receipt?.outcome || "").toUpperCase() !== "APPLIED") {
        throw new Error(String(receipt?.error || `BCT_RENAME_${receipt?.outcome || "UNVERIFIED"}`));
      }
      const savedTitle = String(receipt?.output?.result?.savedTitle || "").trim();
      if (savedTitle && savedTitle !== title) throw new Error("BCT_RENAME_TITLE_MISMATCH");
      return Object.freeze({ receipt, operationId: generated, title });
    }

    async function reloadRcc(instanceId, operationId = "") {
      if (typeof fetcher !== "function") throw new Error("BCT_RCC_RELOAD_FETCH_UNAVAILABLE");
      const instance = String(instanceId || "").trim();
      if (!/^[A-Za-z0-9_.:-]{6,128}$/.test(instance)) {
        throw new Error("BCT_RCC_RELOAD_EXACT_INSTANCE_REQUIRED");
      }
      const generated = String(operationId || `monitor.rcc-reload.${randomId?.() || ""}`).trim();
      if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(generated)) {
        throw new Error("BCT_RCC_RELOAD_OPERATION_ID_INVALID");
      }
      const response = await fetcher(URLS.rccReload, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ instance_id: instance, operation_id: generated, timeout_s: 10 }),
      });
      const receipt = await response?.json?.().catch(() => null);
      if (!response?.ok) {
        throw new Error(String(receipt?.error || `BCT_RCC_RELOAD_HTTP_${Number(response?.status || 0)}`));
      }
      if (String(receipt?.outcome || "").toUpperCase() !== "APPLIED") {
        throw new Error(String(receipt?.error || `BCT_RCC_RELOAD_${receipt?.outcome || "UNVERIFIED"}`));
      }
      return Object.freeze({ receipt, operationId: generated, instanceId: instance });
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
      displayWindowNodes,
      renameConversation,
      reloadRcc,
      openStatus: () => open(URLS.status, { width: 1120, height: 820 }),
      openLocalLlm: () => open(URLS.localLlm, { width: 1200, height: 820 }),
    });
  }

  root.MonitorBctShell = Object.freeze({ URLS, create });
})(globalThis);
