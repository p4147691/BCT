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
  function slotsByDesktop(input = {}) {
    const grouped = new Map();
    const locations = input.locations instanceof Map ? input.locations : new Map(input.locations || []);
    const numbersForHwnd = typeof input.numbersForHwnd === "function" ? input.numbersForHwnd : () => [];
    for (const [rawHwnd, location] of locations) {
      // The bottom desktop label is a minimized-window summary, not a list of
      // every ChatGPT tab that happens to be open on the desktop.
      if (!Boolean(location?.iconic)) continue;
      const desktopId = text(location?.desktopId);
      if (!desktopId) continue;
      const hwnd = text(location?.hwnd || rawHwnd);
      if (!hwnd) continue;
      const slots = [...new Set((numbersForHwnd(hwnd) || []).map(positiveNodeNumber).filter(Boolean))];
      if (!slots.length) continue;
      const target = grouped.get(desktopId) || new Set();
      for (const slot of slots) target.add(slot);
      grouped.set(desktopId, target);
    }
    return new Map([...grouped].map(([desktopId, slots]) => [desktopId, [...slots].sort((a, b) => a - b)]));
  }
  root.MonitorMinimizedNodeBadgeContract = Object.freeze({ minimizedEvent, slotsByDesktop });
})(globalThis);
