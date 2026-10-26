//@@FN_START:ensureMonitorCoreNativePort
function ensureMonitorCoreNativePort() {

  if (monitorCoreNativePort) return monitorCoreNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CORE_HOST);

  monitorCoreNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.type === "shellMirrorChanged" || response?.subscribed === true) {

      window.dispatchEvent(new CustomEvent("desktopwindow-shell-native-event", { detail: response }));

      return;

    }

    if (response?.event === true) return; // Unsolicited native events cannot consume command replies.
    const pending = monitorCoreNativePending.shift();

    if (pending) pending.resolve(response);

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Core Native Host 연결 종료";

    monitorCoreNativePort = null;

    while (monitorCoreNativePending.length) monitorCoreNativePending.shift().reject(new Error(error));

  });

  // Core port carries request/response traffic only. Uncorrelated subscription
  // messages used to consume the next pending request response.

  return port;

}
//@@FN_END:ensureMonitorCoreNativePort

//@@FN_START:ensureMonitorNativePort
function ensureMonitorNativePort() {

  if (monitorNativePort) return monitorNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

  monitorNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.event === true && response?.type === "windowMoveSizeEnd") { scheduleMonitorWindowLifecycleEvent(response); return; }
    if (response?.event === true && response?.type === "windowForegroundChanged") { handleMonitorForegroundChangedEvent(response); return; }
    if (response?.event === true && response?.type === "desktopWallpaperChanged") {
      const explicitId=String(response.desktopId||"").toLowerCase();
      const visuals=[...(monitorDesktopThumbs?.querySelectorAll?.(".monitor-desktop-thumb-visual")||[])];
      const targets=explicitId ? visuals.filter(v=>String(v.dataset.desktopId||"").toLowerCase()===explicitId) : visuals;
      monitorDesktopThumbs.dataset.wallpaperEventAt=String(Date.now());
      // Each visual keeps its own generation fence; no cross-desktop cache.
      void Promise.allSettled(targets.map(visual =>
        globalThis.MonitorDesktopThumbnailV2.refreshWallpaper(
          visual,visual.dataset.desktopId,id=>monitorNativeVisualRead({
            type:"getDesktopVisualSnapshot",desktopId:id,
            maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,quality:68
          }),{force:true})));
      return;
    }
    if (response?.event === true && response?.type === "monitorDragPreviewReleased") {
      const drag = monitorBctPointerDrag;
      if (drag?.active && response?.token === monitorBctNativePreviewToken) {
        cancelMonitorBctNodePointerDrag({ pointerId:drag.pointerId });
      }
      return;
    }

    if (response?.event === true) return; // Never shift a request reply for unsolicited Native events.
    const pending = monitorNativePending.shift();

    if (pending) {
      pending.resolve(response);
    }

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료";

    monitorNativePort = null;

    while (monitorNativePending.length) monitorNativePending.shift().reject(new Error(error));

  });

  return port;

}
//@@FN_END:ensureMonitorNativePort

//@@FN_START:monitorControlNativeRequest
function monitorControlNativeRequest(message) {
  // Pixel capture belongs exclusively to the WGC Core host. The Control host
  // still contains the legacy synchronous capture implementation.
  if (message?.type === "captureWindow") {
    return Promise.reject(new Error("CAPTURE_REQUIRES_WGC_CORE_ADAPTER"));
  }

  return new Promise((resolve, reject) => {

    const port = ensureMonitorNativePort();

    monitorNativePending.push({ resolve, reject, message });

    try { port.postMessage(message); }

    catch (error) { monitorNativePending.pop(); reject(error); }

  });

}
//@@FN_END:monitorControlNativeRequest

//@@FN_START:monitorCoreNative
function monitorCoreNative(message) {
  return MonitorNativeTrace.request("core", message, () => monitorCoreNativeRequest(message));
}
//@@FN_END:monitorCoreNative

//@@FN_START:monitorCoreNativeRequest
function monitorCoreNativeRequest(message) {

  return new Promise((resolve, reject) => {

    const port = ensureMonitorCoreNativePort(); monitorCoreNativePending.push({ resolve, reject });

    try { port.postMessage(message); } catch (error) { monitorCoreNativePending.pop(); reject(error); }

  });

}
//@@FN_END:monitorCoreNativeRequest

//@@FN_START:monitorEndpointNativeChatExpired
function monitorEndpointNativeChatExpired(endpoint, now = Date.now()) {

  const location = monitorLocationForEndpoint(endpoint, now);

  const since = Number(location?.nonChatSince || 0);

  return since > 0 && now - since >= MONITOR_NON_CHAT_GRACE_MS;

}
//@@FN_END:monitorEndpointNativeChatExpired

