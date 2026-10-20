importScripts("browser/tab-focus-adapter.js");

const HOST_NAME = "com.pas40.desktop_window_monitor";
const monitorTabFocusAdapter = globalThis.MonitorTabFocusAdapter.create(chrome);



const DESKTOP_PAGE = chrome.runtime.getURL("desktop.html");



const DESKTOP_SESSION_KEY = "desktopWindowPopupSession";



const DESKTOP_RECOVERY_KEY = "desktopWindowPopupRecovery.v1";



const DESKTOP_TOGGLE_TRACE_KEY = "desktopWindowToggleTrace.v1";

const MONITOR_RELOAD_REQUEST_KEY = "desktopWindowMonitorReloadRequest.v1";
const MONITOR_WINDOW_BOUNDS_KEY = "desktopWindowMonitorBounds.v1";
const MONITOR_WINDOW_MIN_WIDTH = 560;
const MONITOR_WINDOW_MIN_HEIGHT = 420;
const MONITOR_WINDOW_EXPANSION_GUARD_RATIO = 1.55;



const NATIVE_MESSAGE_TYPES = new Set([



  "list", "listDirectory", "open", "readText", "copyFiles", "rename", "moveItems",



  "deleteItems", "undo", "redo", "createFile", "createFolder",



  "captureDesktopAnchor", "hideDesktopAnchor", "restoreDesktopAnchor",



  "hideCleanWindowFrame", "restoreCleanWindowFrame"



]);







const transitionWindowIds = new Set();



let desktopTransitionInProgress = false;


let desktopTransitionPending = false;


let desktopTransitionPendingTab = null;



const closingDesktopWindowIds = new Set();



let desktopSessionMutationChain = Promise.resolve();







let desktopShellNativePort = null;
const desktopShellNativePending = [];

function ensureDesktopShellNativePort() {
  if (desktopShellNativePort) return desktopShellNativePort;
  const port = chrome.runtime.connectNative(HOST_NAME);
  desktopShellNativePort = port;
  port.onMessage.addListener((response) => {
    const pending = desktopShellNativePending.shift();
    if (pending) pending.resolve(response);
  });
  port.onDisconnect.addListener(() => {
    const message = chrome.runtime.lastError?.message || "Desktop file host 연결 종료";
    desktopShellNativePort = null;
    while (desktopShellNativePending.length) desktopShellNativePending.shift().reject(new Error(message));
  });
  return port;
}

function sendToHelper(payload) {



  return new Promise((resolve, reject) => {
    const pending = { resolve, reject };
    desktopShellNativePending.push(pending);
    try { ensureDesktopShellNativePort().postMessage(payload); }
    catch (error) {
      const index = desktopShellNativePending.indexOf(pending);
      if (index >= 0) desktopShellNativePending.splice(index, 1);
      reject(error);
    }
  });



}







function normalizeDesktopSessions(value) {



  if (!value || typeof value !== "object" || Array.isArray(value)) return {};







  // 1.9.3 and older stored one session directly under this key.



  if (Number.isInteger(value.desktopWindowId)) {



    return { [String(value.desktopWindowId)]: value };



  }







  const sessions = {};



  for (const session of Object.values(value)) {



    if (!session || typeof session !== "object" || !Number.isInteger(session.desktopWindowId)) continue;



    sessions[String(session.desktopWindowId)] = session;



  }



  return sessions;



}







async function getDesktopSessions() {



  const stored = await chrome.storage.session.get(DESKTOP_SESSION_KEY);



  const liveSessions = normalizeDesktopSessions(stored?.[DESKTOP_SESSION_KEY]);



  if (Object.keys(liveSessions).length > 0) return liveSessions;







  // chrome.storage.session can be cleared when an unpacked extension is reloaded.



  // Keep a validated recovery mirror so already-open Desktop popups still know



  // which parked Chrome window they belong to after chrome://extensions -> Reload.



  const recoveryStored = await chrome.storage.local.get(DESKTOP_RECOVERY_KEY);



  const recoverySessions = normalizeDesktopSessions(recoveryStored?.[DESKTOP_RECOVERY_KEY]);



  if (Object.keys(recoverySessions).length > 0) {



    await chrome.storage.session.set({ [DESKTOP_SESSION_KEY]: recoverySessions });



  }



  return recoverySessions;



}







async function saveDesktopSessions(sessions) {



  const normalized = normalizeDesktopSessions(sessions);



  if (Object.keys(normalized).length === 0) {



    await Promise.all([



      chrome.storage.session.remove(DESKTOP_SESSION_KEY),



      chrome.storage.local.remove(DESKTOP_RECOVERY_KEY)



    ]);



    return;



  }



  await Promise.all([



    chrome.storage.session.set({ [DESKTOP_SESSION_KEY]: normalized }),



    chrome.storage.local.set({ [DESKTOP_RECOVERY_KEY]: normalized })



  ]);



}







function mutateDesktopSessions(mutator) {



  const operation = desktopSessionMutationChain.then(async () => {



    const sessions = await getDesktopSessions();



    const result = await mutator(sessions);



    await saveDesktopSessions(sessions);



    return result;



  });



  desktopSessionMutationChain = operation.catch(() => {});



  return operation;



}



async function safeGetWindow(windowId, populate = false) {



  if (!Number.isInteger(windowId)) return null;



  try {



    return await chrome.windows.get(windowId, { populate });



  } catch (_) {



    return null;



  }



}







async function safeGetTab(tabId) {



  if (!Number.isInteger(tabId)) return null;



  try {



    return await chrome.tabs.get(tabId);



  } catch (_) {



    return null;



  }



}







function isDesktopPageUrl(url) {



  if (typeof url !== "string") return false;



  return url === DESKTOP_PAGE || url.startsWith(DESKTOP_PAGE + "?") || url.startsWith(DESKTOP_PAGE + "#");



}







