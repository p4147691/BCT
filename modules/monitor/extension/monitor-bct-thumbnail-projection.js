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

  function pixels(value, extent) {
    const raw = text(value);
    if (!raw) return 0;
    const number = Number.parseFloat(raw);
    if (!Number.isFinite(number)) return 0;
    return raw.endsWith("%") ? (number / 100) * extent : number;
  }

  function rectanglesOverlap(first, second, gap = 1) {
    return first.left < second.right + gap
      && first.right + gap > second.left
      && first.top < second.bottom + gap
      && first.bottom + gap > second.top;
  }

  function badgeSize(badge) {
    const measured = typeof badge?.getBoundingClientRect === "function"
      ? badge.getBoundingClientRect()
      : null;
    const labelLength = text(badge?.textContent).length;
    return {
      width: positiveNumber(measured?.width) || Math.max(24, 10 + (labelLength * 6.5)),
      height: positiveNumber(measured?.height) || 16,
    };
  }

  function badgeRectangle(windowRectangle, size, anchor, containerSize) {
    const inset = 2;
    const onRight = anchor.endsWith("right");
    const onBottom = anchor.startsWith("bottom");
    const unclampedLeft = onRight
      ? windowRectangle.right - size.width - inset
      : windowRectangle.left + inset;
    const unclampedTop = onBottom
      ? windowRectangle.bottom - size.height - inset
      : windowRectangle.top + inset;
    const left = Math.max(0, Math.min(unclampedLeft, containerSize.width - size.width));
    const top = Math.max(0, Math.min(unclampedTop, containerSize.height - size.height));
    return {
      left,
      top,
      right: left + size.width,
      bottom: top + size.height,
    };
  }

  function arrangeBadges(container, entries) {
    const measured = typeof container?.getBoundingClientRect === "function"
      ? container.getBoundingClientRect()
      : null;
    const containerSize = {
      width: positiveNumber(measured?.width) || positiveNumber(container?.clientWidth) || 320,
      height: positiveNumber(measured?.height) || positiveNumber(container?.clientHeight) || 180,
    };
    const anchors = ["top-left", "top-right", "bottom-left", "bottom-right"];
    const occupied = [];
    let repositioned = 0;
    let unresolved = 0;

    for (const entry of entries) {
      const geometry = entry.geometry;
      const left = pixels(geometry.left, containerSize.width);
      const top = pixels(geometry.top, containerSize.height);
      const windowRectangle = {
        left,
        top,
        right: left + pixels(geometry.width, containerSize.width),
        bottom: top + pixels(geometry.height, containerSize.height),
      };
      const size = badgeSize(entry.badge);
      const candidates = anchors.map((anchor) => ({
        anchor,
        rectangle: badgeRectangle(windowRectangle, size, anchor, containerSize),
      }));
      let selected = candidates.find((candidate) => !occupied.some((rectangle) => (
        rectanglesOverlap(candidate.rectangle, rectangle)
      )));
      if (!selected) {
        selected = candidates
          .map((candidate) => ({
            ...candidate,
            collisions: occupied.filter((rectangle) => rectanglesOverlap(candidate.rectangle, rectangle)).length,
          }))
          .sort((first, second) => first.collisions - second.collisions)[0];
        unresolved += 1;
      }
      entry.badge.dataset.anchor = selected.anchor;
      if (selected.anchor !== "top-left") repositioned += 1;
      occupied.push(selected.rectangle);
    }
    return { repositioned, unresolved };
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
    const renderedEntries = [];
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
      renderedEntries.push({ badge, geometry, hwnd });
      rendered += 1;
    }

    const arrangement = arrangeBadges(container, renderedEntries);

    return Object.freeze({
      status: rendered ? "RENDERED" : (matched ? "NO_GEOMETRY" : "NO_MATCH"),
      desktopId,
      candidates: candidates.size,
      matched,
      rendered,
      repositioned: arrangement.repositioned,
      unresolvedCollisions: arrangement.unresolved,
      skipped: Object.freeze(skipped),
    });
  }

  root.MonitorBctThumbnailProjection = Object.freeze({ render });
})(globalThis);
