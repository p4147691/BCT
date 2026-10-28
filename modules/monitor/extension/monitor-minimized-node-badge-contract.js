"use strict";

// Pure projection boundary for desktop-thumbnail node badges.
// Native lifecycle supplies the desktop; BCT/RCC supplies node numbers for an
// HWND. Only minimized ChatGPT windows are represented in the desktop-label
// summary. Open ChatGPT windows have their own badge inside the thumbnail.
// This module never invents a node or controls a window, so a missing mapping
// merely hides the badge.
(function installMonitorMinimizedNodeBadgeContract(root) {
  function text(value) { return String(value ?? "").trim(); }
  function positiveNodeNumber(value) {
    const number = Number(value);
    return Number.isSafeInteger(number) && number > 0 ? number : 0;
  }
  function minimizedEvent(event) {
    return Boolean(event?.iconic) || text(event?.reason).toLowerCase() === "minimized";
  }
  function minimizedToken(value, fallbackIdentity) {
    const raw = typeof value === "object" && value ? value : { token: value };
    const token = text(raw.token).replace(/^N/i, "");
    const number = positiveNodeNumber(token);
    if (number) return { token: String(number), tabId: Number(raw.tabId) || 0, identity: `node:${number}` };
    if (token !== "?") return null;
    const tabId = Number(raw.tabId) || 0;
    return { token: "?", tabId, identity: tabId ? `tab:${tabId}` : `unknown:${fallbackIdentity}` };
  }
  function tokensByDesktop(input = {}) {
    const grouped = new Map();
    const locations = input.locations instanceof Map ? input.locations : new Map(input.locations || []);
    const tokensForHwnd = typeof input.tokensForHwnd === "function" ? input.tokensForHwnd : () => [];
    let ordinal = 0;
    for (const [rawHwnd, location] of locations) {
      if (!Boolean(location?.iconic)) continue;
      const desktopId = text(location?.desktopId);
      if (!desktopId) continue;
      const hwnd = text(location?.hwnd || rawHwnd);
      if (!hwnd) continue;
      const target = grouped.get(desktopId) || new Map();
      for (const value of tokensForHwnd(hwnd) || []) {
        const item = minimizedToken(value, `${hwnd}:${ordinal++}`);
        if (item && !target.has(item.identity)) target.set(item.identity, item);
      }
      if (target.size) grouped.set(desktopId, target);
    }
    return new Map([...grouped].map(([desktopId, values]) => {
      const items = [...values.values()];
      // Numeric-only summaries retain the historical ascending order. Mixed
      // unknown tabs must keep Chrome's observed tab order, not move '?' to
      // the end where a different tab might appear selected.
      if (items.every((item) => positiveNodeNumber(item.token))) {
        items.sort((a, b) => positiveNodeNumber(a.token) - positiveNodeNumber(b.token));
      }
      return [desktopId, items];
    }));
  }
  function slotsByDesktop(input = {}) {
    const tokens = tokensByDesktop({ locations: input.locations, tokensForHwnd: input.numbersForHwnd });
    return new Map([...tokens].map(([desktopId, items]) => [desktopId, items.map((item) => positiveNodeNumber(item.token)).filter(Boolean)]));
  }
  root.MonitorMinimizedNodeBadgeContract = Object.freeze({ minimizedEvent, slotsByDesktop, tokensByDesktop });
})(globalThis);