function desktopPageUrlForSource(sourceWindowId, sourceTabId, desktopId = null) {



  const url = new URL(DESKTOP_PAGE);



  if (Number.isInteger(sourceWindowId)) url.searchParams.set("sourceWindowId", String(sourceWindowId));



  if (Number.isInteger(sourceTabId)) url.searchParams.set("sourceTabId", String(sourceTabId));



  if (typeof desktopId === "string" && desktopId) url.searchParams.set("desktopId", desktopId);



  return url.toString();



}







function parseDesktopSourceFromUrl(url) {



  if (!isDesktopPageUrl(url)) return null;



  try {



    const parsed = new URL(url);



    const sourceWindowId = Number(parsed.searchParams.get("sourceWindowId"));



    const sourceTabId = Number(parsed.searchParams.get("sourceTabId"));



    return {



      sourceWindowId: Number.isInteger(sourceWindowId) ? sourceWindowId : null,



      sourceTabId: Number.isInteger(sourceTabId) ? sourceTabId : null



    };



  } catch (_) {



    return null;



  }



}







function findDesktopPageTab(popup) {



  if (!popup || popup.type !== "popup" || !Array.isArray(popup.tabs)) return null;



  return popup.tabs.find((tab) => isDesktopPageUrl(tab.url)) || null;



}







function popupContainsExpectedDesktopTab(popup, session) {



  const desktopTab = findDesktopPageTab(popup);



  if (!desktopTab) return false;







  const encoded = parseDesktopSourceFromUrl(desktopTab.url);



  if (Number.isInteger(encoded?.sourceWindowId)



      && Number.isInteger(session?.sourceWindowId)



      && encoded.sourceWindowId !== session.sourceWindowId) {



    return false;



  }



  return true;



}







function getBounds(windowInfo) {



  if (![windowInfo?.left, windowInfo?.top, windowInfo?.width, windowInfo?.height].every(Number.isInteger)) {



    return null;



  }



  return {



    left: windowInfo.left,



    top: windowInfo.top,



    width: windowInfo.width,



    height: windowInfo.height



  };



}

function validMonitorBounds(value) {
  if (!value || ![value.left, value.top, value.width, value.height].every(Number.isInteger)) return null;
  if (value.width < MONITOR_WINDOW_MIN_WIDTH || value.height < MONITOR_WINDOW_MIN_HEIGHT || value.width > 2400 || value.height > 1600) return null;
  return { left:value.left, top:value.top, width:value.width, height:value.height };
}

function defaultMonitorBounds(sourceBounds) {
  const width = Math.max(760, Math.min(1180, Math.round(sourceBounds.width * 0.72)));
  const height = Math.max(560, Math.min(900, Math.round(sourceBounds.height * 0.82)));
  return {
    left: sourceBounds.left + Math.max(16, sourceBounds.width - width - 24),
    top: sourceBounds.top + Math.max(16, Math.round((sourceBounds.height - height) / 2)),
    width,
    height
  };
}

async function monitorPopupBounds(sourceBounds) {
  const stored = await chrome.storage.local.get(MONITOR_WINDOW_BOUNDS_KEY).catch(() => ({}));
  return validMonitorBounds(stored?.[MONITOR_WINDOW_BOUNDS_KEY]) || defaultMonitorBounds(sourceBounds);
}

const MONITOR_POPUP_RUNTIME_KEY = "monitorPopupRuntimeRegistryV1";

async function getMonitorPopupRuntimeRegistry() {
  const stored = await chrome.storage.session.get(MONITOR_POPUP_RUNTIME_KEY).catch(() => ({}));
  const registry = stored?.[MONITOR_POPUP_RUNTIME_KEY];
  return registry && typeof registry === "object" ? registry : {};
}

async function saveMonitorPopupRuntimeRegistry(registry) {
  await chrome.storage.session.set({ [MONITOR_POPUP_RUNTIME_KEY]: registry });
}

async function notifyMonitorPopupTopologyChanged(desktopIds = []) {
  const ids = [...new Set((Array.isArray(desktopIds) ? desktopIds : [desktopIds]).map((value) => String(value || "").trim()).filter(Boolean))];
  const tabs = await chrome.tabs.query({}).catch(() => []);
  await Promise.allSettled((Array.isArray(tabs) ? tabs : [])
    .filter((tab) => Number.isInteger(tab?.id) && isDesktopPageUrl(tab?.url))
    .map((tab) => chrome.tabs.sendMessage(tab.id, { type:"monitor-popup-topology-changed", desktopIds:ids }).catch(() => null)));
}

async function updateMonitorPopupRuntime(windowId, patch = {}, notify = true) {
  if (!Number.isInteger(windowId)) return { ok:false };
  const popup = await safeGetWindow(windowId, true);
  if (!popup || popup.type !== "popup" || !findDesktopPageTab(popup)) return { ok:false };
  const registry = await getMonitorPopupRuntimeRegistry();
  const key = String(windowId);
  const previous = registry[key] && typeof registry[key] === "object" ? registry[key] : {};
  const bounds = getBounds(popup) || previous.bounds || null;
  const hwnd = /^\d+$/.test(String(patch?.hwnd || previous.hwnd || "")) ? String(patch?.hwnd || previous.hwnd) : "";
  const desktopId = String(patch?.desktopId || previous.desktopId || "").trim();
  const state = String(popup.state || previous.state || "normal").toLowerCase();
  const hwndChanged = Boolean(previous.hwnd && hwnd && String(previous.hwnd) !== hwnd);
  const frozenDataUri = String(patch?.frozenDataUri || (hwndChanged ? "" : previous.frozenDataUri) || "");
  const wallpaperDataUri = String(patch?.wallpaperDataUri || previous.wallpaperDataUri || "");
  const next = {
    windowId,
    hwnd,
    desktopId,
    title:"DWM",
    className:"Chrome_WidgetWin_1",
    bounds,
    state,
    iconic:state === "minimized",
    visible:true,
    frozenDataUri,
    frozenAt:frozenDataUri ? Number(patch?.frozenDataUri ? Date.now() : previous.frozenAt || Date.now()) : 0,
    wallpaperDataUri,
    wallpaperAt:wallpaperDataUri ? Number(patch?.wallpaperDataUri ? Date.now() : previous.wallpaperAt || Date.now()) : 0,
    updatedAt:Date.now()
  };
  registry[key] = next;
  await saveMonitorPopupRuntimeRegistry(registry);
  if (notify) await notifyMonitorPopupTopologyChanged([previous.desktopId, next.desktopId]);
  return { ok:true, window:next };
}

