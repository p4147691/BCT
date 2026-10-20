"use strict";

// Presentation-only SVG icon contract. It accepts semantic states, never raw
// Unicode symbols, and has no authority to change a work, tab, or window.
(function installMonitorStatusIcon(root) {
  const ACTIVITY = new Set(["play", "pause", "complete"]);
  const svg = (kind, className) => {
    const safeKind = ACTIVITY.has(kind) || kind === "warning" ? kind : "";
    if (!safeKind) return "";
    const shape = safeKind === "play"
      ? '<path d="M7 4.5 19 12 7 19.5Z"></path>'
      : safeKind === "pause"
        ? '<rect x="6" y="5" width="4.5" height="14" rx=".75"></rect><rect x="13.5" y="5" width="4.5" height="14" rx=".75"></rect>'
        : safeKind === "complete"
          ? '<rect x="5.5" y="5.5" width="13" height="13" rx=".8"></rect>'
          : '<path d="M12 3.25 21 20H3Z"></path><path d="M12 8v5.5"></path><circle cx="12" cy="16.75" r="1"></circle>';
    return `<svg class="${className} monitor-status-icon-${safeKind}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${shape}</svg>`;
  };
  function normalize(input = {}) {
    const activity = ACTIVITY.has(input.activity) ? input.activity : "";
    return Object.freeze({ activity, warning: input.warning === true });
  }
  function render(host, input = {}) {
    if (!host) return normalize(input);
    const state = normalize(input);
    host.replaceChildren();
    if (state.activity) host.insertAdjacentHTML("beforeend", svg(state.activity, "monitor-status-icon"));
    if (state.warning) host.insertAdjacentHTML("beforeend", svg("warning", "monitor-status-icon monitor-status-icon-warning"));
    host.hidden = !state.activity && !state.warning;
    return state;
  }
  root.MonitorStatusIcon = Object.freeze({ normalize, render, svg });
})(globalThis);