//@@FN_START:monitorFreshNativeLocations
function monitorFreshNativeLocations(conversationKey, now = Date.now()) {

  const key = String(conversationKey || "").trim();

  if (!key) return [];

  return [...monitorWindowDesktopLocations.values()].filter((location) => {

    if (String(location?.conversationKey || "").trim() !== key) return false;

    if (!/^\d+$/.test(String(location?.hwnd || "")) || String(location?.hwnd) === "0") return false;

    const observedAt = Number(location?.at || 0), identityAt = Number(location?.identityAt || 0);

    return observedAt > 0 && now - observedAt <= MONITOR_WINDOW_LOCATION_TTL_MS

      && identityAt > 0 && now - identityAt <= MONITOR_WINDOW_LOCATION_TTL_MS;

  });

}
//@@FN_END:monitorFreshNativeLocations

//@@FN_START:monitorNative
function monitorNative(message) {
  return MonitorNativeTrace.request("control", message, () => monitorControlNativeRequest(message));
}
//@@FN_END:monitorNative

//@@FN_START:monitorNativeLaunchIsolated
function monitorNativeLaunchIsolated(message) {

  return monitorControlNativeIsolatedRequest(message);

}
//@@FN_END:monitorNativeLaunchIsolated

//@@FN_START:monitorNativeVisualRead
function monitorNativeVisualRead(message) {

  // Chrome's official one-shot Native Messaging API gives this read one host
  // process and one response. Wallpaper bytes therefore never enter the
  // long-lived control port's mixed FIFO.
  return MonitorNativeTrace.request("control-visual-read", message, () => new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(MONITOR_CONTROL_HOST, message, (response) => {
      const error = chrome.runtime.lastError?.message;
      if (error) reject(new Error(error)); else resolve(response);
    });
  }));

}
//@@FN_END:monitorNativeVisualRead

//@@FN_START:monitorControlNativeIsolatedRequest
function monitorControlNativeIsolatedRequest(message) {

  return new Promise((resolve, reject) => {

    const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

    let settled = false;

    const finish = (fn, value) => {

      if (settled) return;

      settled = true;

      try { port.disconnect(); } catch (_) {}

      fn(value);

    };

    port.onMessage.addListener((response) => {

      if (response?.event === true) return;

      finish(resolve, response);

    });

    port.onDisconnect.addListener(() => {

      if (settled) return;

      finish(reject, new Error(chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료"));

    });

    try { port.postMessage(message); }

    catch (error) { finish(reject, error); }

  });

}
//@@FN_END:monitorControlNativeIsolatedRequest

//@@FN_START:monitorNativeWithTimeout
function monitorNativeWithTimeout(message, timeoutMs = 2500) {

  return new Promise((resolve, reject) => {

    let done = false;

    const timer = setTimeout(() => {

      if (done) return;

      done = true;

      try { monitorNativePort?.disconnect(); } catch (_) {}

      reject(new Error("MONITOR_NATIVE_TIMEOUT"));

    }, Math.max(250, Number(timeoutMs) || 2500));

    monitorNative(message).then((value) => { if (done) return; done = true; clearTimeout(timer); resolve(value); }, (error) => { if (done) return; done = true; clearTimeout(timer); reject(error); });

  });

}
//@@FN_END:monitorNativeWithTimeout

//@@FN_START:stopMonitorBctNativePreview
function stopMonitorBctNativePreview() {
  const token = monitorBctNativePreviewToken;
  monitorBctNativePreviewToken = "";
  if (token) void monitorNative({ type:"monitorDragPreviewStop", token }).catch(() => {});
}
//@@FN_END:stopMonitorBctNativePreview

//@@FN_START:syncMonitorNativeZOrder
async function syncMonitorNativeZOrder(desktopId) {

  const id = String(desktopId || "").trim();

  if (!id) return false;

  const result = await monitorNative({ type: "getDesktopWindows", desktopId: id }).catch(() => null);

  if (!result?.ok || !Array.isArray(result.windows)) return false;

  const zByHwnd = new Map(result.windows.map((item) => {

    const nativeZ = Math.max(0, Number(item?.z) || 0);

    return [String(item?.hwnd || ""), String(10000 - Math.min(nativeZ, 9999))];

  }));

  for (const img of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const nativeZIndex = zByHwnd.get(String(img.dataset.hwnd || ""));

    if (!nativeZIndex) continue;

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");
    syncMonitorStatusLayer(img, img.dataset.hwnd || "");
    syncMonitorPauseOverlay(img, img.dataset.hwnd || "");
    syncMonitorDesktopNumberBadge(img, img.dataset.hwnd || "");
    syncMonitorNonChatCountdown(img, img.dataset.hwnd || "");

  }

  return true;

}
//@@FN_END:syncMonitorNativeZOrder