async function removeMonitorPopupRuntime(windowId) {
  if (!Number.isInteger(windowId)) return;
  const registry = await getMonitorPopupRuntimeRegistry();
  const key = String(windowId);
  const previous = registry[key];
  if (!previous) return;
  delete registry[key];
  await saveMonitorPopupRuntimeRegistry(registry);
  await notifyMonitorPopupTopologyChanged([previous.desktopId]);
}

async function listMonitorPopupRuntime() {
  const registry = await getMonitorPopupRuntimeRegistry();
  const nextRegistry = {};
  const windows = [];
  for (const [key, row] of Object.entries(registry)) {
    const windowId = Number(key);
    const popup = Number.isInteger(windowId) ? await safeGetWindow(windowId, true) : null;
    if (!popup || popup.type !== "popup" || !findDesktopPageTab(popup)) continue;
    const bounds = getBounds(popup) || row?.bounds || null;
    const hwnd = /^\d+$/.test(String(row?.hwnd || "")) ? String(row.hwnd) : "";
    const desktopId = String(row?.desktopId || "").trim();
    const state = String(popup.state || row?.state || "normal").toLowerCase();
    const current = { ...row, windowId, hwnd, desktopId, bounds, state, iconic:state === "minimized", visible:true, updatedAt:Date.now() };
    nextRegistry[key] = current;
    if (!hwnd || !desktopId || !bounds) continue;
    windows.push({
      hwnd,
      desktopId,
      title:"DWM",
      className:"Chrome_WidgetWin_1",
      left:bounds.left,
      top:bounds.top,
      width:bounds.width,
      height:bounds.height,
      visible:true,
      iconic:current.iconic,
      z:0,
      cloaked:0,
      monitorWindow:true,
      frozenDataUri:String(current.frozenDataUri || ""),
      frozenAt:Number(current.frozenAt || 0),
      wallpaperDataUri:String(current.wallpaperDataUri || ""),
      wallpaperAt:Number(current.wallpaperAt || 0)
    });
  }
  await saveMonitorPopupRuntimeRegistry(nextRegistry);
  return { ok:true, windows };
}

async function registerMonitorPopupWindow(windowId) {
  const popup = await safeGetWindow(windowId, true);
  const currentBounds = getBounds(popup);
  if (!popup || popup.type !== "popup" || !findDesktopPageTab(popup) || !currentBounds) return { ok:false };
  const desiredBounds = await monitorPopupBounds(currentBounds);
  const currentArea = currentBounds.width * currentBounds.height;
  const desiredArea = desiredBounds.width * desiredBounds.height;
  const popupState = String(popup.state || "normal").toLowerCase();
  if (popupState !== "normal") {
    await chrome.windows.update(windowId, { state:"normal" });
    await chrome.windows.update(windowId, desiredBounds);
  } else if (currentArea > desiredArea * MONITOR_WINDOW_EXPANSION_GUARD_RATIO) {
    await chrome.windows.update(windowId, desiredBounds);
  }
  await mutateDesktopSessions((sessions) => {
    const session = sessions[String(windowId)] || { independent:true, desktopWindowId:windowId };
    session.popupBounds = desiredBounds;
    sessions[String(windowId)] = session;
  });
  await chrome.storage.local.set({ [MONITOR_WINDOW_BOUNDS_KEY]: desiredBounds });
  return { ok:true, bounds:desiredBounds };
}

async function saveMonitorPopupWindowBounds(windowId) {
  const popup = await safeGetWindow(windowId, true);
  const bounds = String(popup?.state || "").toLowerCase() === "normal" ? validMonitorBounds(getBounds(popup)) : null;
  if (!popup || popup.type !== "popup" || !findDesktopPageTab(popup) || !bounds) return { ok:false };
  await mutateDesktopSessions((sessions) => {
    const session = sessions[String(windowId)] || { independent:true, desktopWindowId:windowId };
    session.popupBounds = bounds;
    sessions[String(windowId)] = session;
  });
  await chrome.storage.local.set({ [MONITOR_WINDOW_BOUNDS_KEY]: bounds });
  return { ok:true, bounds };
}







function boundsMatch(a, b, tolerance = 2) {



  if (!a || !b) return false;



  return ["left", "top", "width", "height"].every((key) =>



    Number.isInteger(a[key])



    && Number.isInteger(b[key])



    && Math.abs(a[key] - b[key]) <= tolerance



  );



}







async function showSourceWindow(session, preferredBounds = null, focusSource = true) {



  const source = await safeGetWindow(session?.sourceWindowId);



  if (!source) return;







  if (session?.anchorMode === "hidden" && session?.nativeAnchor) {



    let restored = null;



    try {



      restored = await sendToHelper({



        type: "restoreDesktopAnchor",



        ...session.nativeAnchor,



        allowBackgroundRestore: !focusSource



      });



    } catch (_) {



      return;



    }



    if (!restored?.ok || restored.restored !== true) return;



    if (!focusSource || restored.onCurrentDesktop !== true) return;



    try {



      await chrome.windows.update(source.id, { focused: true });



    } catch (_) {



    }



    return;



  }







  // If the user restored/moved the source window while Desktop mode was open,



  // that newer geometry/state wins. For an explicit close, still focus this exact



  // source before the popup is removed; otherwise Windows may foreground some



  // unrelated Chrome window. Quiet recovery passes focusSource=false and never steals focus.



  if (source.state !== "minimized") {



    if (focusSource) {



      try { await chrome.windows.update(source.id, { focused: true }); } catch (_) {}



    }



    return;



  }







  const bounds = preferredBounds || session.popupBounds || session.sourceBounds || null;



  const originalState = session.sourceState || "normal";







  if ((originalState === "maximized" || originalState === "fullscreen")



      && boundsMatch(bounds, session.sourceBounds)) {



    await chrome.windows.update(source.id, { state: originalState, focused: focusSource });



    return;



  }







  await chrome.windows.update(source.id, { state: "normal" });



  if (bounds) await chrome.windows.update(source.id, bounds);



  if (focusSource) await chrome.windows.update(source.id, { focused: true });



}







