"use strict";

// Read-only, current-session join between RCC Chrome window ids and Windows
// HWNDs. It intentionally returns no binding when the active ChatGPT tab or
// the physical HWND is not unique. Bindings are memory-only.
(function installMonitorWindowHwndContract(root) {
  const SCHEMA = "BCT_RCC_CHROME_HWND_CURRENT_SESSION_V1";
  function text(value) { return String(value ?? "").trim(); }
  function positiveId(value) { const id = text(value); return /^\d+$/.test(id) && id !== "0" ? id : ""; }
  function conversationKey(value) { const key = text(value).toLowerCase(); return /^[a-z0-9-]{3,128}$/.test(key) ? key : ""; }
  function lineage(node) {
    const instanceId = text(node?.instanceId), sessionId = text(node?.sessionId), windowId = positiveId(node?.windowId);
    return instanceId && sessionId && windowId ? `${instanceId}:${sessionId}:${windowId}` : "";
  }
  function locations(value) { return value instanceof Map ? [...value.values()] : (Array.isArray(value) ? value : []); }

  function create(options = {}) {
    const identityMaxAgeMs = Math.max(1000, Number(options.identityMaxAgeMs) || 8000);
    function resolve(input = {}) {
      const now = Number(input.now) || Date.now();
      const activeByLineage = new Map(), rejected = [];
      for (const node of Array.isArray(input.nodes) ? input.nodes : []) {
        if (text(node?.instanceState).toUpperCase() !== "OPEN" || node?.active !== true) continue;
        const key = lineage(node), conversation = conversationKey(node?.conversationKey);
        if (!key || !conversation) { rejected.push(Object.freeze({ reason: "ACTIVE_RCC_IDENTITY_INCOMPLETE" })); continue; }
        if (activeByLineage.has(key)) { rejected.push(Object.freeze({ lineage: key, reason: "ACTIVE_TAB_AMBIGUOUS" })); activeByLineage.set(key, null); continue; }
        activeByLineage.set(key, Object.freeze({ lineage: key, instanceId: text(node.instanceId), sessionId: text(node.sessionId), windowId: positiveId(node.windowId), conversationKey: conversation }));
      }
      const hwndsByConversation = new Map();
      for (const location of locations(input.locations)) {
        const hwnd = positiveId(location?.hwnd), conversation = conversationKey(location?.conversationKey), observedAt = Number(location?.identityAt) || 0;
        if (!hwnd || !conversation || observedAt < now - identityMaxAgeMs || observedAt > now + 1000) continue;
        const candidates = hwndsByConversation.get(conversation) || new Set(); candidates.add(hwnd); hwndsByConversation.set(conversation, candidates);
      }
      const tentative = [];
      for (const candidate of activeByLineage.values()) {
        if (!candidate) continue;
        const hwnds = hwndsByConversation.get(candidate.conversationKey) || new Set();
        if (hwnds.size !== 1) { rejected.push(Object.freeze({ lineage: candidate.lineage, reason: hwnds.size ? "HWND_AMBIGUOUS" : "HWND_IDENTITY_UNAVAILABLE" })); continue; }
        tentative.push(Object.freeze({ ...candidate, hwnd: [...hwnds][0], observedAt: now }));
      }
      const lineagesByHwnd = new Map();
      for (const item of tentative) { const items = lineagesByHwnd.get(item.hwnd) || []; items.push(item); lineagesByHwnd.set(item.hwnd, items); }
      const bindings = tentative.filter((item) => {
        const unique = (lineagesByHwnd.get(item.hwnd) || []).length === 1;
        if (!unique) rejected.push(Object.freeze({ lineage: item.lineage, reason: "RCC_WINDOW_AMBIGUOUS" }));
        return unique;
      });
      return Object.freeze({ schema: SCHEMA, generatedAt: now, identityMaxAgeMs, bindings: Object.freeze(bindings), rejected: Object.freeze(rejected) });
    }
    return Object.freeze({ schema: SCHEMA, resolve, lineage });
  }
  root.MonitorWindowHwndContract = Object.freeze({ SCHEMA, create });
})(globalThis);
