"use strict";

// Exact, user-initiated Chrome tab selection for the Monitor node list.
// The caller must already have resolved the native HWND. This adapter only
// selects the already-observed ChatGPT tab and focuses its existing window.
(function installMonitorTabFocusAdapter(root) {
  const RECEIPT_SCHEMA = "monitor.browser.tab-focus.receipt.v1";

  function integer(value) {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
  }

  function conversationKeyFromUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:") return "";
      if (url.hostname !== "chatgpt.com" && url.hostname !== "chat.openai.com") return "";
      const match = url.pathname.match(/^\/c\/([^/?#]+)\/?$/i);
      return match ? decodeURIComponent(match[1]) : "";
    } catch (_) {
      return "";
    }
  }

  function dotKeyFromUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:" || (url.hostname !== "chatgpt.com" && url.hostname !== "chat.openai.com")) return "";
      const match = url.pathname.match(/^\/dots\/([^/?#]+)\/?$/i);
      return match ? decodeURIComponent(match[1]).trim().toLowerCase() : "";
    } catch (_) { return ""; }
  }

  function localCodexReferenceFromUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "https:" || (url.hostname !== "chatgpt.com" && url.hostname !== "chat.openai.com")) return "";
      const match = url.pathname.match(/^\/local\/client-new-thread:([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\/?$/i);
      return match ? String(match[1]).toLowerCase() : "";
    } catch (_) { return ""; }
  }

  function exactIdentityFromTarget(value = {}) {
    const conversationKey = String(value.conversationKey || "").trim().toLowerCase();
    const dotKey = String(value.dotKey || "").trim().toLowerCase();
    const codexLocalReference = String(value.codexLocalReference || "").trim().toLowerCase();
    const kinds = [
      /^[0-9a-f-]{20,}$/i.test(conversationKey) ? ["conversation", conversationKey] : null,
      dotKey ? ["dot", dotKey] : null,
      /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(codexLocalReference) ? ["codex-local", codexLocalReference] : null,
    ].filter(Boolean);
    return kinds.length === 1 ? Object.freeze({ kind: kinds[0][0], value: kinds[0][1] }) : null;
  }

  function exactIdentityFromUrl(value) {
    const conversationKey = conversationKeyFromUrl(value).toLowerCase();
    if (conversationKey) return Object.freeze({ kind: "conversation", value: conversationKey });
    const dotKey = dotKeyFromUrl(value);
    if (dotKey) return Object.freeze({ kind: "dot", value: dotKey });
    const codexLocalReference = localCodexReferenceFromUrl(value);
    return codexLocalReference ? Object.freeze({ kind: "codex-local", value: codexLocalReference }) : null;
  }

  function receipt(status, target, details = {}) {
    return Object.freeze({
      schema: RECEIPT_SCHEMA,
      ok: status === "APPLIED",
      status,
      tabId: target.tabId,
      windowId: target.windowId,
        conversationKey: target.conversationKey,
        dotKey: target.dotKey,
        codexLocalReference: target.codexLocalReference,
      ...details,
    });
  }

  function create(chromeApi) {
    if (!chromeApi?.tabs?.get || !chromeApi?.tabs?.update || !chromeApi?.windows?.get || !chromeApi?.windows?.update) {
      throw new Error("MONITOR_TAB_FOCUS_CHROME_API_REQUIRED");
    }

    async function focus(targetValue = {}) {
      const target = Object.freeze({
        tabId: integer(targetValue.tabId),
        windowId: integer(targetValue.windowId),
        conversationKey: String(targetValue.conversationKey || "").trim(),
        dotKey: String(targetValue.dotKey || "").trim(),
        codexLocalReference: String(targetValue.codexLocalReference || "").trim(),
      });
      const expectedIdentity = exactIdentityFromTarget(target);
      if (target.tabId === null || target.windowId === null || !expectedIdentity) {
        return receipt("NOT_APPLIED", target, { error: "MONITOR_TAB_FOCUS_TARGET_INVALID" });
      }

      let before;
      try {
        before = await chromeApi.tabs.get(target.tabId);
      } catch (error) {
        return receipt("NOT_APPLIED", target, { error: error?.message || "MONITOR_TAB_FOCUS_TAB_NOT_FOUND" });
      }
      const observedIdentity = exactIdentityFromUrl(before?.url);
      if (integer(before?.windowId) !== target.windowId || observedIdentity?.kind !== expectedIdentity.kind || observedIdentity?.value !== expectedIdentity.value) {
        return receipt("NOT_APPLIED", target, {
          error: "MONITOR_TAB_FOCUS_IDENTITY_MISMATCH",
          observedWindowId: integer(before?.windowId),
          observedIdentity,
        });
      }

      let effectStarted = false;
      try {
        effectStarted = true;
        await chromeApi.tabs.update(target.tabId, { active: true });
        await chromeApi.windows.update(target.windowId, { focused: true });
        const [afterTab, afterWindow] = await Promise.all([
          chromeApi.tabs.get(target.tabId),
          chromeApi.windows.get(target.windowId),
        ]);
        if (
          integer(afterTab?.windowId) !== target.windowId ||
          exactIdentityFromUrl(afterTab?.url)?.kind !== expectedIdentity.kind ||
          exactIdentityFromUrl(afterTab?.url)?.value !== expectedIdentity.value ||
          afterTab?.active !== true ||
          afterWindow?.focused !== true
        ) {
          return receipt("UNKNOWN", target, { error: "MONITOR_TAB_FOCUS_POSTCONDITION_FAILED" });
        }
        return receipt("APPLIED", target, { active: true, focused: true });
      } catch (error) {
        return receipt(effectStarted ? "UNKNOWN" : "NOT_APPLIED", target, {
          error: error?.message || "MONITOR_TAB_FOCUS_FAILED",
        });
      }
    }

    return Object.freeze({ focus });
  }

  root.MonitorTabFocusAdapter = Object.freeze({ create, conversationKeyFromUrl, dotKeyFromUrl, localCodexReferenceFromUrl, RECEIPT_SCHEMA });
})(globalThis);