async function activateOriginalTab(session) {



  const tab = await safeGetTab(session?.sourceTabId);



  if (!tab || tab.windowId !== session?.sourceWindowId) return;



  try {



    await chrome.tabs.update(tab.id, { active: true });



  } catch (_) {



  }



}







async function closeDesktopMode(session, removePopup = true) {



  if (!session) return;







  const popup = await safeGetWindow(session.desktopWindowId);



  const currentPopupBounds = getBounds(popup) || session.popupBounds || session.sourceBounds || null;







  // Remove only this popup's relationship before closing it so onRemoved cannot



  // restore the same source twice. Other Desktop sessions remain untouched.



  await mutateDesktopSessions((sessions) => {



    delete sessions[String(session.desktopWindowId)];



  });







  if (session.independent !== true) {



    await activateOriginalTab(session);



    await showSourceWindow(session, currentPopupBounds);



  }







  if (removePopup && popup) {



    closingDesktopWindowIds.add(popup.id);



    try {



      await chrome.windows.remove(popup.id);



    } catch (_) {



    } finally {



      closingDesktopWindowIds.delete(popup.id);



    }



  }



}







async function appendToggleTrace(event, details = {}) {



  try {



    const stored = await chrome.storage.local.get(DESKTOP_TOGGLE_TRACE_KEY);



    const entries = Array.isArray(stored?.[DESKTOP_TOGGLE_TRACE_KEY])



      ? stored[DESKTOP_TOGGLE_TRACE_KEY]



      : [];



    entries.push({ time: new Date().toISOString(), event, ...details });



    await chrome.storage.local.set({ [DESKTOP_TOGGLE_TRACE_KEY]: entries.slice(-60) });



  } catch (_) {



  }



}







async function getLastFocusedContext() {



  try {



    const windowInfo = await chrome.windows.getLastFocused({ populate: true });



    if (!windowInfo || windowInfo.focused !== true) return { window: null, tab: null };



    const tab = windowInfo.tabs?.find((candidate) => candidate.active) || null;



    return tab ? { window: windowInfo, tab } : { window: null, tab: null };



  } catch (_) {



    return { window: null, tab: null };



  }



}







async function resolveOriginContext(preferredTab = null) {



  if (Number.isInteger(preferredTab?.id) && Number.isInteger(preferredTab?.windowId)) {



    const originWindow = await safeGetWindow(preferredTab.windowId);



    const liveTab = await safeGetTab(preferredTab.id);







    // Origin-first remains the rule. Accept the exact event origin when it is still



    // focused/active, just like the Clean Window fix.



    if (originWindow?.focused === true



        && liveTab?.windowId === originWindow.id



        && liveTab.active === true) {



      return { window: originWindow, tab: liveTab };



    }







    // Extension reload can briefly leave the command callback with stale tab/focus



    // flags. Re-check getLastFocused, but ONLY accept it when it is the same windowId



    // Chrome supplied with the command. Never redirect Alt+M to a different window.



    const fallback = await getLastFocusedContext();



    if (fallback.window?.id === preferredTab.windowId && fallback.window.focused === true) {



      await appendToggleTrace("origin-same-window-recovered", {



        preferredWindowId: preferredTab.windowId,



        preferredTabId: preferredTab.id,



        activeTabId: fallback.tab?.id ?? null



      });



      return fallback;



    }







    await appendToggleTrace("origin-rejected", {



      preferredWindowId: preferredTab.windowId,



      preferredTabId: preferredTab.id,



      originFocused: originWindow?.focused ?? null,



      liveTabActive: liveTab?.active ?? null,



      lastFocusedWindowId: fallback.window?.id ?? null



    });



    return { window: null, tab: null };



  }







  // Callers without an origin tab may use the actual last-focused window.



  return getLastFocusedContext();



}



async function openDesktopMode(source, sourceTab) {



  if (!source || source.type !== "normal" || !Number.isInteger(source.id)) {



    throw new Error("일반 Chrome 창에서만 Desktop Window을 열 수 있습니다.");



  }



  if (!sourceTab || sourceTab.windowId !== source.id) {



    throw new Error("Alt+M를 누른 Chrome 탭을 확인할 수 없습니다.");



  }



  const sourceBounds = getBounds(source);



  if (!sourceBounds) throw new Error("현재 Chrome 창의 위치와 크기를 확인할 수 없습니다.");
  const initialPopupBounds = await monitorPopupBounds(sourceBounds);



  let desktopId = null;



  try {



    const captured = await sendToHelper({ type: "captureDesktopAnchor" });



    if (captured?.ok && typeof captured.desktopId === "string") desktopId = captured.desktopId;



  } catch (_) {}



  let popup = null;



  const session = {



    independent: true,



    sourceWindowId: null,



    sourceTabId: null,



    sourceState: null,



    sourceBounds: null,



    desktopWindowId: null,



    desktopTabId: null,



    popupBounds: initialPopupBounds,



    desktopId



  };



  try {



    // Create the Monitor popup directly. Do not create any temporary browser tab or launcher window.



    popup = await chrome.windows.create({



      url: desktopPageUrlForSource(null, null, desktopId),



      type: "popup",



      focused: true,

      state: "normal",



      ...initialPopupBounds



    });



    if (!Number.isInteger(popup?.id)) throw new Error("Desktop Window을 만들 수 없습니다.");



    session.desktopWindowId = popup.id;



    const popupWithTabs = await safeGetWindow(popup.id, true);



    const desktopTab = findDesktopPageTab(popupWithTabs);



    session.desktopTabId = Number.isInteger(desktopTab?.id) ? desktopTab.id : null;



    session.popupBounds = getBounds(popup) || initialPopupBounds;



    await mutateDesktopSessions((sessions) => { sessions[String(popup.id)] = session; });



    // Source Chrome windows are never removed or minimized here.



    // A temporary launcher window, when used, is owned and cleaned up by AutoHotkey.



  } catch (error) {



    if (Number.isInteger(session.desktopWindowId)) {



      await mutateDesktopSessions((sessions) => { delete sessions[String(session.desktopWindowId)]; }).catch(() => {});



    }



    if (popup?.id != null) {
      try { await chrome.windows.remove(popup.id); } catch (_) {}
    }



    throw error;



  }



}







