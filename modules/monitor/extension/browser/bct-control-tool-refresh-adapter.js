(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.MonitorBctControlToolRefreshAdapter = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const BCT_CONTROL_APP_ID = "asdk_app_6ac3a06ea58c819195b90feb131b6da5";
  const BCT_CONTROL_SETTINGS_PATH = `/settings/plugins-settings/plugin_${BCT_CONTROL_APP_ID}`;
  const BCT_CONTROL_SETTINGS_URL = `https://chatgpt.com${BCT_CONTROL_SETTINGS_PATH}`;

  function normalizeUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return `${url.origin}${url.pathname.replace(/\/$/, "")}`;
    } catch (_) {
      return "";
    }
  }

  function refreshBctControlToolsOnPage(expectedPath) {
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const normalizedText = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const matchingButtons = () => [...document.querySelectorAll("button")].filter((button) => {
      const text = normalizedText(button.textContent || button.getAttribute("aria-label"));
      return text === "도구 새로 고침" || text === "Refresh tools";
    });
    const visibleErrors = () => [...document.querySelectorAll('[role="alert"], [aria-live="assertive"]')]
      .map((node) => normalizedText(node.textContent)).filter((text) => /실패|오류|error|failed/i.test(text));
    const receipt = (values) => Object.freeze({
      schema: "monitor.bct-control.tool-refresh.receipt.v1",
      ...values,
    });

    return (async () => {
      if (location.origin !== "https://chatgpt.com" || location.pathname.replace(/\/$/, "") !== expectedPath) {
        return receipt({ ok:false, status:"NOT_APPLIED", error:"BCT_CONTROL_SETTINGS_IDENTITY_CHANGED" });
      }
      const matches = matchingButtons();
      if (matches.length !== 1) {
        return receipt({ ok:false, status:"NOT_APPLIED", error:"BCT_CONTROL_REFRESH_BUTTON_NOT_UNIQUE" });
      }
      let button = matches[0];
      if (button.disabled || button.getAttribute("aria-disabled") === "true") {
        return receipt({ ok:false, status:"BUSY", error:"BCT_CONTROL_REFRESH_ALREADY_RUNNING" });
      }

      const errorsBefore = new Set(visibleErrors());
      button.click();
      let accepted = false;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await wait(100);
        const current = matchingButtons();
        if (current.length === 1) button = current[0];
        if (button.disabled || button.getAttribute("aria-disabled") === "true") {
          accepted = true;
          break;
        }
      }
      if (!accepted) {
        return receipt({ ok:false, status:"NOT_APPLIED", error:"BCT_CONTROL_REFRESH_NOT_ACCEPTED" });
      }

      for (let attempt = 0; attempt < 300; attempt += 1) {
        await wait(100);
        const current = matchingButtons();
        if (current.length === 1) button = current[0];
        const newError = visibleErrors().find((text) => !errorsBefore.has(text));
        if (newError) return receipt({ ok:false, status:"NOT_APPLIED", accepted:true,
          error:"BCT_CONTROL_REFRESH_REPORTED_FAILURE" });
        if (current.length === 1 && !button.disabled && button.getAttribute("aria-disabled") !== "true") {
          return receipt({ ok:true, status:"APPLIED", accepted:true, completed:true });
        }
      }
      return receipt({ ok:false, status:"UNKNOWN", accepted:true, error:"BCT_CONTROL_REFRESH_COMPLETION_UNVERIFIED" });
    })();
  }

  function create(chromeApi) {
    if (!chromeApi?.tabs?.query || !chromeApi?.tabs?.create || !chromeApi?.tabs?.get ||
        !chromeApi?.scripting?.executeScript) {
      throw new Error("BCT_CONTROL_REFRESH_CHROME_API_REQUIRED");
    }

    async function waitForComplete(tabId) {
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const tab = await chromeApi.tabs.get(tabId);
        if (tab?.status === "complete") return tab;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      throw new Error("BCT_CONTROL_SETTINGS_LOAD_TIMEOUT");
    }

    async function resolveSettingsTab() {
      const tabs = await chromeApi.tabs.query({ url:"https://chatgpt.com/settings/plugins-settings/*" });
      const exact = (Array.isArray(tabs) ? tabs : []).filter((tab) =>
        normalizeUrl(tab?.url) === BCT_CONTROL_SETTINGS_URL);
      if (exact.length > 1) throw new Error("BCT_CONTROL_REFRESH_AMBIGUOUS_SETTINGS_TABS");
      if (exact.length === 1) return { tab:exact[0], opened:false };
      const created = await chromeApi.tabs.create({ url:BCT_CONTROL_SETTINGS_URL, active:false });
      if (!Number.isInteger(created?.id)) throw new Error("BCT_CONTROL_SETTINGS_TAB_CREATE_FAILED");
      return { tab:await waitForComplete(created.id), opened:true };
    }

    async function refreshTools() {
      const resolved = await resolveSettingsTab();
      const tabId = Number(resolved.tab?.id);
      if (!Number.isInteger(tabId) || tabId < 0) throw new Error("BCT_CONTROL_SETTINGS_TAB_ID_REQUIRED");
      const results = await chromeApi.scripting.executeScript({
        target: { tabId },
        func: refreshBctControlToolsOnPage,
        args: [BCT_CONTROL_SETTINGS_PATH],
      });
      const value = Array.isArray(results) ? results[0]?.result : null;
      if (!value || value.schema !== "monitor.bct-control.tool-refresh.receipt.v1") {
        throw new Error("BCT_CONTROL_REFRESH_RECEIPT_MISSING");
      }
      return Object.freeze({
        ...value,
        tabId,
        windowId: Number.isInteger(resolved.tab?.windowId) ? resolved.tab.windowId : null,
        settingsUrl: BCT_CONTROL_SETTINGS_URL,
        opened: resolved.opened,
      });
    }

    return Object.freeze({ refreshTools });
  }

  return Object.freeze({
    BCT_CONTROL_APP_ID,
    BCT_CONTROL_SETTINGS_PATH,
    BCT_CONTROL_SETTINGS_URL,
    create,
    refreshBctControlToolsOnPage,
  });
});
