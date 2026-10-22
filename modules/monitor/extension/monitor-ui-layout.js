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
    })
  });
  const has = (obj, name) => Object.prototype.hasOwnProperty.call(obj, name);
  const plain = (value) => value !== null && typeof value === "object" &&
    !Array.isArray(value) && (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null);
  const copy = (config) => JSON.parse(JSON.stringify(config));

  function normalize(raw) {
    if (!plain(raw) || raw.version !== 1 || !plain(raw.toolbar) ||
        Object.keys(raw).some((key) => !["version", "toolbar"].includes(key)) ||
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
    return { version: 1, toolbar: {
      placement, order: [...order], hidden: [...hidden], density, gap
    } };
  }

  function merge(current, patch) {
    if (!plain(patch) || Object.keys(patch).some((key) => !["version", "toolbar"].includes(key)) ||
        (has(patch, "version") && patch.version !== 1) ||
        (has(patch, "toolbar") && !plain(patch.toolbar))) {
      throw new TypeError("UI_LAYOUT_PATCH_INVALID");
    }
    return normalize({ version: 1, toolbar: {
      ...current.toolbar, ...(patch.toolbar || {})
    } });
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

  global.MonitorUiLayout = Object.freeze({ KEY, ENDPOINT, BUTTONS, DEFAULT, normalize, merge, create });
})(typeof globalThis !== "undefined" ? globalThis : this);