async function recoverDesktopSessions() {



  const restoreQueue = [];



  const sessions = await mutateDesktopSessions(async (current) => {



    for (const [popupKey, session] of Object.entries(current)) {



      const popupId = Number(popupKey);



      const popup = await safeGetWindow(popupId, true);



      const source = await safeGetWindow(session.sourceWindowId);







      // A recovery mirror can survive a browser restart, so never trust window IDs



      // by themselves. The popup must still contain this extension's Desktop page.



      // Its tab ID may legitimately change across an extension reload; repair that



      // identity in-place instead of restoring an unrelated source window.



      const liveDesktopTab = findDesktopPageTab(popup);



      if (!popup || !popupContainsExpectedDesktopTab(popup, session)) {

        delete current[popupKey];

        if (session?.independent !== true) {

          if (session?.anchorMode === "hidden" && session?.nativeAnchor && source) {

            restoreQueue.push({ session, quiet: true });

          } else if (source?.state === "minimized") {

            restoreQueue.push({ session, quiet: true });

          }

        }

        continue;

      }



      if (Number.isInteger(liveDesktopTab?.id) && liveDesktopTab.id !== session.desktopTabId) {



        session.desktopTabId = liveDesktopTab.id;



        current[popupKey] = session;



      }







      if (!source && session.sourceWindowId != null) {



        // The user intentionally closed the parked source. Keep the Desktop popup



        // alive, but detach it so closing that popup will not recreate a Chrome window.



        session.sourceWindowId = null;



        session.sourceTabId = null;



        current[popupKey] = session;



      }



    }



    return normalizeDesktopSessions(current);



  });







  for (const entry of restoreQueue) {



    const session = entry?.session || entry;



    await showSourceWindow(session, session.popupBounds || session.sourceBounds, false);



  }



  return sessions;



}








async function openDesktopModeFromCommand(preferredTab = null) {



  



  if (desktopTransitionInProgress) {


    desktopTransitionPending = true;


    desktopTransitionPendingTab = preferredTab || desktopTransitionPendingTab;


    await appendToggleTrace("open-queued", { transitionInProgress: true, preferredWindowId: preferredTab?.windowId ?? null, preferredTabId: preferredTab?.id ?? null });


    return;


  }



  desktopTransitionInProgress = true;



  try {



    const { window: originWindow, tab: originTab } = await resolveOriginContext(preferredTab);



    if (!originWindow || !originTab || !Number.isInteger(originWindow.id)) return;



    const sessions = await getDesktopSessions();



    const popupSession = sessions[String(originWindow.id)];



    if (popupSession) {

      await mutateDesktopSessions((latest) => { delete latest[String(originWindow.id)]; });

      await appendToggleTrace("open-cleared-stale-session", { windowId: originWindow.id });

    }



    if (originWindow.type !== "normal") return;



    await openDesktopMode(originWindow, originTab);



  } finally {


    desktopTransitionInProgress = false;


    if (desktopTransitionPending) {


      const queuedTab = desktopTransitionPendingTab;


      desktopTransitionPending = false;


      desktopTransitionPendingTab = null;


      setTimeout(() => { focusOrOpenMonitorFromShortcut(queuedTab).catch(console.error); }, 0);


    }


  }


}

async function focusOrOpenMonitorFromShortcut(preferredTab = null) {
  // Alt+M is a durable entry point. Extension reload can briefly make Chrome's
  // focus/tab payload unavailable, so never silently do nothing in that state.
  const existingTabs = await chrome.tabs.query({});
  const existing = (Array.isArray(existingTabs) ? existingTabs : []).find((tab) => isDesktopPageUrl(tab?.url));
  if (existing && Number.isInteger(existing.windowId)) {
    await chrome.windows.update(existing.windowId, { focused: true }).catch(() => {});
    if (Number.isInteger(existing.id)) await chrome.tabs.update(existing.id, { active: true }).catch(() => {});
    return { ok: true, focusedExisting: true };
  }

  await openDesktopModeFromCommand(preferredTab).catch(() => {});
  const openedTabs = await chrome.tabs.query({});
  const opened = (Array.isArray(openedTabs) ? openedTabs : []).find((tab) => isDesktopPageUrl(tab?.url));
  if (opened) return { ok: true, openedNormal: true };

  const bounds = await monitorPopupBounds(null);
  await chrome.windows.create({ url: DESKTOP_PAGE, type: "popup", focused: true, state: "normal", ...bounds });
  return { ok: true, openedFallback: true };
}







