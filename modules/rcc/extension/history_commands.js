/* Exact-conversation read-only RCC bridge. No send, reload, or existing-tab reuse. */
(function (root) {
  "use strict";
  const STORAGE = "historyReadTabsV1";
  const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const OP = /^[A-Za-z0-9_.:-]{1,80}$/;

  function keyOf(value) {
    const key = String(value || "").toLowerCase();
    if (!UUID.test(key)) throw new Error("HISTORY_CONVERSATION_KEY_INVALID");
    return key;
  }
  function positive(value, name) {
    const n = Number(value);
    if (!Number.isSafeInteger(n) || n < 1) throw new Error(name);
    return n;
  }
  function operationId(value) {
    const id = String(value || "");
    if (!OP.test(id)) throw new Error("HISTORY_OPERATION_ID_INVALID");
    return id;
  }
  function exactUrl(key) { return "https://chatgpt.com/c/" + keyOf(key); }
  function sameConversation(url, key) {
    try {
      const u = new URL(String(url || ""));
      return u.protocol === "https:" &&
        (u.hostname === "chatgpt.com" || u.hostname === "chat.openai.com") &&
        u.pathname === "/c/" + keyOf(key) &&
        !u.search && !u.hash;
    } catch (_) { return false; }
  }
  async function open(message, deps) {
    const conversationKey = keyOf(message.conversationKey);
    const op = operationId(message.operationId);
    const instanceId = String(message.instanceId || "");
    const fingerprint = JSON.stringify([instanceId, conversationKey, "HISTORY_ONLY"]);
    return deps.runIdempotentOperation(op, "history-open", fingerprint, async () => {
      const state = await deps.loadState();
      const sessionId = deps.endpointSessionId();
      if (String(state.settings.instanceId || "") !== instanceId || !sessionId) {
        throw new Error("HISTORY_OPEN_INSTANCE_MISMATCH");
      }
      const stored = (await deps.chrome.storage.local.get(STORAGE))[STORAGE] || {};
      if (Object.keys(stored).length >= 16) throw new Error("HISTORY_TAB_LIMIT");
      // The only window effect is creation of one inactive exact-target tab.
      // Do not register it as CONTROL or Worker or touch existing user tabs.
      const created = await deps.chrome.tabs.create({
        url: exactUrl(conversationKey), active: false
      });
      const tab = await deps.waitForConversationReady(created.id, conversationKey);
      if (!sameConversation(tab.url, conversationKey) || tab.active) {
        throw new Error("HISTORY_OPEN_IDENTITY_UNVERIFIED");
      }
      const receipt = {
        instanceId,
        sessionId,
        conversationKey, operationId: op,
        tabId: positive(tab.id, "HISTORY_TAB_INVALID"),
        windowId: positive(tab.windowId, "HISTORY_WINDOW_INVALID")
      };
      await deps.chrome.storage.local.set({[STORAGE]: {...stored, [op]: receipt}});
      return {
        ok: true, state: "HISTORY_TAB_READY", created: true,
        inactive: true, exactUrl: exactUrl(conversationKey), ...receipt
      };
    });
  }
  async function read(message, deps) {
    const conversationKey = keyOf(message.conversationKey);
    const openId = operationId(message.openOperationId);
    const tabId = positive(message.tabId, "HISTORY_TAB_INVALID");
    const windowId = positive(message.windowId, "HISTORY_WINDOW_INVALID");
    const sessionId = String(message.sessionId || "");
    const instanceId = String(message.instanceId || "");
    const maxSteps = Number(message.maxSteps);
    const maxTurns = Number(message.maxTurns);
    const maxBytes = Number(message.maxBytes);
    if (!Number.isSafeInteger(maxSteps) || maxSteps < 1 || maxSteps > 20 ||
        !Number.isSafeInteger(maxTurns) || maxTurns < 1 || maxTurns > 60 ||
        !Number.isSafeInteger(maxBytes) || maxBytes < 1024 || maxBytes > 24000) {
      throw new Error("HISTORY_READ_BOUNDS_INVALID");
    }
    const stored = (await deps.chrome.storage.local.get(STORAGE))[STORAGE] || {};
    const saved = stored[openId];
    if (!saved || saved.tabId !== tabId || saved.windowId !== windowId ||
        saved.instanceId !== instanceId || saved.sessionId !== sessionId ||
        saved.conversationKey !== conversationKey || saved.operationId !== openId) {
      throw new Error("HISTORY_READ_CREATION_RECEIPT_MISMATCH");
    }
    const tab = await deps.chrome.tabs.get(tabId);
    if (tab.windowId !== windowId || !sameConversation(tab.url, conversationKey)
        || tab.active) {
      throw new Error("HISTORY_READ_TAB_IDENTITY_MISMATCH");
    }
    // This is the dedicated history tab only, never a registered RCC task tab.
    await deps.chrome.scripting.executeScript({
      target: {tabId}, files: ["conversation_history_reader_v2.js"]
    });
    const injected = await deps.chrome.scripting.executeScript({
      target: {tabId},
      args: [exactUrl(conversationKey), maxSteps, maxTurns, maxBytes],
      func: async (targetUrl, steps, turnLimit, byteLimit) => {
        const exact = () => location.origin === "https://chatgpt.com" &&
          location.pathname === new URL(targetUrl).pathname &&
          !location.search && !location.hash;
        if (!exact() || !globalThis.BCTConversationHistoryV2) {
          return {ok: false, state: "HISTORY_IDENTITY_MISMATCH"};
        }
        const collected = await globalThis.BCTConversationHistoryV2.loadOlder(document, {
          expectedConversationUrl: targetUrl, maxSteps: steps,
          settle: () => new Promise(resolve => setTimeout(resolve, 180))
        });
        if (!exact()) return {ok: false, state: "HISTORY_IDENTITY_CHANGED"};
        const utf8 = new TextEncoder();
        // Return a bounded, explicit fragment; never silently call it full history.
        const messages = [];
        let budget = byteLimit, omitted = 0, truncated = false;
        for (const row of collected.messages) {
          if (messages.length >= turnLimit || budget < 128) {
            omitted++; truncated = true; continue;
          }
          const full = String(row.text || "");
          const fullBytes = utf8.encode(full).length;
          let kept = full;
          if (fullBytes > budget) {
            const chars = [];
            let used = 0;
            for (const char of full) {
              const cost = utf8.encode(char).length;
              if (used + cost > budget) break;
              chars.push(char); used += cost;
            }
            kept = chars.join("");
            truncated = true;
          }
          budget -= utf8.encode(kept).length;
          messages.push({id:row.id, text:kept, originalBytes:fullBytes,
            textTruncated:kept !== full});
        }
        return {
          ok: true, state: "HISTORY_PARTIAL", status: "PARTIAL",
          coverage: "OBSERVED_VISIBLE_TURNS", fullHistoryVerified: false,
          gapsVerifiable: false, reason: collected.reason,
          steps: collected.steps, identified: collected.messages.length,
          duplicateObservations: collected.duplicates,
          reobserved: collected.reobserved,
          unidentified: collected.unidentified,
          conflictingTexts: collected.conflictingTexts,
          observedFirstId: collected.messages[0]?.id || "",
          observedLastId: collected.messages[collected.messages.length-1]?.id || "",
          truncated, omitted, messages
        };
      }
    });
    // Require one exact frame/result; ambiguous transport must not be PASS.
    const result = injected?.length === 1 ? injected[0].result : null;
    if (result?.ok !== true || result.state !== "HISTORY_PARTIAL" ||
        result.status !== "PARTIAL" || result.fullHistoryVerified !== false) {
      throw new Error("HISTORY_READ_RESULT_UNVERIFIED");
    }
    // Revalidate after scrolling to protect against SPA navigation.
    const after = await deps.chrome.tabs.get(tabId);
    if (after.windowId !== windowId || after.active ||
        !sameConversation(after.url, conversationKey)) {
      throw new Error("HISTORY_READ_POST_IDENTITY_MISMATCH");
    }
    return { ...result, instanceId, sessionId, conversationKey,
      tabId, windowId, openOperationId: openId };
  }
  const api = {open, read, keyOf, exactUrl, sameConversation};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RccHistoryCommands = api;
})(typeof globalThis === "object" ? globalThis : this);
