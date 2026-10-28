"use strict";

// Project BCT node identity onto the physical browser windows already rendered
// by the Native desktop capture. Node labels deliberately share each window's
// z-order so a rear window and its label are covered together.
(function installMonitorBctThumbnailProjection(root) {
  function text(value) {
    return String(value ?? "").trim();
  }

  function uniqueNodeTokens(values) {
    const seenNumbers = new Set();
    const result = [];
    for (const value of Array.isArray(values) ? values : []) {
      const rawToken = value && typeof value === "object" ? value.token : value;
      const tabId = Number(value && typeof value === "object" ? value.tabId : null);
      const item = {
        token: text(rawToken),
        tabId: Number.isInteger(tabId) && tabId >= 0 ? tabId : null,
      };
      const number = Number(item.token);
      if (Number.isSafeInteger(number) && number > 0) {
        if (seenNumbers.has(number)) continue;
        seenNumbers.add(number);
        item.token = String(number);
        result.push(item);
        continue;
      }
      // UUID-less tabs retain their exact tabId. Multiple `?` labels can then
      // be rendered in order while selection still targets one real tab only.
      if (item.token === "?") result.push(item);
    }
    return result;
  }

  function geometryForImage(img) {
    const geometry = {
      left: text(img?.style?.left),
      top: text(img?.style?.top),
      width: text(img?.style?.width),
      height: text(img?.style?.height),
    };
    return Object.values(geometry).every(Boolean) ? geometry : null;
  }

  function windowZIndex(img) {
    const value = Number(img?.style?.zIndex || img?.dataset?.nativeZIndex || 1);
    return Number.isFinite(value) ? Math.max(1, value) : 1;
  }

  function render(options = {}) {
    const container = options.container;
    if (!container) {
      return Object.freeze({ status: "NO_CONTAINER", candidates: 0, matched: 0, rendered: 0 });
    }

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

    const state = options.state;
    const numbersForHwnd = typeof options.numbersForHwnd === "function"
      ? options.numbersForHwnd
      : () => [];
    const images = [...container.querySelectorAll(".monitor-desktop-thumb-window[data-hwnd]")];
    let matched = 0;
    let rendered = 0;
    const skipped = { hidden: 0, minimized: 0, noNumbers: 0, noGeometry: 0 };

    for (const img of images) {
      const hwnd = text(img.dataset.hwnd);
      if (!hwnd) continue;
      if (img.style.display === "none" || img.hidden) {
        skipped.hidden += 1;
        continue;
      }

      const tokens = uniqueNodeTokens(numbersForHwnd(hwnd, state));
      if (!tokens.length) {
        skipped.noNumbers += 1;
        continue;
      }
      matched += 1;

      const geometry = geometryForImage(img);
      if (!geometry) {
        skipped.noGeometry += 1;
        continue;
      }

      const windowLayer = documentObject.createElement("span");
      windowLayer.className = "monitor-thumbnail-node-window";
      windowLayer.dataset.hwnd = hwnd;
      Object.assign(windowLayer.style, geometry);
      windowLayer.style.zIndex = String(windowZIndex(img));
      windowLayer.classList.toggle(
        "monitor-bct-node-target-highlighted",
        Boolean(options.highlightedHwnd) && hwnd === text(options.highlightedHwnd),
      );

      const badge = documentObject.createElement("span");
      badge.className = "monitor-node-number-badge monitor-thumbnail-tab-badge";
      badge.dataset.hwnd = hwnd;
      // Keep each slash+node pair atomic.  A line may begin at `/58`, but a
      // node number such as `57` can never be detached from its separator.
      const selectedHere = hwnd === text(options.selectedNodeHwnd);
      const selectedToken = text(options.selectedNodeToken);
      const selectedTabId = options.selectedNodeTabId == null ? null : Number(options.selectedNodeTabId);
      const labelParts = [];
      for (const item of tokens) {
        const token = item.token;
        if (labelParts.length > 0) {
          const separator = documentObject.createElement("span");
          separator.className = "monitor-thumbnail-tab-separator";
          separator.textContent = "/";
          labelParts.push(separator);
        }
        const part = documentObject.createElement("span");
        const selectedByTab = selectedHere && Number.isInteger(selectedTabId) && item.tabId === selectedTabId;
        const selectedByKnownToken = selectedHere && !Number.isInteger(selectedTabId) && selectedToken !== "?" && token === selectedToken;
        part.className = `monitor-thumbnail-tab-token${selectedByTab || selectedByKnownToken ? " is-selected" : ""}`;
        part.textContent = token;
        labelParts.push(part);
      }
      badge.replaceChildren(...labelParts);
      badge.title = `BCT 노드 ${tokens.map((item) => item.token).join(" / ")}`;
      windowLayer.append(badge);
      layer.append(windowLayer);
      rendered += 1;
    }

    return Object.freeze({
      status: rendered ? "RENDERED" : (matched ? "NO_GEOMETRY" : "NO_MATCH"),
      desktopId: text(container.dataset.desktopId),
      candidates: images.length,
      matched,
      rendered,
      repositioned: 0,
      unresolvedCollisions: 0,
      zStackedWindows: 0,
      hiddenWindows: 0,
      zOrderConfirmed: true,
      skipped: Object.freeze(skipped),
    });
  }

  root.MonitorBctThumbnailProjection = Object.freeze({ render });
})(globalThis);