async function closeDesktopFromSender(sender, reason = "page-request") {



  const senderTab = sender?.tab;



  if (!Number.isInteger(senderTab?.id) || !Number.isInteger(senderTab?.windowId)) {



    return { ok: false, error: "missing-sender-tab" };



  }



  if (!isDesktopPageUrl(senderTab.url)) {



    return { ok: false, error: "sender-is-not-desktop-page" };



  }







  const originWindow = await safeGetWindow(senderTab.windowId, true);



  if (!originWindow || originWindow.type !== "popup") {



    return { ok: false, error: "sender-is-not-desktop-popup" };



  }







  if (transitionWindowIds.has(originWindow.id)) {



    return { ok: true, ignored: "transition-in-progress" };



  }



  transitionWindowIds.add(originWindow.id);



  try {



    const sessions = await getDesktopSessions();



    const session = sessions[String(originWindow.id)] || null;



    if (!session) {



      await appendToggleTrace("page-close-no-session", {



        reason,



        windowId: originWindow.id,



        tabId: senderTab.id



      });



      return { ok: false, error: "desktop-session-not-found" };



    }







    await appendToggleTrace("page-close", {



      reason,



      windowId: originWindow.id,



      sourceWindowId: session.sourceWindowId ?? null



    });



    await closeDesktopMode(session, true);



    return { ok: true };



  } finally {



    transitionWindowIds.delete(originWindow.id);



  }



}







function proxyNativeMessage(message, sendResponse) {



  if (!message || !NATIVE_MESSAGE_TYPES.has(message.type)) return false;



  sendToHelper(message)



    .then((response) => sendResponse(response))



    .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));



  return true;



}







async function resumePendingMonitorReload() {
  const stored = await chrome.storage.local.get(MONITOR_RELOAD_REQUEST_KEY);
  const pending = stored?.[MONITOR_RELOAD_REQUEST_KEY];
  if (!pending) return;

  const requestedAtMs = Number(pending?.requestedAtMs || 0);
  const rawTargets = Array.isArray(pending?.tabs)
    ? pending.tabs
    : [{ tabId: pending?.tabId, windowId: pending?.windowId, url: pending?.url }];
  const seen = new Set();
  const targets = rawTargets.map((item) => ({
    tabId: Number(item?.tabId),
    windowId: Number(item?.windowId),
    url: String(item?.url || "")
  })).filter((item) => {
    const hasTab = Number.isInteger(item.tabId) && item.tabId >= 0;
    const hasWindow = Number.isInteger(item.windowId) && item.windowId >= 0;
    if (!hasTab && !hasWindow) return false;
    const key = hasWindow ? `w:${item.windowId}` : `t:${item.tabId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const stale = !targets.length || !requestedAtMs || (Date.now() - requestedAtMs) > 30000;

  if (stale) {
    await chrome.storage.local.remove(MONITOR_RELOAD_REQUEST_KEY);
    return;
  }

  try {
    // Chrome invalidates extension pages during runtime.reload().  Give that
    // transition a short, bounded moment to finish before opening replacement
    // popups, otherwise Chrome can overwrite the repaired page with New Tab.
    await new Promise((resolve) => setTimeout(resolve, 650));
    await Promise.allSettled(targets.map(async (target) => {
      const desiredUrl = isDesktopPageUrl(target.url) ? target.url : DESKTOP_PAGE;
      const bounds = await monitorPopupBounds(null);
      await chrome.windows.create({
        url: desiredUrl,
        type: "popup",
        focused: true,
        state: "normal",
        ...bounds
      });
      // chrome.runtime.reload() can turn an extension page into New Tab after
      // the replacement popup is already open. Wait through that transition,
      // then close only the recorded old Monitor window if it contains no user
      // tabs (only the old DWM page and/or Chrome's blank replacement).
      await new Promise((resolve) => setTimeout(resolve, 1200));
      if (!Number.isInteger(target.windowId) || target.windowId < 0) return;
      const legacyWindow = await safeGetWindow(target.windowId, true);
      const legacyTabs = Array.isArray(legacyWindow?.tabs) ? legacyWindow.tabs : [];
      const isDisposableLegacyWindow = legacyTabs.length > 0 && legacyTabs.every((tab) => {
        const url = String(tab?.url || "");
        return isDesktopPageUrl(url) || /^chrome:\/\/newtab\/?$/i.test(url);
      });
      if (isDisposableLegacyWindow) await chrome.windows.remove(target.windowId).catch(() => {});
    }));
  } catch (_) {
  } finally {
    await chrome.storage.local.remove(MONITOR_RELOAD_REQUEST_KEY);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message?.type === "monitor-register-popup-window") {
    const windowId = Number(sender?.tab?.windowId);
    if (!Number.isInteger(windowId)) { sendResponse({ ok:false }); return false; }
    registerMonitorPopupWindow(windowId)
      .then(sendResponse)
      .catch((error) => sendResponse({ ok:false, error:error?.message || String(error) }));
    return true;
  }

  if (message?.type === "monitor-save-popup-window-bounds") {
    const windowId = Number(sender?.tab?.windowId);
    if (!Number.isInteger(windowId)) { sendResponse({ ok:false }); return false; }
    saveMonitorPopupWindowBounds(windowId)
      .then(sendResponse)
      .catch((error) => sendResponse({ ok:false, error:error?.message || String(error) }));
    return true;
  }

  if (message?.type === "monitor-update-popup-runtime") {
    const windowId = Number(sender?.tab?.windowId);
    if (!Number.isInteger(windowId)) { sendResponse({ ok:false }); return false; }
    updateMonitorPopupRuntime(windowId, { desktopId:message?.desktopId, hwnd:message?.hwnd, frozenDataUri:message?.frozenDataUri, wallpaperDataUri:message?.wallpaperDataUri })
      .then(sendResponse)
      .catch((error) => sendResponse({ ok:false, error:error?.message || String(error) }));
    return true;
  }

  if (message?.type === "monitor-list-popup-runtime") {
    listMonitorPopupRuntime()
      .then(sendResponse)
      .catch((error) => sendResponse({ ok:false, error:error?.message || String(error), windows:[] }));
    return true;
  }

  if (message?.type === "monitor-reload-extension") {
    const tabId = Number(sender?.tab?.id);
    const windowId = Number(sender?.tab?.windowId);
    if (!Number.isInteger(tabId) || tabId < 0) {
      return false;
    }

    chrome.tabs.query({}).then((tabs) => {
      const monitorTabs = (Array.isArray(tabs) ? tabs : [])
        .filter((tab) => Number.isInteger(tab?.id) && isDesktopPageUrl(tab?.url))
        .map((tab) => ({
          tabId: tab.id,
          windowId: Number.isInteger(tab?.windowId) ? tab.windowId : null,
          url: String(tab.url || "")
        }));
      if (!monitorTabs.some((item) => item.tabId === tabId)) {
        monitorTabs.push({
          tabId,
          windowId: Number.isInteger(windowId) ? windowId : null,
          url: String(sender?.tab?.url || "")
        });
      }
      return chrome.storage.local.set({
        [MONITOR_RELOAD_REQUEST_KEY]: {
          tabId,
          windowId: Number.isInteger(windowId) ? windowId : null,
          url: String(sender?.tab?.url || ""),
          tabs: monitorTabs,
          requestedAtMs: Date.now()
        }
      }).then(() => monitorTabs);
    }).then(async (monitorTabs) => {
      // An open extension page is converted by Chrome into a blank New Tab when
      // runtime.reload() runs. Close only dedicated Monitor windows first; the
      // pending recovery record above re-creates each one after the reload.
      const windowIds = [...new Set(monitorTabs.map((item) => item.windowId).filter((id) => Number.isInteger(id) && id >= 0))];
      await Promise.allSettled(windowIds.map(async (monitorWindowId) => {
        const monitorWindow = await safeGetWindow(monitorWindowId, true);
        const tabsInWindow = Array.isArray(monitorWindow?.tabs) ? monitorWindow.tabs : [];
        if (tabsInWindow.length && tabsInWindow.every((tab) => isDesktopPageUrl(tab?.url))) {
          await chrome.windows.remove(monitorWindowId);
        }
      }));
      chrome.runtime.reload();
    }).catch(() => {});
    return false;
  }

  if (message?.type === "monitor-navigate-chat-tab") {
    const tabId = Number(message?.tabId);
    const conversationKey = String(message?.conversationKey || "").trim();
    if (!Number.isInteger(tabId) || tabId < 0 || !/^[0-9a-f-]{20,}$/i.test(conversationKey)) {
      sendResponse({ ok: false, error: "invalid tab or conversation key" });
      return false;
    }
    const url = `https://chatgpt.com/c/${encodeURIComponent(conversationKey)}`;
    chrome.tabs.update(tabId, { url, active: true })
      .then((tab) => sendResponse({ ok: true, tabId: tab?.id ?? tabId, windowId: tab?.windowId ?? null, url }))
      .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
    return true;
  }

  if (message?.type === "monitor-focus-exact-chat-tab") {
    monitorTabFocusAdapter.focus({
      tabId: message?.tabId,
      windowId: message?.windowId,
      conversationKey: message?.conversationKey,
    }).then(sendResponse).catch((error) => sendResponse({
      schema: "monitor.browser.tab-focus.receipt.v1",
      ok: false,
      status: "NOT_APPLIED",
      error: error?.message || String(error),
    }));
    return true;
  }

  if (message?.type === "monitor-close-chat-tab") {



    const tabId=Number(message?.tabId);



    if(!Number.isInteger(tabId)||tabId<0){sendResponse({ok:false,error:"invalid tab id"});return false;}



    chrome.tabs.remove(tabId)



      .then(()=>sendResponse({ok:true,tabId}))



      .catch((error)=>sendResponse({ok:false,error:error?.message||String(error)}));



    return true;



  }



  if (message?.type === "desktop-window-close-request") {



    closeDesktopFromSender(sender, message.reason || "page-request")



      .then((response) => sendResponse(response))



      .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));



    return true;



  }



  return proxyNativeMessage(message, sendResponse);



});







