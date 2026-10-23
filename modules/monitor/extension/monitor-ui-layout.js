/* BWM presentation-only runtime layout. BCT data file is authoritative;
   no UI editor, arbitrary CSS/JS, browser action, or node-state mutation. */
(function (global) {
  "use strict";
  const KEY = "bwm.monitor.ui.layout.v1";
  const ENDPOINT = "http://127.0.0.1:18790/monitor/ui-layout";
  const BUTTONS = Object.freeze([
    "monitorExtensionReload",
    "monitorRccReload",
    "monitorBctRecover",
    "monitorMcpTunnelRecover",
    "monitorBctControlRefresh"
  ]);
  const DEFAULT = Object.freeze({
    version: 1,
    toolbar: Object.freeze({
      placement: "inline",
      order: BUTTONS,
      hidden: Object.freeze([]),
      density: "compact",
      gap: 2
    }),
    captureFallback: Object.freeze({
      mode: "last_good",
      staleAfterSeconds: 20,
      maxAgeSeconds: 180
    }),
    presentation: Object.freeze({
      nodeTitleFontPx: 12,
      nodeCardMinHeightPx: 36,
      nodeGapPx: 6,
      panelPaddingPx: 10,
      thumbnailStatusIconPx: 20
    })
  });
  const PRESENTATION_LIMITS = Object.freeze({
    nodeTitleFontPx: [10, 16],
    nodeCardMinHeightPx: [30, 56],
    nodeGapPx: [2, 14],
    panelPaddingPx: [5, 16],
    thumbnailStatusIconPx: [16, 32]
  });
  const has = (obj, name) => Object.prototype.hasOwnProperty.call(obj, name);
  const plain = (value) => value !== null && typeof value === "object" &&
    !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null);
  const copy = (config) => JSON.parse(JSON.stringify(config));

  function normalize(raw) {
    if (!plain(raw) || raw.version !== 1 || !plain(raw.toolbar) ||
        Object.keys(raw).some((key) => !["version", "toolbar", "presentation", "captureFallback"].includes(key)) ||
        Object.keys(raw.toolbar).some((key) =>
          !["placement", "order", "hidden", "density", "gap"].includes(key))) {
      throw new TypeError("UI_LAYOUT_SCHEMA_INVALID");
    }
    const t = raw.toolbar;
    const placement = has(t, "placement") ? t.placement : DEFAULT.toolbar.placement;
    const density = has(t, "density") ? t.density : DEFAULT.toolbar.density;
    const gap = has(t, "gap") ? t.gap : DEFAULT.toolbar.gap;
    const order = has(t, "order") ? t.order : BUTTONS;
    const hidden = has(t, "hidden") ? t.hidden : [];
    if (!["inline", "below"].includes(placement) ||
        !["compact", "normal"].includes(density) ||
        !Number.isInteger(gap) || gap < 0 || gap > 16 ||
        !Array.isArray(order) || order.length !== BUTTONS.length ||
        new Set(order).size !== BUTTONS.length ||
        order.some((id) => !BUTTONS.includes(id)) ||
        !Array.isArray(hidden) || new Set(hidden).size !== hidden.length ||
        hidden.some((id) => !BUTTONS.includes(id))) {
      throw new TypeError("UI_LAYOUT_VALUE_NOT_ALLOWED");
    }
    const values = has(raw, "presentation") ? raw.presentation : {};
    if (!plain(values) || Object.keys(values).some((key) => !has(PRESENTATION_LIMITS, key))) {
      throw new TypeError("UI_PRESENTATION_FIELDS_INVALID");
    }
    const presentation = { ...DEFAULT.presentation, ...values };
    if (Object.entries(PRESENTATION_LIMITS).some(([key, bounds]) =>
      !Number.isInteger(presentation[key]) ||
      presentation[key] < bounds[0] || presentation[key] > bounds[1])) {
      throw new TypeError("UI_PRESENTATION_VALUES_INVALID");
    }
    const fallbackExtra = has(raw, "captureFallback") ? raw.captureFallback : {};
    if (!plain(fallbackExtra) ||
        Object.keys(fallbackExtra).some((key) => !["mode","staleAfterSeconds","maxAgeSeconds"].includes(key))) {
      throw new TypeError("UI_CAPTURE_FALLBACK_FIELDS_INVALID");
    }
    const captureFallback = {...DEFAULT.captureFallback, ...fallbackExtra};
    if (!["last_good","compact","legacy"].includes(captureFallback.mode) ||
        !Number.isInteger(captureFallback.staleAfterSeconds) ||
        !Number.isInteger(captureFallback.maxAgeSeconds) ||
        captureFallback.staleAfterSeconds < 5 || captureFallback.staleAfterSeconds > 120 ||
        captureFallback.maxAgeSeconds < 30 || captureFallback.maxAgeSeconds > 600 ||
        captureFallback.staleAfterSeconds >= captureFallback.maxAgeSeconds) {
      throw new TypeError("UI_CAPTURE_FALLBACK_VALUE_INVALID");
    }
    return { version: 1, toolbar: {
      placement, order: [...order], hidden: [...hidden], density, gap
    }, presentation, captureFallback };
  }

  function merge(current, patch) {
    if (!plain(patch) || Object.keys(patch).some((key) => !["version", "toolbar", "presentation", "captureFallback"].includes(key)) ||
        (has(patch, "version") && patch.version !== 1) ||
        (has(patch, "toolbar") && !plain(patch.toolbar)) ||
        (has(patch, "presentation") && !plain(patch.presentation)) ||
        (has(patch, "captureFallback") && !plain(patch.captureFallback))) {
      throw new TypeError("UI_LAYOUT_PATCH_INVALID");
    }
    return normalize({ version: 1, toolbar: {
      ...current.toolbar, ...(patch.toolbar || {})
    },
      presentation: { ...current.presentation, ...(patch.presentation || {}) },
      captureFallback: { ...current.captureFallback, ...(patch.captureFallback || {}) }
    });
  }

  // Pure presentation policy. Never interprets a frame as proof that the HWND
  // is open/closed, that an operation succeeded, or that a worker finished.
  function chooseCaptureView(input, settings) {
    const policy = normalize({version:1,toolbar:{},
      captureFallback: settings || {}}).captureFallback;
    const now = Number.isFinite(input?.now) ? Number(input.now) : Date.now();
    const captured = String(input?.nextState || "") === "captured";
    const incomingSource = String(input?.nextSource || "");
    if (captured && (incomingSource.startsWith("blob:") || incomingSource.startsWith("data:image/"))) {
      const observedAt = Number(input?.nextCapturedAt || 0);
      return {state:"captured",source:incomingSource,
        capturedAt:Number.isFinite(observedAt) && observedAt > 0 && observedAt <= now ? observedAt : now,
        label:""};
    }
    const previousState = String(input?.previousState || "");
    const previousSource = String(input?.previousSource || "");
    const capturedAt = Number(input?.previousCapturedAt || 0);
    const age = now - capturedAt;
    const useful = ["captured","held","stale"].includes(previousState) &&
      (previousSource.startsWith("blob:") || previousSource.startsWith("data:image/")) &&
      capturedAt > 0 && age >= 0 && age <= policy.maxAgeSeconds * 1000;
    if (policy.mode === "last_good" && useful) {
      const stale = age > policy.staleAfterSeconds * 1000;
      return {state: stale ? "stale" : "held",source:previousSource,
        capturedAt,label:stale ? "오래된 화면" : "이전 화면"};
    }
    return {state:"placeholder",source:incomingSource,capturedAt:0,label:""};
  }

  function create(root, storage, onError, options = {}) {
    if (!root || !storage?.local?.get) throw new TypeError("UI_LAYOUT_ADAPTER_INVALID");
    const titleLine = root.querySelector(".monitor-title-line");
    const titleBlock = root.querySelector(".monitor-title-block");
    const toolbar = root.querySelector(".monitor-utility-actions");
    if (!titleLine || !titleBlock || !toolbar) throw new TypeError("UI_LAYOUT_ANCHOR_MISSING");
    const nodes = new Map(BUTTONS.map((id) => [id, root.querySelector("#" + id)]));
    if ([...nodes.values()].some((node) => !node || node.parentNode !== toolbar)) {
      throw new TypeError("UI_LAYOUT_BUTTON_ID_MISMATCH");
    }
    const fetcher = has(options, "fetcher")
      ? options.fetcher : (typeof global.fetch === "function" ? global.fetch.bind(global) : null);
    const pollMs = Number.isInteger(options.pollMs) ? options.pollMs : 3000;
    let state = copy(DEFAULT);
    let disposed = false;
    let remoteValidated = false;
    let pendingVersion = 0;
    let inflight = null;
    let pollTimer = null;

    function apply(raw) {
      if (disposed) return copy(state);
      const next = normalize(raw);
      const parent = next.toolbar.placement === "inline" ? titleLine : titleBlock;
      parent.appendChild(toolbar);
      root.classList.toggle("bwm-ui-layout-inline", next.toolbar.placement === "inline");
      toolbar.classList.toggle("bwm-ui-toolbar-inline", next.toolbar.placement === "inline");
      toolbar.classList.toggle("bwm-ui-toolbar-compact", next.toolbar.density === "compact");
      toolbar.style.setProperty("--bwm-ui-toolbar-gap", next.toolbar.gap + "px");
      const presentationVars = {
        nodeTitleFontPx: "--bwm-node-title-size",
        nodeCardMinHeightPx: "--bwm-node-card-min-height",
        nodeGapPx: "--bwm-node-gap",
        panelPaddingPx: "--bwm-panel-padding",
        thumbnailStatusIconPx: "--bwm-thumbnail-status-size"
      };
      for (const [key, variable] of Object.entries(presentationVars)) {
        root.style.setProperty(variable, next.presentation[key] + "px");
      }
      for (const id of next.toolbar.order) {
        const button = nodes.get(id);
        toolbar.appendChild(button); // existing real element and handler are retained
        button.hidden = next.toolbar.hidden.includes(id);
      }
      state = next;
      return copy(state);
    }

    async function refreshRemote() {
      if (disposed || !fetcher) return copy(state);
      if (inflight) return inflight;
      inflight = (async () => {
        try {
          const response = await fetcher(ENDPOINT, { cache: "no-store" });
          if (!response?.ok) throw new Error("BWM_UI_CONFIG_UNAVAILABLE");
          const body = await response.json();
          if (body?.status !== "READY" || !plain(body.config)) {
            throw new Error("BWM_UI_CONFIG_NOT_READY");
          }
          if (!disposed) {
            remoteValidated = true;
            ++pendingVersion;
            apply(body.config);
          }
        } catch (error) {
          if (typeof onError === "function" && options.reportRemoteErrors) onError(error);
        }
        return copy(state);
      })();
      try { return await inflight; }
      finally { inflight = null; }
    }

    function changed(changes, area) {
      if (disposed || remoteValidated || area !== "local" || !has(changes, KEY)) return;
      ++pendingVersion;
      try {
        apply(changes[KEY].newValue === undefined ? DEFAULT : changes[KEY].newValue);
      } catch (error) {
        if (typeof onError === "function") onError(error);
      }
    }

    storage.onChanged?.addListener?.(changed);
    // Set compact non-overlapping header immediately, even before Core is ready.
    apply(DEFAULT);
    const request = ++pendingVersion;
    const ready = Promise.resolve(storage.local.get(KEY)).then((values) => {
      if (!disposed && !remoteValidated && pendingVersion === request && values && has(values, KEY)) {
        try { apply(values[KEY]); }
        catch (error) { if (typeof onError === "function") onError(error); }
      }
      return refreshRemote();
    }).catch((error) => {
      if (typeof onError === "function") onError(error);
      return refreshRemote();
    });

    if (fetcher && pollMs >= 1000 && typeof global.setInterval === "function") {
      pollTimer = global.setInterval(() => {
        if (!disposed && (typeof document === "undefined" || document.visibilityState !== "hidden")) {
          void refreshRemote();
        }
      }, pollMs);
      pollTimer?.unref?.(); // node test runner only
    }

    return Object.freeze({
      ready,
      read: () => copy(state),
      apply,
      refreshRemote,
      dispose: () => {
        disposed = true;
        ++pendingVersion;
        if (pollTimer !== null) global.clearInterval?.(pollTimer);
        storage.onChanged?.removeListener?.(changed);
      }
    });
  }

  global.MonitorUiLayout = Object.freeze({ KEY, ENDPOINT, BUTTONS, DEFAULT,
    normalize, merge, chooseCaptureView, create });
})(typeof globalThis !== "undefined" ? globalThis : this);
