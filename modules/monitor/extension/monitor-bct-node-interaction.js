"use strict";

// Exact, user-initiated navigation from a BCT/RCC node card to the native
// Chrome HWND already proven by the current-session window/HWND contract.
// This module never guesses a desktop or window and owns no persistent binding.
(function installMonitorBctNodeInteraction(root) {
  function hwndText(value) {
    const hwnd = String(value ?? "").trim();
    return /^\d+$/.test(hwnd) && hwnd !== "0" ? hwnd : "";
  }

  function scanContainsHwnd(scan, hwnd) {
    if (!scan?.ok) return false;
    const direct = Array.isArray(scan.hwnds) ? scan.hwnds : [];
    const detailed = Array.isArray(scan.windows) ? scan.windows.map((item) => item?.hwnd) : [];
    return [...direct, ...detailed].some((value) => hwndText(value) === hwnd);
  }

  function create(options = {}) {
    if (typeof options.nativeRequest !== "function") throw new Error("BCT_NODE_NATIVE_REQUEST_REQUIRED");
    const nativeRequest = options.nativeRequest;
    const highlight = typeof options.highlight === "function" ? options.highlight : () => {};
    const renderVirtualDesktops = typeof options.renderVirtualDesktops === "function" ? options.renderVirtualDesktops : () => {};
    const selectVirtualDesktopPreview = typeof options.selectVirtualDesktopPreview === "function" ? options.selectVirtualDesktopPreview : () => {};

    function select(hwndValue) {
      const hwnd = hwndText(hwndValue);
      if (!hwnd) throw new Error("BCT_NODE_HWND_INVALID");
      highlight(hwnd);
      return Object.freeze({ ok: true, hwnd });
    }

    async function activate(hwndValue) {
      const hwnd = select(hwndValue).hwnd;
      const state = await nativeRequest({ type: "getVirtualDesktops" });
      if (!state?.ok) throw new Error(state?.error || "데스크톱 상태 확인 실패");
      const desktopIds = Array.isArray(state.desktopIds) ? state.desktopIds.map(String) : [];
      let index = -1;
      for (let current = 0; current < desktopIds.length; current += 1) {
        const scan = await nativeRequest({
          type: "getDesktopWindowHandles",
          desktopId: desktopIds[current],
          includeMonitorWindows: "true",
        });
        if (scanContainsHwnd(scan, hwnd)) {
          index = current;
          break;
        }
      }
      if (index < 0) throw new Error("이 창의 실제 데스크톱 위치를 확인하지 못함");

      renderVirtualDesktops(state);
      const switched = await nativeRequest({ type: "switchVirtualDesktop", index });
      if (!switched?.ok) throw new Error(switched?.error || "데스크톱 전환 실패");
      renderVirtualDesktops(switched);
      selectVirtualDesktopPreview(index);

      const foreground = await nativeRequest({ type: "restoreForegroundWindow", hwnd });
      if (!foreground?.ok) throw new Error(foreground?.error || "웹브라우저 창 활성화 실패");
      highlight(hwnd);
      return Object.freeze({ ok: true, hwnd, index });
    }

    return Object.freeze({ select, activate });
  }

  root.MonitorBctNodeInteraction = Object.freeze({ create });
})(globalThis);