chrome.runtime.onMessageExternal.addListener((message, _sender, sendResponse) => {



  if (message?.type !== "hideCleanWindowFrame" && message?.type !== "restoreCleanWindowFrame") return false;



  return proxyNativeMessage(message, sendResponse);



});











const monitorChatNavigationLastByTab = new Map();

function monitorConversationKeyFromUrl(rawUrl) {
  try {
    const url = new URL(String(rawUrl || ""));
    if (url.hostname !== "chatgpt.com" && url.hostname !== "chat.openai.com") return "";
    const match = url.pathname.match(/^\/c\/([^/?#]+)/);
    return match ? String(match[1] || "").trim() : "";
  } catch (_) {
    return "";
  }
}

async function publishMonitorBrowserVisualChange(tabIdValue, reason, tabHint = null) {
  const tabId = Number(tabIdValue);
  if (!Number.isInteger(tabId) || tabId < 0) return;
  const tab = tabHint || await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.active) return;
  const windowId = Number(tab?.windowId);
  if (!Number.isInteger(windowId)) return;
  chrome.runtime.sendMessage({
    type: "monitor-browser-visual-changed",
    tabId,
    windowId,
    url: String(tab?.url || ""),
    active: true,
    reason: String(reason || "visual-change"),
    at: Date.now()
  }).catch(() => {});
}

async function publishMonitorChatNavigation(tabIdValue, rawUrl, reason, windowIdHint = null, activeHint = null) {
  const tabId = Number(tabIdValue);
  if (!Number.isInteger(tabId) || tabId < 0) return;
  const url = String(rawUrl || "");
  let parsed;
  try { parsed = new URL(url); } catch (_) { return; }
  if (parsed.hostname !== "chatgpt.com" && parsed.hostname !== "chat.openai.com") return;

  const now = Date.now();
  const conversationKey = monitorConversationKeyFromUrl(url);
  const signature = url + "|" + conversationKey;
  const reasonText = String(reason || "navigation");
  const previous = monitorChatNavigationLastByTab.get(tabId);
  // URL changes are deduped. Tab activation is itself a window-identity event.
  if (reasonText !== "tab-activated" && previous?.signature === signature) return;
  monitorChatNavigationLastByTab.set(tabId, { signature, at: now });

  const tab = Number.isInteger(Number(windowIdHint)) && typeof activeHint === "boolean"
    ? null
    : await chrome.tabs.get(tabId).catch(() => null);
  const windowId = Number.isInteger(Number(windowIdHint))
    ? Number(windowIdHint)
    : (Number.isInteger(tab?.windowId) ? tab.windowId : null);
  const active = typeof activeHint === "boolean" ? activeHint : Boolean(tab?.active);
  chrome.runtime.sendMessage({
    type: "monitor-chat-navigation-changed",
    tabId,
    windowId,
    url,
    conversationKey,
    active,
    reason: reasonText,
    at: now
  }).catch(() => {});
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!Object.prototype.hasOwnProperty.call(changeInfo || {}, "url")) return;
  void publishMonitorBrowserVisualChange(tabId, "tab-url", tab);
  void publishMonitorChatNavigation(tabId, changeInfo?.url || tab?.url || "", "tab-url", tab?.windowId, Boolean(tab?.active));
});

