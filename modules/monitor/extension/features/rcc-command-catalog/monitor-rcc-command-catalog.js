"use strict";

// Read-only Monitor feature for the authoritative BCT command catalogue.
// It intentionally has no command invocation port: selecting a row only
// explains its source, effect and target contract.
(function installMonitorRccCommandCatalog(root) {
  const text = (value) => String(value || "").trim();
  const originLabel = (origin) => origin === "rcc-native" ? "RCC 확장 내부" : "BCT 조합";

  function normalizeRows(source) {
    return Object.freeze((Array.isArray(source) ? source : []).map((row) => Object.freeze({
      command: text(row?.command),
      origin: text(row?.origin),
      group: text(row?.display_group || row?.group),
      summary: text(row?.summary),
      effect: text(row?.effect),
      target: text(row?.target),
      source: text(row?.source),
      legacyAlias: text(row?.legacy_alias),
      compatibilityAlias: text(row?.compatibility_alias),
    })).filter((row) => (
      /^(?:rcc|bct)_/.test(row.command) &&
      (row.origin === "rcc-native" || row.origin === "bct") &&
      row.group && row.summary && row.effect && row.target
    )));
  }

  function create(options = {}) {
    const doc = options.document || root.document;
    const shell = options.shell;
    const dialog = options.dialog || doc?.getElementById("monitorCommandCatalogDialog");
    const openButton = options.openButton || doc?.getElementById("monitorCommandCatalogOpen");
    const closeButton = options.closeButton || doc?.getElementById("monitorCommandCatalogClose");
    const list = options.list || doc?.getElementById("monitorCommandCatalogList");
    const detail = options.detail || doc?.getElementById("monitorCommandCatalogDetail");
    const search = options.search || doc?.getElementById("monitorCommandCatalogSearch");
    const summary = options.summary || doc?.getElementById("monitorCommandCatalogSummary");
    const refreshButton = options.refreshButton || doc?.getElementById("monitorCommandCatalogRefresh");
    let rows = Object.freeze([]);
    let selected = "";

    function showDetail(row) {
      if (!detail || !row) return;
      selected = row.command;
      detail.replaceChildren();
      const title = doc.createElement("strong"); title.textContent = row.command;
      const description = doc.createElement("p"); description.textContent = row.summary;
      const meta = doc.createElement("dl");
      const values = [
        ["실행 위치", originLabel(row.origin)],
        ["외부 효과", row.effect],
        ["정확한 대상", row.target],
        ["구현", row.source],
      ];
      if (row.legacyAlias) values.push(["이전 내부 키", row.legacyAlias]);
      if (row.compatibilityAlias) values.push(["호환 호출 이름", row.compatibilityAlias]);
      for (const [label, value] of values) {
        const term = doc.createElement("dt"); term.textContent = label;
        const definition = doc.createElement("dd"); definition.textContent = value;
        meta.append(term, definition);
      }
      const note = doc.createElement("small");
      note.textContent = "이 목록은 읽기 전용입니다. 클릭해도 명령을 실행하거나 대상 상태를 바꾸지 않습니다.";
      detail.append(title, description, meta, note);
    }

    function render() {
      if (!list) return;
      const needle = text(search?.value).toLowerCase();
      const visible = rows.filter((row) => !needle || `${row.command} ${row.group} ${row.summary} ${row.effect} ${row.target}`.toLowerCase().includes(needle));
      const groups = new Map();
      for (const row of visible) {
        const key = `${row.origin}\u0000${row.group}`;
        if (!groups.has(key)) groups.set(key, { origin: row.origin, group: row.group, rows: [] });
        groups.get(key).rows.push(row);
      }
      list.replaceChildren();
      for (const { origin, group, rows: groupRows } of groups.values()) {
        const section = doc.createElement("section"); section.className = "monitor-command-catalog-group";
        const heading = doc.createElement("h3"); heading.textContent = `${originLabel(origin)} · ${group}`;
        const entries = doc.createElement("div"); entries.className = "monitor-command-catalog-entries";
        for (const row of groupRows) {
          const button = doc.createElement("button"); button.type = "button"; button.className = "monitor-command-catalog-entry";
          button.dataset.command = row.command; button.classList.toggle("is-selected", row.command === selected);
          const name = doc.createElement("code"); name.textContent = row.command;
          const desc = doc.createElement("span"); desc.textContent = row.summary;
          const badge = doc.createElement("em"); badge.dataset.effect = row.effect; badge.textContent = row.effect;
          button.append(name, desc, badge);
          button.addEventListener("click", () => { showDetail(row); render(); });
          entries.append(button);
        }
        section.append(heading, entries); list.append(section);
      }
      if (!list.childElementCount) {
        const empty = doc.createElement("p"); empty.className = "monitor-command-catalog-empty";
        empty.textContent = rows.length ? "검색 결과가 없습니다." : "표시할 공개 명령이 없습니다.";
        list.append(empty);
      }
      if (summary) summary.textContent = `${visible.length}/${rows.length}개 · 읽기 전용`;
    }

    async function refresh() {
      if (!shell?.rccCommandCatalog) throw new Error("BCT_RCC_COMMAND_CATALOG_UNAVAILABLE");
      if (refreshButton) refreshButton.disabled = true;
      if (summary) summary.textContent = "카탈로그 읽는 중…";
      try {
        rows = normalizeRows(await shell.rccCommandCatalog());
        if (!rows.length) throw new Error("BCT_RCC_COMMAND_CATALOG_EMPTY");
        if (!rows.some((row) => row.command === selected)) selected = "";
        render();
      } catch (error) {
        if (summary) summary.textContent = "카탈로그를 읽지 못했습니다";
        if (detail) {
          detail.replaceChildren();
          const message = doc.createElement("span");
          message.textContent = text(error?.message) || "BCT_RCC_COMMAND_CATALOG_FAILED";
          detail.append(message);
        }
      } finally {
        if (refreshButton) refreshButton.disabled = false;
      }
    }

    async function open() {
      if (!dialog) return;
      if (!dialog.open) dialog.showModal();
      if (!rows.length) await refresh();
      search?.focus();
    }

    search?.addEventListener("input", render);
    refreshButton?.addEventListener("click", () => void refresh());
    openButton?.addEventListener("click", () => void open());
    closeButton?.addEventListener("click", () => dialog?.close());
    return Object.freeze({ open, refresh, render, rows: () => rows });
  }

  root.MonitorRccCommandCatalog = Object.freeze({ create, normalizeRows });
})(globalThis);
