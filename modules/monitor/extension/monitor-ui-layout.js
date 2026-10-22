/* BWM presentation-only layout configuration. No BCT/RCC/native actions. */
(function (global) {
  "use strict";
  const KEY = "bwm.monitor.ui.layout.v1";
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
      placement: "below",
      order: BUTTONS,
      hidden: Object.freeze([]),
      density: "normal",
      gap: 4
    })
  });
  const OWN = Object.prototype.hasOwnProperty;
  const has = (obj, name) => OWN.call(obj, name);
  const plain = (value) =>
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
  const copy = (config) => JSON.parse(JSON.stringify(config));
  function normalize(raw) {
    if (!plain(raw) || raw.version !== 1 || !plain(raw.toolbar)) {
      throw new TypeError("UI_LAYOUT_SCHEMA_INVALID");
    }
    if (Object.keys(raw).some((key) => !["version", "toolbar"].includes(key)) ||
        Object.keys(raw.toolbar).some((key) => !["placement", "order", "hidden", "density", "gap"].includes(key))) {
      throw new TypeError("UI_LAYOUT_FIELD_NOT_ALLOWED");
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
    return { version: 1, toolbar: { placement, order: [...order], hidden: [...hidden], density, gap } };
  }
  function merge(current, patch) {
    if (!plain(patch) || Object.keys(patch).some((k) => !["version", "toolbar"].includes(k)) ||
        (has(patch, "version") && patch.version !== 1) ||
        (has(patch, "toolbar") && !plain(patch.toolbar))) {
      throw new TypeError("UI_LAYOUT_PATCH_INVALID");
    }
    return normalize({
      version: 1,
      toolbar: { ...current.toolbar, ...(patch.toolbar || {}) }
    });
  }
  function create(root, storage, onError) {
    if (!root || !storage?.local?.get || !storage?.local?.set) throw new TypeError("UI_LAYOUT_ADAPTER_INVALID");
    const titleLine = root.querySelector(".monitor-title-line");
    const titleBlock = root.querySelector(".monitor-title-block");
    const toolbar = root.querySelector(".monitor-utility-actions");
    if (!titleLine || !titleBlock || !toolbar) throw new TypeError("UI_LAYOUT_ANCHOR_MISSING");
    const nodes = new Map(BUTTONS.map((id) => [id, root.querySelector("#" + id)]));
    if ([...nodes.values()].some((node) => !node || node.parentNode !== toolbar)) {
      throw new TypeError("UI_LAYOUT_BUTTON_ID_MISMATCH");
    }
    let state = copy(DEFAULT);
    let disposed = false;
    let editor = null;
    let pendingVersion = 0;

    function apply(value) {
      const next = normalize(value);
      // Re-parenting a real button retains its original click handler and identity.
      (next.toolbar.placement === "inline" ? titleLine : titleBlock).appendChild(toolbar);
      titleLine.appendChild(trigger); // the compact edit entry stays after the real toolbar
      toolbar.classList.toggle("bwm-ui-toolbar-inline", next.toolbar.placement === "inline");
      toolbar.classList.toggle("bwm-ui-toolbar-compact", next.toolbar.density === "compact");
      toolbar.style.setProperty("--bwm-ui-toolbar-gap", next.toolbar.gap + "px");
      for (const id of next.toolbar.order) {
        const node = nodes.get(id);
        toolbar.appendChild(node);
        node.hidden = next.toolbar.hidden.includes(id);
      }
      state = next;
      if (editor && !editor.hidden && editor.dataset.dirty !== "yes") {
        editor.querySelector("#bwmUiLayoutJson").value = JSON.stringify(state, null, 2);
      }
      return copy(state);
    }

    async function persist(raw) {
      const next = normalize(raw);
      await storage.local.set({ [KEY]: next });
      if (!disposed) apply(next);
      return copy(next);
    }

    async function patch(raw) {
      return persist(merge(state, raw));
    }

    async function reset() {
      if (typeof storage.local.remove !== "function") throw new Error("UI_LAYOUT_REMOVE_UNAVAILABLE");
      await storage.local.remove(KEY);
      if (!disposed) apply(DEFAULT);
      return copy(DEFAULT);
    }

    function showEditor() {
      if (!editor) {
        editor = document.createElement("section");
        editor.id = "bwmUiLayoutEditor";
        editor.className = "bwm-ui-layout-editor";
        editor.setAttribute("aria-label", "BWM 화면 배치 설정");
        editor.innerHTML = '<label for="bwmUiLayoutJson">화면 배치 설정(JSON)</label>' +
          '<textarea id="bwmUiLayoutJson" spellcheck="false" aria-label="BWM 배치 JSON"></textarea>' +
          '<div class="bwm-ui-layout-editor-actions">' +
          '<button id="bwmUiLayoutApply" type="button">배치 적용</button>' +
          '<button id="bwmUiLayoutReset" type="button">기본 배치</button>' +
          '<button id="bwmUiLayoutClose" type="button">닫기</button></div>' +
          '<span id="bwmUiLayoutError" role="status"></span>';
        root.appendChild(editor);
        const field = editor.querySelector("#bwmUiLayoutJson");
        const error = editor.querySelector("#bwmUiLayoutError");
        field.addEventListener("input", () => { editor.dataset.dirty = "yes"; });
        editor.querySelector("#bwmUiLayoutApply").addEventListener("click", async () => {
          try {
            await persist(JSON.parse(field.value));
            editor.dataset.dirty = "no";
            error.textContent = "배치 설정이 저장되었습니다.";
          } catch (err) {
            error.textContent = "적용 거부: " + String(err?.message || "설정 오류");
          }
        });
        editor.querySelector("#bwmUiLayoutReset").addEventListener("click", async () => {
          try {
            await reset();
            editor.dataset.dirty = "no";
            field.value = JSON.stringify(state, null, 2);
            error.textContent = "기본 배치로 복원했습니다.";
          } catch (err) {
            error.textContent = "초기화 실패: " + String(err?.message || "저장소 오류");
          }
        });
        editor.querySelector("#bwmUiLayoutClose").addEventListener("click", () => {
          editor.hidden = true;
        });
      }
      editor.dataset.dirty = "no";
      editor.querySelector("#bwmUiLayoutError").textContent = "";
      editor.querySelector("#bwmUiLayoutJson").value = JSON.stringify(state, null, 2);
      editor.hidden = false;
      return editor;
    }

    // Small, optional edit entry point for BCT UI automation, not a general command executor.
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = "bwmUiLayoutOpen";
    trigger.className = "bwm-ui-layout-open";
    trigger.textContent = "배치";
    trigger.title = "BWM 화면 배치 설정 열기";
    trigger.addEventListener("click", showEditor);
    titleLine.appendChild(trigger);

    function changed(changes, area) {
      if (disposed || area !== "local" || !has(changes, KEY)) return;
      ++pendingVersion; // do not let a stale initial get overwrite a newer storage event
      try {
        apply(changes[KEY].newValue === undefined ? DEFAULT : changes[KEY].newValue);
      } catch (err) {
        if (typeof onError === "function") onError(err);
      }
    }
    storage.onChanged?.addListener?.(changed);
    const request = ++pendingVersion;
    const ready = Promise.resolve(storage.local.get(KEY)).then((values) => {
      if (!disposed && request === pendingVersion) {
        try { apply(values && has(values, KEY) ? values[KEY] : DEFAULT); }
        catch (err) { if (typeof onError === "function") onError(err); }
      }
      return copy(state);
    }).catch((err) => {
      if (typeof onError === "function") onError(err);
      return copy(state);
    });
    return Object.freeze({
      ready,
      read: () => copy(state),
      patch,
      save: persist,
      reset,
      showEditor,
      dispose: () => {
        disposed = true;
        pendingVersion++;
        storage.onChanged?.removeListener?.(changed);
        trigger.remove();
        editor?.remove();
      }
    });
  }

  global.MonitorUiLayout = Object.freeze({ KEY, BUTTONS, normalize, merge, create });
})(typeof globalThis !== "undefined" ? globalThis : this);
