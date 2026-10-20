"use strict";

// Render BCT node labels as one semantic layer above the Native desktop
// capture. This module owns every badge position so legacy per-image
// decorators cannot apply the physical offset a second time.
(function installMonitorBctThumbnailProjection(root) {
  function text(value) {
    return String(value ?? "").trim();
  }

  function positiveNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : 0;
  }

  function geometryFor(img, location, viewport) {
    const left = text(img?.style?.left) || (location
      ? `${((Number(location.left) - viewport.left) / viewport.width) * 100}%`
      : "");
    const top = text(img?.style?.top) || (location
      ? `${((Number(location.top) - viewport.top) / viewport.height) * 100}%`
      : "");
    const width = text(img?.style?.width) || (location
      ? `${(Number(location.width) / viewport.width) * 100}%`
      : "");
    const height = text(img?.style?.height) || (location
      ? `${(Number(location.height) / viewport.height) * 100}%`
      : "");
    return { left, top, width, height };
  }

  function render(options = {}) {
    const container = options.container;
    if (!container) return Object.freeze({ status: "NO_CONTAINER", candidates: 0, matched: 0, rendered: 0 });
    const state = options.state;
    const locations = options.locations instanceof Map ? options.locations : new Map();
    const numbersForHwnd = typeof options.numbersForHwnd === "function"
      ? options.numbersForHwnd
      : () => [];
    const documentObject = container.ownerDocument || root.document;
    for (const badge of container.querySelectorAll(
      ".monitor-thumbnail-tab-badge, .monitor-window-desktop-badge-thumb, .monitor-window-desktop-badge",
    )) badge.remove();

    let layer = container.querySelector(".monitor-thumbnail-node-overlay");
    if (!layer) {
      layer = documentObject.createElement("span");
      layer.className = "monitor-thumbnail-node-overlay";
      layer.setAttribute("aria-hidden", "true");
    }
    layer.replaceChildren();
    container.append(layer);

    const desktopId = text(container.dataset.desktopId);
    const images = [...container.querySelectorAll(".monitor-desktop-thumb-window[data-hwnd]")];
    const imagesByHwnd = new Map(images
      .map((img) => [text(img.dataset.hwnd), img])
      .filter(([hwnd]) => Boolean(hwnd)));
    const candidates = new Set(imagesByHwnd.keys());
    for (const [hwnd, location] of locations) {
      if (text(location?.desktopId) === desktopId) candidates.add(text(hwnd));
    }

    const viewport = {
      left: Number(container.dataset.monitorPreviewVirtualLeft) || 0,
      top: Number(container.dataset.monitorPreviewVirtualTop) || 0,
      width: Math.max(1, positiveNumber(container.dataset.monitorPreviewVirtualWidth) || 1),
      height: Math.max(1, positiveNumber(container.dataset.monitorPreviewVirtualHeight) || 1),
    };
    let matched = 0;
    let rendered = 0;
    const skipped = { hidden: 0, minimized: 0, noNumbers: 0, noGeometry: 0 };

    for (const hwnd of candidates) {
      if (!hwnd) continue;
      const img = imagesByHwnd.get(hwnd) || null;
      const location = locations.get(hwnd) || null;
      if (img?.style?.display === "none" || location?.visible === false) {
        skipped.hidden += 1;
        continue;
      }
      if (Boolean(location?.iconic)) {
        skipped.minimized += 1;
        continue;
      }
      const numbers = [...new Set(numbersForHwnd(hwnd, state)
        .map(Number)
        .filter((number) => Number.isSafeInteger(number) && number > 0))];
      if (!numbers.length) {
        skipped.noNumbers += 1;
        continue;
      }
      matched += 1;
      const geometry = geometryFor(img, location, viewport);
      if (!geometry.left || !geometry.top || !geometry.width || !geometry.height) {
        skipped.noGeometry += 1;
        continue;
      }

      const windowLayer = documentObject.createElement("span");
      windowLayer.className = "monitor-thumbnail-node-window";
      windowLayer.dataset.hwnd = hwnd;
      Object.assign(windowLayer.style, geometry);
      windowLayer.classList.toggle(
        "monitor-bct-node-target-highlighted",
        Boolean(options.highlightedHwnd) && hwnd === text(options.highlightedHwnd),
      );

      const badge = documentObject.createElement("span");
      badge.className = "monitor-node-number-badge monitor-thumbnail-tab-badge";
      badge.dataset.hwnd = hwnd;
      badge.textContent = `N${numbers.join("/")}`;
      badge.title = `BCT 노드 ${numbers.join(" / ")}`;
      windowLayer.append(badge);
      layer.append(windowLayer);
      rendered += 1;
    }

    return Object.freeze({
      status: rendered ? "RENDERED" : (matched ? "NO_GEOMETRY" : "NO_MATCH"),
      desktopId,
      candidates: candidates.size,
      matched,
      rendered,
      skipped: Object.freeze(skipped),
    });
  }

  root.MonitorBctThumbnailProjection = Object.freeze({ render });
})(globalThis);
