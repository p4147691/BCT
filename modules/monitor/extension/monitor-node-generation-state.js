"use strict";
(function installMonitorNodeGenerationState(root) {
  function create({readTab, readConversation, ttlMs}) {
    if (typeof readTab !== "function" || typeof readConversation !== "function"
        || !Number.isFinite(ttlMs) || ttlMs < 0)
      throw new TypeError("MONITOR_NODE_GENERATION_DEPENDENCIES_INVALID");

    function directGenerationState(endpoint, now = Date.now()) {
      const key = String(endpoint?.conversation_key || "").trim();
      const tabId = String(endpoint?.tab_id ?? "").trim();
      if (!key || !tabId) return null;
      const item = readTab(key + ":" + tabId);
      if (!item || now - Number(item.at || 0) > ttlMs) return null;
      return item.generating === true;
    }

    function directUserAttention(endpoint) {
      const key = String(endpoint?.conversation_key || "").trim();
      const tabId = String(endpoint?.tab_id ?? "").trim();
      if (!key) return null;
      if (tabId) {
        const item = readTab(key + ":" + tabId);
        if (item) return item.userAttention || null;
      }
      return readConversation(key)?.userAttention || null;
    }

    function endpointIsGenerating(endpoint) {
      const direct = directGenerationState(endpoint);
      if (direct !== null) return direct;
      const metadata = endpoint?.metadata || {};
      if (metadata.generating === true || endpoint?.generating === true) return true;
      if (metadata.generating === false || endpoint?.generating === false) return false;
      const generationState = String(metadata.generation_state || endpoint?.generation_state || "").trim().toUpperCase();
      if (["GENERATING", "RUNNING", "WORKING", "ACTIVE"].includes(generationState)) return true;
      if (generationState) return false;
      const interactionState = String(metadata.interaction_state || endpoint?.interaction_state || "").trim().toUpperCase();
      return interactionState === "WORKING";
    }
    return Object.freeze({directGenerationState, directUserAttention, endpointIsGenerating});
  }
  root.MonitorNodeGenerationState = Object.freeze({create});
})(globalThis);