chrome.tabs.onActivated.addListener((activeInfo) => {
  const tabId = Number(activeInfo?.tabId);
  if (!Number.isInteger(tabId) || tabId < 0) return;
  chrome.tabs.get(tabId)
    .then((tab) => {
      void publishMonitorBrowserVisualChange(tabId, "tab-activated", tab);
      return publishMonitorChatNavigation(tabId, tab?.url || "", "tab-activated", activeInfo?.windowId, true);
    })
    .catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => {
  monitorChatNavigationLastByTab.delete(Number(tabId));
});

chrome.windows.onFocusChanged.addListener(() => {
  listMonitorPopupRuntime()
    .then((result) => notifyMonitorPopupTopologyChanged((Array.isArray(result?.windows) ? result.windows : []).map((item) => item.desktopId)))
    .catch(() => {});
});

chrome.windows.onBoundsChanged.addListener((windowInfo) => {
  const windowId = Number(windowInfo?.id);
  if (!Number.isInteger(windowId)) return;
  getMonitorPopupRuntimeRegistry()
    .then((registry) => registry?.[String(windowId)] ? updateMonitorPopupRuntime(windowId, {}, true) : null)
    .catch(() => {});
});

chrome.windows.onRemoved.addListener((windowId) => {
  removeMonitorPopupRuntime(windowId).catch(() => {});



  (async () => {



    if (closingDesktopWindowIds.has(windowId)) return;







    const removedPopupSession = await mutateDesktopSessions((sessions) => {



      const popupSession = sessions[String(windowId)] || null;



      if (popupSession) {



        delete sessions[String(windowId)];



        return popupSession;



      }







      for (const [popupKey, session] of Object.entries(sessions)) {



        if (session.sourceWindowId !== windowId) continue;



        // The user intentionally closed this parked original Chrome window.



        // Respect that state instead of recreating it.



        session.sourceWindowId = null;



        session.sourceTabId = null;



        sessions[popupKey] = session;



      }



      return null;



    });







    if (removedPopupSession && removedPopupSession.independent !== true) {



      await activateOriginalTab(removedPopupSession);



      await showSourceWindow(removedPopupSession, removedPopupSession.popupBounds || removedPopupSession.sourceBounds);



    }



  })().catch(console.error);



});







// Keep the Google Monitor shortcut durable across unpacked-extension reloads.



chrome.commands.getAll().then((commands) => {



  const toggle = commands.find((item) => item?.name === "toggle-desktop-window");



  if (toggle && !String(toggle.shortcut || "").trim()) {



    return chrome.commands.update({ name: "toggle-desktop-window", shortcut: "Alt+M" });



  }



  return null;



}).catch(() => {});







chrome.action.onClicked.addListener((tab) => {



  focusOrOpenMonitorFromShortcut(tab).catch(console.error);



});







chrome.commands.onCommand.addListener((command, tab) => {



  if (command === "toggle-desktop-window") {



    appendToggleTrace("command", {



      tabId: tab?.id ?? null,



      windowId: tab?.windowId ?? null,



      url: typeof tab?.url === "string" ? tab.url.slice(0, 180) : null



    }).catch(() => {});



    focusOrOpenMonitorFromShortcut(tab).catch(console.error);



  }



});







resumePendingMonitorReload().catch(() => {});

async function ensureChatGptBootstrapInOpenTabs() {
  const tabs = await chrome.tabs.query({ url: ["https://chatgpt.com/*", "https://chat.openai.com/*"] });
  await Promise.allSettled(tabs
    .filter((tab) => Number.isInteger(tab?.id))
    .map((tab) => chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["google-bootstrap.js"] })));
}

// Manifest content scripts only attach on navigation. Re-inject into already-open
// ChatGPT tabs after an unpacked-extension reload; google-bootstrap owns the
// per-document singleton guard, so normal navigation and this recovery can race safely.
ensureChatGptBootstrapInOpenTabs().catch(() => {});

// Monitor pages are reloaded only by explicit user action.



// Automatic version-sync reload was removed because direct live-folder edits can



// otherwise leave DesktopWindow in a repeated/unfinished loading state.



let monitorBrowserStartupSeen = false;



chrome.runtime.onStartup.addListener(() => {



  monitorBrowserStartupSeen = true;



  saveDesktopSessions({}).catch(console.error);

  ensureChatGptBootstrapInOpenTabs().catch(() => {});



});



setTimeout(() => {



  if (!monitorBrowserStartupSeen) recoverDesktopSessions().catch(console.error);



}, 500);
