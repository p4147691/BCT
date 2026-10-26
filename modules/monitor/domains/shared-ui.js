//@@FN_START:activateMonitorCodexResource
async function activateMonitorCodexResource(worker, row = null) {
  const profileId = monitorCodexResourceProfile(worker);
  if (!monitorIsActionableCodexResource(worker)) return { ok: false, error: "지원되지 않는 Codex 자원" };

  const label = "G-CODEX";
  row?.classList.add("monitor-worker-resource-pending");
  try {
    setMonitorStatus("G-CODEX Codex 앱 열기 요청", true);
    window.location.href = "codex://threads/new";

    let runtime = null;
    let hwnd = "";
    for (let attempt = 0; attempt < 40; attempt += 1) {
      runtime = await monitorNativeLaunchIsolated({ type: "getCodexRuntimeStatus", profileId: "GOOGLE" }).catch(() => null);
      hwnd = String(runtime?.hwnd || "").trim();
      if (/^\d+$/.test(hwnd) && hwnd !== "0") break;
      await new Promise((resolve) => setTimeout(resolve, 125));
    }

    const desktopIds = Array.isArray(monitorDesktopState.desktopIds) ? monitorDesktopState.desktopIds : [];
    const targetDesktopId = String(desktopIds[desktopIds.length - 1] || "").trim();
    if (!/^\d+$/.test(hwnd) || hwnd === "0") throw new Error("G-CODEX 창을 찾지 못했습니다");
    if (!targetDesktopId) throw new Error("마지막 데스크톱을 찾지 못했습니다");

    const moved = await monitorNative({ type: "moveWindowToDesktop", hwnd, desktopId: targetDesktopId }).catch(() => null);
    if (!moved?.ok) throw new Error(moved?.error || "G-CODEX 창을 마지막 데스크톱으로 이동하지 못했습니다");

    setMonitorStatus("G-CODEX 마지막 데스크톱에서 사용 준비됨", true);
    return { ok: true, launched: true, profileId, hwnd, targetDesktopId };
  } catch (error) {
    const message = String(error?.message || error || `${label} 열기 실패`);
    if (row) row.title = `${String(worker?.name || label)} · ${message}`;
    setMonitorStatus(message, false);
    return { ok: false, error: message, profileId };
  } finally {
    row?.classList.remove("monitor-worker-resource-pending");
  }
}
//@@FN_END:activateMonitorCodexResource

//@@FN_START:applyMonitorLiveWindowGeometry
function applyMonitorLiveWindowGeometry(desktopId, snap) {

  const actMeta = monitorActDesktopVisualForDesktop(desktopId);

  if (!actMeta || !snap?.ok) return;

  const vw = Math.max(1, Number(actMeta.previewVirtualWidth) || 1);

  const vh = Math.max(1, Number(actMeta.previewVirtualHeight) || 1);

  const vl = Number(actMeta.previewVirtualLeft || 0), vt = Number(actMeta.previewVirtualTop || 0);

  const rows = new Map((Array.isArray(snap.windows) ? snap.windows : []).map((item) => [String(item?.hwnd || ""), item]));

  const targets = [];

  const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === String(desktopId || ""));

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (visual) targets.push(visual);

  if (String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "") === String(desktopId || "")) targets.push(monitorWindowLayer);

  for (const container of targets) for (const img of container.querySelectorAll(".monitor-desktop-thumb-window[data-hwnd], .monitor-window-preview[data-hwnd]")) {

    const row = rows.get(String(img.dataset.hwnd || ""));

    if (!row) continue;

    if (Boolean(row.iconic)) { img.style.display = "none"; continue; }

    img.style.display = "";

    // getDesktopWindowHandles reports visibility/iconic state but may not include geometry.

    // Never overwrite a valid captured frame with 0x0 when rect fields are absent.

    const hasGeometry = [row.left,row.top,row.width,row.height].every((value) => Number.isFinite(Number(value)))

      && Number(row.width) > 0 && Number(row.height) > 0;

    if (hasGeometry) {

      img.style.left = `${((Number(row.left) - vl) / vw) * 100}%`;

      img.style.top = `${((Number(row.top) - vt) / vh) * 100}%`;

      img.style.width = `${(Number(row.width) / vw) * 100}%`;

      img.style.height = `${(Number(row.height) / vh) * 100}%`;

    }

    syncMonitorStatusLayer(img, img.dataset.hwnd || "");

    syncMonitorPauseOverlay(img, img.dataset.hwnd || "");

    syncMonitorDesktopNumberBadge(img, img.dataset.hwnd || "");

    syncMonitorNonChatCountdown(img, img.dataset.hwnd || "");

  }

}
//@@FN_END:applyMonitorLiveWindowGeometry

//@@FN_START:applyMonitorSharedSelection
function applyMonitorSharedSelection(result) {

  const revision = String(result?.revision || "");

  if (!result?.ok || !revision || monitorSharedSelectionWritePending > 0 || compareMonitorSharedSelectionRevision(revision, monitorSharedSelectionRevision) <= 0) return;

  monitorSharedSelectionRevision = revision;

  monitorSharedSelectionReady = true;

  const sharedDesktopId = String(result.selectedDesktopId || "").trim();

  if (sharedDesktopId) monitorApplySharedDesktopSelection(sharedDesktopId);

  monitorSelectedHwnds.clear();

  for (const value of String(result.hwndsCsv || "").split(",")) {

    const hwnd = value.trim();

    if (/^\d+$/.test(hwnd) && hwnd !== "0") monitorSelectedHwnds.add(hwnd);

  }

  const requested = String(result.highlightedHwnd || "");

  monitorHighlightedHwnd = monitorSelectedHwnds.has(requested) ? requested : ([...monitorSelectedHwnds][0] || "");

  applyMonitorWindowHighlight(monitorHighlightedHwnd, { preserve: true, remote: true });

}
//@@FN_END:applyMonitorSharedSelection

//@@FN_START:applyPersistentMonitorRoleClass
function applyPersistentMonitorRoleClass(node, hwnd) {

  const key = String(hwnd || "");

  const conversationKey = monitorVisualConversationForHwnd(key, monitorLastAiState);

  const identityKnown = Boolean(conversationKey) || Boolean(monitorLastAiState && monitorActNodeNumbersForHwnd(key, monitorLastAiState).length);

  // Identity refresh is asynchronous. Preserve role/question decoration, but never preserve

  // a stale working haze when the exact tab generation telemetry is no longer fresh.

  if (!identityKnown) {

    const liveWorking = monitorLastAiState ? monitorHwndIsGenerating(key, monitorLastAiState) : false;

    node.classList.toggle("monitor-window-working", liveWorking);

    syncMonitorStatusLayer(node, key);
    syncMonitorPauseOverlay(node, key);

    return;

  }

  for (const cls of Object.values(MONITOR_PERSISTENT_ROLE_CLASSES)) node.classList.remove(cls);

  applyMonitorConversationGroupVisual(node, conversationKey, monitorLastAiState);

  const liveRoleClass = conversationKey && monitorLastAiState ? monitorPersistentRoleClass(monitorLiveRoleForConversation(conversationKey, monitorLastAiState, key)) : "";

  if (liveRoleClass) node.classList.add(liveRoleClass);

  const liveWorking = monitorLastAiState ? monitorHwndIsGenerating(key, monitorLastAiState) : false;

  node.classList.toggle("monitor-window-working", liveWorking);

  node.classList.toggle("monitor-window-paused", !liveWorking && monitorPausedByHwnd.has(key));

  syncMonitorStatusLayer(node, key);
  syncMonitorPauseOverlay(node, key);

}
//@@FN_END:applyPersistentMonitorRoleClass

//@@FN_START:attachMonitorContextTitleMenu
function attachMonitorContextTitleMenu(row,worker,state,endpoint){

  const key=String(worker?.conversation_key||endpoint?.conversation_key||"").trim(); if(!key)return;

  row.addEventListener("contextmenu",(event)=>{event.preventDefault();event.stopPropagation(); const ghost=monitorGhostCache.get(key)||{}; const current=monitorContextTitleDisplay(worker,state,endpoint)||String(endpoint?.title||worker?.title||"");

    const next=window.prompt(`작업 제목을 입력하세요.\n\n${monitorLifecycleTooltip(key,endpoint,ghost)}\n\n빈 값: AI 제목 잠금 해제\n/browser: 실제 제목 다시 읽기\n/ai: AI 자동 제목 다시 사용`,current);

    if(next===null)return; const value=String(next).trim(); if(value==="/browser"){resetMonitorContextTitleToBrowser(key);return;} if(value==="/ai"){setMonitorManualContextTitle(key,"");void refreshMonitorContextTitle(worker,state,endpoint,true);return;} if(!value){setMonitorManualContextTitle(key,"");return;}

    const liveState=monitorLastAiState||state;

    const liveEndpoints=(Array.isArray(liveState?.endpoints)?liveState.endpoints:[]).filter((item)=>String(item?.conversation_key||"").trim()===key&&String(item?.presence_state||"").toUpperCase()==="OPEN");

    const liveEndpoint=liveEndpoints.length===1?liveEndpoints[0]:null;

    const titleElement=row.querySelector(".monitor-worker-chat-title"), previousListTitle=String(titleElement?.textContent||current);

    if(titleElement)titleElement.textContent=value;

    setMonitorStatus(`제목 변경 확인 중 · ${value}`,true,12000);

    void requestMonitorConversationRename(key,value,liveEndpoint,true).then((ok)=>{

      const latest=monitorContextTitleRecord(key);

      if(ok==="pending")setMonitorStatus(`제목 저장됨 · 반영 확인 중 · ${value}`,true,12000);

      else if(ok)setMonitorStatus(`제목 변경 완료 · ${value}`,true,1500);

      else { if(titleElement?.isConnected)titleElement.textContent=previousListTitle; setMonitorStatus(`제목 변경 실패 · ${String(latest.rename_error||"RENAME_FAILED")}`,false,6000); }

    }).catch((error)=>{if(titleElement?.isConnected)titleElement.textContent=previousListTitle;setMonitorStatus(`제목 변경 실패 · ${String(error?.message||error||"RENAME_FAILED")}`,false,6000);});

  });

}
//@@FN_END:attachMonitorContextTitleMenu

//@@FN_START:checkMonitorDeploymentUpdate
async function checkMonitorDeploymentUpdate() {

  if (monitorDeploymentCheckBusy) {
    monitorDeploymentCheckQueued = true;
    return;
  }

  monitorDeploymentCheckBusy = true;

  try {

    const info = await monitorNative({ type: "getDeploymentInfo" });

    const running = chrome.runtime.getManifest().version;

    const reloadToken = String(info?.reloadToken || "");

    const publishedVersion = String(info?.version || "");
    const versionMismatch = Boolean(
      publishedVersion && publishedVersion.localeCompare(
        String(running), undefined, { numeric: true, sensitivity: "base" }
      ) !== 0
    );

    if (versionMismatch) {
      setMonitorStatus(`업데이트 ${publishedVersion} 감지 · 설치본 재로드 중`, false);
      if (!monitorDeploymentReloadRequested) {
        monitorDeploymentReloadRequested = true;
        chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {
          monitorDeploymentReloadRequested = false;
        });
      }
      return;
    }

    if (monitorReloadToken === null) {

      monitorReloadToken = reloadToken;

    } else if (reloadToken && reloadToken !== monitorReloadToken) {

      if (!monitorDeploymentReloadRequested) {
        monitorDeploymentReloadRequested = true;
        setMonitorStatus("새 설치본 감지 · 설치본 재로드 중", false);
        chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {
          monitorDeploymentReloadRequested = false;
        });
      }
      return;

    }

    if (reloadToken && monitorReloadToken === reloadToken && monitorInitialThumbBatchDone &&
        monitorReloadAckToken !== reloadToken) {
      const ack = await monitorNative({ type: "ackExtensionReload", token: reloadToken }).catch(() => null);
      if (ack?.ok === true) monitorReloadAckToken = reloadToken;
    }

    // A reload can recreate the popup after its HWND-change event has already
    // run. Publish one fresh presence record once the token is known; this is
    // a startup/deployment event, not a timer or a background polling loop.
    if (reloadToken && monitorReloadToken === reloadToken) {
      await monitorPublishSharedInstance("deployment-token-ready");
    }
    monitorDeploymentReloadRequested = false;

  } catch (_) {} finally {
    monitorDeploymentCheckBusy = false;
    if (monitorDeploymentCheckQueued) {
      monitorDeploymentCheckQueued = false;
      queueMicrotask(() => { void checkMonitorDeploymentUpdate(); });
    }
  }

}
//@@FN_END:checkMonitorDeploymentUpdate

//@@FN_START:compareMonitorSharedSelectionRevision
function compareMonitorSharedSelectionRevision(leftValue, rightValue) { return globalThis.MonitorDomainAPIs["shared-ui"]["compareMonitorSharedSelectionRevision"].apply(this, arguments); }
//@@FN_END:compareMonitorSharedSelectionRevision

//@@FN_START:createMonitorContextContinueButton
function createMonitorContextContinueButton(item) {
  const captured = { ...item };
  return globalThis.MonitorContextResume.createButton({
    target: captured,
    fetcher: actFetch,
    openConversation: () => restoreMonitorDetachedTask(captured, document.createElement('button')),
  });
}
//@@FN_END:createMonitorContextContinueButton

//@@FN_START:ensureMonitorOwnFrozenSnapshot
async function ensureMonitorOwnFrozenSnapshot() {
  const hwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();
  const desktopId = String(monitorDesktopState.hostDesktopId || "").trim();
  if (!monitorIsActiveDesktopRenderer()) {
    monitorOwnFrozenCaptureAttemptedHwnd = "";
    return false;
  }
  if (!/^\d+$/.test(hwnd) || hwnd === "0" || !desktopId) return false;
  if (monitorOwnFrozenCaptureHwnd === hwnd) return true;
  if (monitorOwnFrozenCaptureAttemptedHwnd === hwnd || monitorOwnFrozenCaptureBusy) return false;

  monitorOwnFrozenCaptureAttemptedHwnd = hwnd;
  monitorOwnFrozenCaptureBusy = true;
  try {
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (String(monitorDesktopState.hostWindowHwnd || "") !== hwnd || !monitorIsActiveDesktopRenderer()) return false;

    const runtime = await chrome.runtime.sendMessage({ type:"monitor-list-popup-runtime" }).catch(() => null);
    const existing = (Array.isArray(runtime?.windows) ? runtime.windows : [])
      .find((item) => String(item?.hwnd || "") === hwnd);
    if (String(existing?.frozenDataUri || "").startsWith("data:image/")) {
      monitorOwnFrozenCaptureHwnd = hwnd;
      return true;
    }

    // Startup capture can race the popup becoming WGC-ready. Retry only this HWND
    // a bounded number of times; there is no recurring timer or background polling.
    const retryDelays = [0, 160, 420];
    for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
      if (retryDelays[attempt] > 0) await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
      if (String(monitorDesktopState.hostWindowHwnd || "") !== hwnd || !monitorIsActiveDesktopRenderer()) return false;
      const capture = await monitorCoreNative({
        type:"captureWindow",
        hwnd,
        maxWidth:960,
        maxHeight:540,
        quality:68,
        reason:"monitor-self-frozen"
      }).catch(() => null);
      const dataUri = capture?.ok && capture?.captureEngine === "wgc-oneshot" ? String(capture.dataUri || "") : "";
      if (!dataUri.startsWith("data:image/")) continue;

      const saved = await chrome.runtime.sendMessage({
        type:"monitor-update-popup-runtime",
        desktopId,
        hwnd,
        frozenDataUri:dataUri
      }).catch(() => null);
      if (!saved?.ok) continue;
      monitorOwnFrozenCaptureHwnd = hwnd;
      return true;
    }
    return false;
  } finally {
    monitorOwnFrozenCaptureBusy = false;
  }
}
//@@FN_END:ensureMonitorOwnFrozenSnapshot

//@@FN_START:flushMonitorBrowserVisualRefresh
async function flushMonitorBrowserVisualRefresh() {
  if (monitorBrowserVisualRefreshInFlight) return;
  monitorBrowserVisualRefreshInFlight = true;
  try {
    const windowIds = [...monitorBrowserVisualPendingWindowIds];
    monitorBrowserVisualPendingWindowIds.clear();
    if (!windowIds.length) return;

    const hwnds = new Set();
    const desktopIds = new Set();
    for (const browserWindowId of windowIds) {
      const hwnd = monitorHwndForBrowserWindowId(browserWindowId, monitorLastAiState);
      if (!hwnd) continue;
      hwnds.add(hwnd);
      const desktopId = String(monitorWindowDesktopLocations.get(hwnd)?.desktopId || "");
      if (desktopId) desktopIds.add(desktopId);
    }

    // Generic Chrome windows may not have an ACT browser-node mapping. In that case,
    // reconcile the currently known desktops once rather than introducing polling.
    if (!desktopIds.size) {
      for (const desktopId of monitorDesktopState.desktopIds || []) {
        const key = String(desktopId || "");
        if (key) desktopIds.add(key);
      }
    }
    if (!desktopIds.size) return;

    if (hwnds.size) {
      for (const hwnd of hwnds) monitorThumbnailService.invalidate(hwnd);
    } else {
      for (const [hwnd, location] of monitorWindowDesktopLocations.entries()) {
        if (desktopIds.has(String(location?.desktopId || ""))) monitorThumbnailService.invalidate(hwnd);
      }
    }

    invalidateMonitorDesktopFrames(...desktopIds);

    const selectedDesktopId = String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "");
    if (selectedDesktopId && desktopIds.has(selectedDesktopId)) {
      await refreshSelectedThumb().catch(() => false);
    }
    const backgroundIds = [...desktopIds].filter((desktopId) => desktopId !== selectedDesktopId);
    if (backgroundIds.length) await refreshBackgroundThumbs(...backgroundIds).catch(() => []);
  } finally {
    monitorBrowserVisualRefreshInFlight = false;
    if (monitorBrowserVisualPendingWindowIds.size && !monitorBrowserVisualRefreshTimer) {
      monitorBrowserVisualRefreshTimer = setTimeout(() => {
        monitorBrowserVisualRefreshTimer = 0;
        void flushMonitorBrowserVisualRefresh();
      }, MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS);
    }
  }
}
//@@FN_END:flushMonitorBrowserVisualRefresh

//@@FN_START:flushMonitorPopupTopologyRefresh
async function flushMonitorPopupTopologyRefresh() {
  if (monitorPopupTopologyRefreshInFlight) return;
  monitorPopupTopologyRefreshInFlight = true;
  try {
    const desktopIds = [...monitorPopupTopologyPendingDesktopIds];
    monitorPopupTopologyPendingDesktopIds.clear();
    if (!desktopIds.length || !monitorDesktopState.hostDesktopId || monitorDesktopState.hostDesktopId !== monitorDesktopState.currentDesktopId) return;
    invalidateMonitorDesktopFrames(...desktopIds);
    for (const desktopId of desktopIds) {
      const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === desktopId);
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (visual?.isConnected) await refreshDesktopThumb(visual, desktopId).catch(() => false);
    }
    const selectedDesktopId = String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "");
    if (selectedDesktopId && desktopIds.includes(selectedDesktopId)) await refreshObservedWindows().catch(() => false);
  } finally {
    monitorPopupTopologyRefreshInFlight = false;
    if (monitorPopupTopologyPendingDesktopIds.size && !monitorPopupTopologyRefreshTimer) {
      monitorPopupTopologyRefreshTimer = setTimeout(() => {
        monitorPopupTopologyRefreshTimer = 0;
        void flushMonitorPopupTopologyRefresh();
      }, MONITOR_POPUP_TOPOLOGY_REFRESH_DEBOUNCE_MS);
    }
  }
}
//@@FN_END:flushMonitorPopupTopologyRefresh

//@@FN_START:handleMonitorForegroundChangedEvent
function handleMonitorForegroundChangedEvent(event) {
  const hwnd=String(event?.hwnd||"").trim();
  const desktopId=String(event?.desktopId||"").trim();
  if(!/^\d+$/.test(hwnd)||hwnd==="0"||!desktopId)return;
  const visibleNode=document.querySelector(`.monitor-desktop-thumb-window[data-hwnd="${hwnd}"], .monitor-window-preview[data-hwnd="${hwnd}"]`);
  if(!visibleNode)return;
  monitorAcknowledgePostWorkForHwnd(hwnd);
  applyMonitorWindowHighlight(hwnd);
  void syncMonitorNativeZOrder(desktopId);
}
//@@FN_END:handleMonitorForegroundChangedEvent

//@@FN_START:monitorAdoptLocalLlmControlPayload
function monitorAdoptLocalLlmControlPayload(payload, render = true) {
  if (!payload || typeof payload !== "object") return;
  monitorLocalLlmControlState = payload;

  if (Array.isArray(payload.llm_nodes)) {
    monitorCachedLlmNodes = payload.llm_nodes;
    if (monitorLastAiState && typeof monitorLastAiState === "object") {
      monitorLastAiState = { ...monitorLastAiState, llm_nodes: payload.llm_nodes };
    }
  }

  monitorUpdateLocalLlmToggleButtons();
  if (render && monitorLastAiState) renderWorkers(monitorLastAiState);
  if (render && monitorStructurePanel?.isConnected && monitorStructurePanel.style.display !== "none") {
    renderMonitorStructure();
  }
}
//@@FN_END:monitorAdoptLocalLlmControlPayload

//@@FN_START:monitorApplyDirectUserClick
function monitorApplyDirectUserClick(message, sender) {

  const key=String(message?.conversationKey||"").trim();

  const tabId=String(message?.sourceTabId ?? sender?.tab?.id ?? "").trim();

  const profile=String(message?.profile||"").trim().toUpperCase();

  if (!key) return false;

  // A trusted click came from this exact ChatGPT conversation. Acknowledge the

  // conversation immediately; tab/HWND resolution below is only for clearing

  // the matching physical-window overlay and must not block the acknowledgement.

  monitorAcknowledgePostWork(key, "");

  if (!tabId || !monitorLastAiState) { if (monitorLastAiState) renderWorkers(monitorLastAiState); return true; }

  const candidates=(Array.isArray(monitorLastAiState?.endpoints)?monitorLastAiState.endpoints:[]).filter((endpoint)=>

    String(endpoint?.presence_state||"").toUpperCase()==="OPEN"

    && String(endpoint?.tab_id??"").trim()===tabId

    && (!profile || String(endpoint?.profile_id||"").trim().toUpperCase()===profile)

    && String(endpoint?.conversation_key||"").trim()===key

  );

  if (candidates.length!==1) { renderWorkers(monitorLastAiState); return true; }

  const endpoint=candidates[0];

  const location=monitorLocationForEndpoint(endpoint);

  const hwnd=String(location?.hwnd || endpointOsWindowHandle(endpoint) || "").trim();

  if (!/^\d+$/.test(hwnd) || hwnd==="0") { renderWorkers(monitorLastAiState); return true; }

  monitorAcknowledgePostWorkForHwnd(hwnd);

  applyMonitorWindowHighlight(hwnd);
  const desktopId=String(location?.desktopId||"").trim();
  if(desktopId)setTimeout(()=>{ void syncMonitorNativeZOrder(desktopId); },0);

  return true;

}
//@@FN_END:monitorApplyDirectUserClick

//@@FN_START:monitorApplyRoleMode
async function monitorApplyRoleMode(worker,state) {

  const mode=monitorRoleAssignMode; const key=String(worker?.conversation_key||"").trim();

  if(!mode||!key||monitorRoleMutationInFlight.has(key))return;

  monitorRoleMutationInFlight.add(key);

  try {

    if(mode==="EXEMPT") {

      const ep=monitorExactOpenEndpoint(state,key); if(!ep) throw new Error("ENDPOINT_AMBIGUOUS");

      const body={conversation_key:key,transport_instance_id:ep.transport_instance_id,session_id:ep.session_id,tab_id:ep.tab_id};

      const {r,data}=await monitorBootstrapExempt(body);

      if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);

      monitorRoleAssignMode=""; setMonitorStatus("열외 지정됨",true);

    } else {

      await refreshMonitorRoleAdmin();

      const roleRow=(monitorRoleAdminState?.roles||[]).find((x)=>String(x?.role_id||"")===mode); if(!roleRow)throw new Error("ROLE_STATE_UNAVAILABLE");

      const occupant=String(roleRow?.occupant?.conversation_key||""); if(occupant===key){setMonitorStatus(`${monitorRoleAdminShort(mode)} 이미 지정됨`,true);monitorRoleAssignMode="";return;}

      const action=occupant?"replace":"assign"; const body=monitorRoleAdminPayload(action,roleRow,key);

      const r=await fetch(monitorRoleAdminPath(action),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); const data=await r.json();

      if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);

      monitorRoleAssignMode=""; setMonitorStatus(`${monitorRoleAdminShort(mode)} 지정됨`,true);

    }

    await refreshMonitorRoleAdmin(); await refreshAiMonitor();

  } catch(error){ setMonitorStatus(`역할 변경 실패 · ${monitorRoleAdminErrorText(error?.message||error)}`,false); }

  finally { monitorRoleMutationInFlight.delete(key); if(monitorLastAiState)renderWorkers(monitorLastAiState); }

}
//@@FN_END:monitorApplyRoleMode

//@@FN_START:monitorBootstrapExempt
async function monitorBootstrapExempt(body){
  const r=await actFetch(ORCHESTRATOR_BOOTSTRAP_EXEMPT_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);
  return {r,data};
}
//@@FN_END:monitorBootstrapExempt

//@@FN_START:monitorBrowserLineageKey
function monitorBrowserLineageKey(endpoint) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorBrowserLineageKey"].apply(this, arguments); }
//@@FN_END:monitorBrowserLineageKey

//@@FN_START:monitorCanonicalJsonValue
function monitorCanonicalJsonValue(value) {
  if (Array.isArray(value)) return value.map(monitorCanonicalJsonValue);
  if (!value || typeof value !== "object") return value;
  const result = {};
  for (const key of Object.keys(value).sort()) {
    // confirmed_at was a write-only observation timestamp. Updating it during
    // projection made an unchanged binding look different on every render.
    if (key === "confirmed_at") continue;
    result[key] = monitorCanonicalJsonValue(value[key]);
  }
  return result;
}
//@@FN_END:monitorCanonicalJsonValue

//@@FN_START:monitorCanonicalPhysicalLocation
function monitorCanonicalPhysicalLocation(worker, state, now = Date.now()) {

  const endpoint = worker?.__endpoint || null;

  const key = String(worker?.conversation_key || endpoint?.conversation_key || "").trim();

  const projected=monitorActBrowserNode(worker,state);

  const projectedParts=monitorNodeIdentityParts(projected?.node_label, projected?.desktop_id);

  if(projectedParts.nodeNumber&&String(projected?.location_authority||"")==="ACT_NATIVE_OBSERVER"){

    const current={status:"MAPPED",label:projectedParts.displayLabel,desktop:projectedParts.desktop,slot:projectedParts.nodeNumber,hwnd:String(projected?.hwnd||""),reason:"ACT_NODE_STATE",endpoint,actNode:projected,location:{desktop:projectedParts.desktop,desktopId:String(projected?.desktop_id||""),hwnd:String(projected?.hwnd||"")}};
    const change=monitorNodeChatChangeState(worker,state,current);
    if(change?.changed){
      const binding=change.binding||{};
      return {...current,status:"CHAT_CHANGED",previousConversationKey:String(binding.conversation_key||""),currentConversationKey:key,nodeBinding:binding,nodeChange:true,reason:"ACT_CANONICAL_CHAT_CHANGED"};
    }
    return current;

  }

  // An ACT projection confirms a canonical number when available, but it must
  // not suppress the tab + conversation-key recovery path below.  Organization
  // synchronization is presentation metadata, not browser-node identity.

  const resolved = monitorExactConversationWindow(key, state, now, endpoint);

  const inheritedLocation = resolved.location || monitorPhysicalWindowPeerLocation(endpoint, state, now);

  if (inheritedLocation) {

    const desktop = Number(inheritedLocation.desktop);

    const actNode = monitorActBrowserNode(worker, state);

    const actParts = monitorNodeIdentityParts(actNode?.node_label, actNode?.desktop_id || inheritedLocation.desktopId);

    const slot = actParts.nodeNumber;

    const label = slot ? `N${slot} · D${desktop}` : "";

    const current = { status: slot ? "MAPPED" : "DESKTOP_ONLY", label, desktop, slot, hwnd: String(inheritedLocation.hwnd), reason: slot ? "" : "ACT_NODE_NUMBER_PENDING", endpoint: resolved.endpoint || endpoint, location: inheritedLocation };

    const endpointTabId = Number(endpoint?.tab_id || 0);

    const canonicalNodeId = endpointTabId && key ? `tab:${endpointTabId}:chat:${key}` : "";

    const actConversationKey = String(actNode?.conversation_key || actNode?.current_conversation_key || "").trim();

    if (slot && actConversationKey === key && canonicalNodeId && String(actNode?.browser_node_id || "") === canonicalNodeId) {

      return { ...current, status:"MAPPED", label:`N${slot} · D${desktop}`, desktop, slot, reason:"ACT_CANONICAL_IDENTITY", actNode };

    }

    const change = monitorNodeChatChangeState(worker, state, current);

    if (change?.changed) return { ...current, status:"CHAT_CHANGED", previousConversationKey:String(change.binding?.conversation_key||""), currentConversationKey:key, nodeBinding:change.binding||null, nodeChange:true, reason:"ACT_NODE_NUMBER_PENDING_CHAT_CHANGED" };

    // Node numbering authority is ACT only. Physical location and local bindings
    // may describe where a node is, but they never manufacture or restore a slot.

    return current;

  }

  const actNode = monitorActBrowserNode(worker, state);

  const actLabel = String(actNode?.node_label || "").trim().toUpperCase();

  const actParts = monitorNodeIdentityParts(actLabel, actNode?.desktop_id);

  const actConversationKey = String(actNode?.conversation_key || actNode?.current_conversation_key || "").trim();

  const endpointTabId = Number(endpoint?.tab_id || 0);

  const canonicalNodeId = endpointTabId && key ? `tab:${endpointTabId}:chat:${key}` : "";

  if (actParts.nodeNumber && actConversationKey === key && (!canonicalNodeId || String(actNode?.browser_node_id || "") === canonicalNodeId)) {

    return { status:"MAPPED", label:actParts.displayLabel, desktop:actParts.desktop, slot:actParts.nodeNumber, hwnd:String(actNode?.hwnd||""), reason:"ACT_CANONICAL_IDENTITY", endpoint, actNode };

  }

  const previous = key ? monitorLastKnownNodeLocations.get(key) : null;

  if (previous && now - Number(previous.confirmedAt || 0) <= MONITOR_NODE_CHECKING_TTL_MS) return { ...previous, status: "CHECKING", reason: resolved.reason || "TRANSIENT_LOCATION_LOSS" };

  // Historical binding/ghost state never restores a node number.

  if (actNode && canonicalNodeId && String(actNode?.browser_node_id || "") === canonicalNodeId && actConversationKey === key) {
    return { status:"MAPPED", label:actLabel, desktop:null, slot:null, hwnd:String(actNode?.hwnd || ""), reason:"ACT_CANONICAL_IDENTITY_LOCATION_PENDING", endpoint, actNode, locationPending:true };
  }

  return { status:"UNMAPPED", label:"UNMAPPED", desktop:null, slot:null, hwnd:"", reason:resolved.reason };

}
//@@FN_END:monitorCanonicalPhysicalLocation

//@@FN_START:monitorCaptureDataUriToObjectUrl
function monitorCaptureDataUriToObjectUrl(dataUri) {
  const source = String(dataUri || "");
  const match = /^data:([^;,]+);base64,(.+)$/.exec(source);
  if (!match) return source;
  const binary = atob(match[2]);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const objectUrl = URL.createObjectURL(new Blob([bytes], { type:match[1] || "image/jpeg" }));
  monitorRenderDiagnostics.blobCreates += 1;
  return objectUrl;
}
//@@FN_END:monitorCaptureDataUriToObjectUrl

//@@FN_START:monitorCaptureMatchesCurrentWindow
function monitorCaptureMatchesCurrentWindow(captureTitle,currentTitle,capturedAt,now=Date.now()){
  const age=Number(now)-Number(capturedAt||0);
  return Boolean(String(captureTitle||"").trim())
    && String(captureTitle||"").trim()===String(currentTitle||"").trim()
    && Number.isFinite(age)&&age>=0&&age<=MONITOR_WINDOW_CAPTURE_MAX_AGE_MS;
}
//@@FN_END:monitorCaptureMatchesCurrentWindow

//@@FN_START:monitorCapturePaused
function monitorCapturePaused() {
  return Boolean(monitorWindowPointerDrag || monitorDesktopPointerDrag);
}
//@@FN_END:monitorCapturePaused

//@@FN_START:monitorCaptureRebootSnapshot
function monitorCaptureRebootSnapshot(state) {
  if (!MONITOR_FEATURE_RECOVERY_ENABLED) return;
  if (!monitorRebootSnapshotReady || monitorRebootRestoreActive || !state) return;
  // Prior-boot snapshots are history only. Never merge them into current live state automatically.
  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];
  const items = [];
  for (const worker of monitorWorkersForState(state)) {
    if (classifyMonitorWorker(worker) !== "chatgpt") continue;
    const key = String(worker?.conversation_key || "").trim();
    const profile = String(worker?.profile_id || "").toUpperCase();
    if (!key || !["GOOGLE", "NAVER"].includes(profile)) continue;
    const endpoint = endpoints.find((ep) =>
      String(ep?.conversation_key || "").trim() === key
      && String(ep?.presence_state || "").toUpperCase() === "OPEN"
    ) || null;
    if (!endpoint) continue;
    const node = monitorActBrowserNode(worker, state);
    const parts = monitorNodeIdentityParts(node?.node_label, node?.desktop_id);
    if (!parts.nodeNumber || !parts.desktop) continue;
    const rec = monitorContextTitleRecord(key);
    const ghost = monitorGhostCache.get(key) || {};
    const display = monitorContextTitleDisplay(worker, state, endpoint)
      || String(rec.verified_title || "").trim()
      || (rec.manual_locked && String(rec.manual_title || "").trim())
      || String(rec.context_title || "").trim()
      || ghost.meaningful_title
      || endpoint.title
      || key.slice(0, 8);
    items.push({
      conversation_key: key,
      profile_id: profile,
      node_label: parts.displayLabel,
      desktop: parts.desktop,
      slot: parts.nodeNumber,
      desktop_id: String(node?.desktop_id || ""),
      browser_node_id: String(node?.browser_node_id || ""),
      title: String(endpoint?.title || ghost.title || ""),
      meaningful_title: String(display || "").slice(0, 96),
      first_seen_ms: monitorGhostTime(endpoint?.first_seen_at) || 0,
      closed_at_ms: monitorGhostTime(endpoint?.closed_at) || 0,
    });
  }
  if (!items.length) return;
  items.sort((a, b) => a.desktop - b.desktop || a.slot - b.slot);
  const previousItems = (Array.isArray(monitorRebootSnapshot?.items) ? monitorRebootSnapshot.items : []).map((item) => ({
    conversation_key: String(item?.conversation_key || ""),
    profile_id: String(item?.profile_id || ""),
    node_label: String(item?.node_label || ""),
    desktop: Number(item?.desktop || 0),
    slot: Number(item?.slot || 0),
    desktop_id: String(item?.desktop_id || ""),
    browser_node_id: String(item?.browser_node_id || ""),
    title: String(item?.title || ""),
    meaningful_title: String(item?.meaningful_title || ""),
    first_seen_ms: Number(item?.first_seen_ms || 0),
    closed_at_ms: Number(item?.closed_at_ms || 0),
  }));
  if (JSON.stringify(previousItems) === JSON.stringify(items)) return;
  const capturedAt = Date.now();
  monitorRebootSnapshot = {
    captured_at_ms: capturedAt,
    items: items.map((item) => ({ ...item, captured_at_ms: capturedAt })),
  };
  chrome.storage.local.set({ [MONITOR_REBOOT_SNAPSHOT_KEY]: monitorRebootSnapshot });
  monitorPublishSharedRebootSnapshot();
}
//@@FN_END:monitorCaptureRebootSnapshot

//@@FN_START:monitorChatTransitionIsApproved
function monitorChatTransitionIsApproved(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); return Boolean(key&&monitorApprovedChatTransitions.has(key));

}
//@@FN_END:monitorChatTransitionIsApproved

//@@FN_START:monitorChatTransitionKey
function monitorChatTransitionKey(nodeIdentityKey, profileId, oldKey, newKey) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorChatTransitionKey"].apply(this, arguments); }
//@@FN_END:monitorChatTransitionKey

//@@FN_START:monitorChooseCaptureView
function monitorChooseCaptureView(input, settings) {
  // The layout module owns the normal last-good policy. Keep a minimal,
  // non-throwing fallback so a partially copied presentation payload cannot
  // abort the whole thumbnail render loop before the deployment gate rejects
  // that inconsistent payload.
  const chooser = globalThis.MonitorUiLayout?.chooseCaptureView;
  if (typeof chooser === "function") return chooser(input, settings);
  const now = Number.isFinite(input?.now) ? Number(input.now) : Date.now();
  const source = String(input?.nextSource || "");
  if (String(input?.nextState || "") === "captured" &&
      (source.startsWith("blob:") || source.startsWith("data:image/"))) {
    const observedAt = Number(input?.nextCapturedAt || 0);
    return {state:"captured",source,capturedAt:
      Number.isFinite(observedAt) && observedAt > 0 && observedAt <= now ? observedAt : now,label:""};
  }
  return {state:"placeholder",source:"",capturedAt:0,label:""};
}
//@@FN_END:monitorChooseCaptureView

//@@FN_START:monitorContextTitleDisplay
function monitorContextTitleDisplay(worker, state, endpoint = null) {

  const key=String(worker?.conversation_key||endpoint?.conversation_key||"").trim(); const rec=monitorContextTitleRecord(key);

  const pendingTitle=String(rec.rename_pending_title||"").trim(), pendingAt=Number(rec.rename_pending_at_ms||0);

  if(pendingTitle&&pendingAt>0&&Date.now()-pendingAt<65000) return pendingTitle;

  const liveTitle=String(endpoint?.presence_state||"").toUpperCase()==="OPEN" ? String(endpoint?.title||"").trim() : "";

  if(liveTitle) return liveTitle;

  const sharedVerified=String(rec.verified_title||"").trim();

  if(sharedVerified) return sharedVerified;

  if(rec.manual_locked && String(rec.manual_title||"").trim()) return String(rec.manual_title).trim();

  if(String(rec.context_title||"").trim()) return String(rec.context_title).trim();

  return monitorWorkerContextTitle(worker,state,endpoint);

}
//@@FN_END:monitorContextTitleDisplay

//@@FN_START:monitorContextTitleDisplayFromRecord
function monitorContextTitleDisplayFromRecord(rec, liveTitle = "", fallbackTitle = "") {
  const pendingTitle=String(rec?.rename_pending_title||"").trim(), pendingAt=Number(rec?.rename_pending_at_ms||0);
  if(pendingTitle&&pendingAt>0&&Date.now()-pendingAt<65000) return pendingTitle;
  const live=String(liveTitle||"").trim();
  if(live) return live;
  const sharedVerified=String(rec?.verified_title||"").trim();
  if(sharedVerified) return sharedVerified;
  if(rec?.manual_locked && String(rec?.manual_title||"").trim()) return String(rec.manual_title).trim();
  if(String(rec?.context_title||"").trim()) return String(rec.context_title).trim();
  return String(fallbackTitle||"").trim();
}
//@@FN_END:monitorContextTitleDisplayFromRecord

//@@FN_START:monitorContextTitleInput
function monitorContextTitleInput(worker,state,endpoint=null){

  const key=String(worker?.conversation_key||endpoint?.conversation_key||"").trim(); const ghost=key?monitorGhostCache.get(key):null;

  const task=monitorGhostTaskForWorker(worker,state); const history=(Array.isArray(ghost?.history)?ghost.history:[]).slice(-5).map(x=>String(x?.text||"")).filter(Boolean);

  const project=String(task?.project_name||worker?.project_name||endpoint?.metadata?.project_name||ghost?.project_name||"").trim();

  return {conversation_key:key,browser_title:String(endpoint?.title||worker?.title||ghost?.title||""),task_title:String(task?.title||ghost?.task_title||""),project_name:project,history,conversation_tail:Array.isArray(ghost?.conversation_tail)?ghost.conversation_tail.slice(-5):[],created_at_ms:Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0)};

}
//@@FN_END:monitorContextTitleInput

//@@FN_START:monitorContextTitlePart
function monitorContextTitlePart(value) {

  let text = monitorGhostMeaningfulTitle(value, "");

  if (!text) return "";

  text = String(text).replace(/\s*\[[A-Z_]+\].*$/i, "").replace(/\s+·\s+.*$/, "").trim();

  return normalizeMonitorWindowTitle(text).slice(0, 28).trim();

}
//@@FN_END:monitorContextTitlePart

//@@FN_START:monitorContextTitleRecord
function monitorContextTitleRecord(key) { return key ? (monitorContextTitles.get(String(key)) || {}) : {}; }
//@@FN_END:monitorContextTitleRecord

//@@FN_START:monitorContextTitleSignature
function monitorContextTitleSignature(input) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorContextTitleSignature"].apply(this, arguments); }
//@@FN_END:monitorContextTitleSignature

//@@FN_START:monitorDisplayHwndForBrowserWindowId
function monitorDisplayHwndForBrowserWindowId(windowIdValue, state = monitorLastAiState, instanceIdValue = "", sessionIdValue = "") {
  return monitorHwndForBrowserWindowId(windowIdValue, state, instanceIdValue, sessionIdValue)
    || monitorBctDisplaySessionHwnd(windowIdValue, instanceIdValue, sessionIdValue);
}
//@@FN_END:monitorDisplayHwndForBrowserWindowId

//@@FN_START:monitorEnsureLocalLlmControlStatus
async function monitorEnsureLocalLlmControlStatus(force = false, render = true) {
  if (!force && monitorLocalLlmControlState) return monitorLocalLlmControlState;
  if (monitorLocalLlmStatusPromise) return monitorLocalLlmStatusPromise;

  const requestGeneration = monitorLocalLlmCommandState.generation;
  const request = (async () => {
    const response = await actFetch(ORCHESTRATOR_LOCAL_LLM_STATUS_URL, { cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok) throw new Error(data?.error || ("HTTP " + response.status));

    if (requestGeneration !== monitorLocalLlmCommandState.generation || monitorLocalLlmCommandState.inFlight) {
      return data;
    }

    monitorAdoptLocalLlmControlPayload(data, render);
    return data;
  })().catch((error) => {
    console.warn("Local LLM status unavailable", error);
    return null;
  });

  monitorLocalLlmStatusPromise = request;
  try {
    return await request;
  } finally {
    if (monitorLocalLlmStatusPromise === request) monitorLocalLlmStatusPromise = null;
  }
}
//@@FN_END:monitorEnsureLocalLlmControlStatus

//@@FN_START:monitorGetWindowCapture
async function monitorGetWindowCapture(hwnd, profile = "thumb") {
  return monitorThumbnailService.requestSnapshot(hwnd, "desktop-frame", profile);
}
//@@FN_END:monitorGetWindowCapture

//@@FN_START:monitorGroupChatgptMembersForDisplay
function monitorGroupChatgptMembersForDisplay(members,state) {

  const input=Array.isArray(members)?members:[];

  if(monitorRoleAssignMode) return input;

  const buckets=new Map(); const order=[];

  for(const worker of input){

    const key=monitorWindowGroupKeyForWorker(worker,state);

    if(!key){order.push({single:worker});continue;}

    if(!buckets.has(key)){buckets.set(key,[]);order.push({key});}

    buckets.get(key).push(worker);

  }

  return order.map((item)=>{

    if(item.single)return item.single;

    const group=buckets.get(item.key)||[]; if(group.length<2)return group[0];

    const active=group.find((worker)=>{const ep=endpointForMonitorWorker(worker,state);return ep?.metadata?.tab_active===true||ep?.metadata?.window_bounds?.activeTab===true;})||group[0];

    return {...active,__window_group_members:group,__window_group_key:item.key};

  }).filter(Boolean);

}
//@@FN_END:monitorGroupChatgptMembersForDisplay

//@@FN_START:monitorHwndForBrowserWindowId
function monitorHwndForBrowserWindowId(windowIdValue, state = monitorLastAiState, instanceIdValue = "", sessionIdValue = "") {
  const windowId = String(windowIdValue ?? "").trim();
  if (!/^\d+$/.test(windowId) || windowId === "0") return "";
  const currentSessionHwnd = monitorBctCurrentSessionHwnd(windowId, instanceIdValue, sessionIdValue);
  if (currentSessionHwnd) return currentSessionHwnd;
  if (!state) return "";

  const candidates = new Set();
  const browserNodes = Array.isArray(state?.organization?.browser_nodes) ? state.organization.browser_nodes : [];
  for (const node of browserNodes) {
    const nodeWindowId = String(node?.window_id ?? node?.browser_window_id ?? "").trim();
    const hwnd = String(node?.hwnd || "").trim();
    if (nodeWindowId === windowId && /^\d+$/.test(hwnd) && hwnd !== "0") candidates.add(hwnd);
  }

  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];
  for (const endpoint of endpoints) {
    if (String(endpoint?.presence_state || "").toUpperCase() !== "OPEN") continue;
    if (monitorBrowserWindowIdForEndpoint(endpoint) !== windowId) continue;
    const hwnd = String(endpointOsWindowHandle(endpoint) || "").trim();
    if (/^\d+$/.test(hwnd) && hwnd !== "0") candidates.add(hwnd);
  }

  return candidates.size === 1 ? [...candidates][0] : "";
}
//@@FN_END:monitorHwndForBrowserWindowId

//@@FN_START:monitorIsActionableCodexResource
function monitorIsActionableCodexResource(worker) {
  return worker?.__kind === "LLM_NODE"
    && monitorIsExplicitCodexResource(worker)
    && monitorCodexResourceProfile(worker) === "GOOGLE";
}
//@@FN_END:monitorIsActionableCodexResource

//@@FN_START:monitorIsActivelyWorking
function monitorIsActivelyWorking(work) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorIsActivelyWorking"].apply(this, arguments); }
//@@FN_END:monitorIsActivelyWorking

//@@FN_START:monitorIsExplicitCodexResource
function monitorIsExplicitCodexResource(node) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorIsExplicitCodexResource"].apply(this, arguments); }
//@@FN_END:monitorIsExplicitCodexResource

//@@FN_START:monitorIsOwnWindowTitle
function monitorIsOwnWindowTitle(value) {
  const title = String(value || "").trim();
  return title === "BCT Window Monitor" || title.startsWith("BCT Window Monitor ·") ||
    title === "DWM" || title.startsWith("DWM ·") || title.startsWith("DesktopWindow Monitor");
}
//@@FN_END:monitorIsOwnWindowTitle

//@@FN_START:monitorLifecycleTooltip
function monitorLifecycleTooltip(key,endpoint,ghost){

  const rec=monitorContextTitleRecord(key), created=Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0), closed=Number(ghost?.closed_at_ms||monitorGhostTime(endpoint?.closed_at)||0);

  return `프로젝트 ${rec.project_name||"미지정"} · 생성 ${created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"} · 소멸 ${closed?new Date(closed).toLocaleString("ko-KR"):"-"} · 원본 제목 ${endpoint?.title||ghost?.title||""}`;

}
//@@FN_END:monitorLifecycleTooltip

//@@FN_START:monitorLlmRuntimePresentation
function monitorLlmRuntimePresentation(worker, ready) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorLlmRuntimePresentation"].apply(this, arguments); }
//@@FN_END:monitorLlmRuntimePresentation

//@@FN_START:monitorLocalLlmIsUsable
function monitorLocalLlmIsUsable(control = monitorLocalLlmControlState) {
  if (!control || String(control.state || "off").toLowerCase() !== "ready") return false;
  return monitorLocalOllamaModels(control).some(monitorLocalModelIsLoaded);
}
//@@FN_END:monitorLocalLlmIsUsable

//@@FN_START:monitorLocalLlmReadyState
function monitorLocalLlmReadyState() {
  return String(monitorLocalLlmControlState?.state || "off").toLowerCase();
}
//@@FN_END:monitorLocalLlmReadyState

//@@FN_START:monitorLocalLlmSummary
function monitorLocalLlmSummary() {
  const control = monitorLocalLlmControlState;
  if (!control) return "상태 확인 중";
  const models = monitorLocalOllamaModels(control);
  const loaded = models.filter(monitorLocalModelIsLoaded);
  const stack = control.state === "ready" ? "Ollama · 준비됨"
    : control.state === "partial" ? "일부 서비스만 준비됨"
      : "Ollama · 꺼짐";
  return `${stack} · 모델 ${loaded.length}/${models.length} 로드`;
}
//@@FN_END:monitorLocalLlmSummary

//@@FN_START:monitorLocalModelIsLoaded
function monitorLocalModelIsLoaded(node) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorLocalModelIsLoaded"].apply(this, arguments); }
//@@FN_END:monitorLocalModelIsLoaded

//@@FN_START:monitorLocalOllamaModels
function monitorLocalOllamaModels(payload) {
  const nodes = Array.isArray(payload?.llm_nodes) ? payload.llm_nodes : [];
  return nodes
    .filter((node) => String(node?.kind || "").toLowerCase() === "local"
      && String(node?.provider || "").toLowerCase() === "ollama")
    .sort((a, b) => Number(monitorLocalModelIsLoaded(b)) - Number(monitorLocalModelIsLoaded(a)));
}
//@@FN_END:monitorLocalOllamaModels

//@@FN_START:monitorPatchContextTitleRows
function monitorPatchContextTitleRows(conversationKey) {
  const key=String(conversationKey||"").trim();
  if(!key)return;
  const rec=monitorContextTitleRecord(key);
  for(const row of monitorWorkers.querySelectorAll(".monitor-worker-row[data-conversation-key]")){
    if(String(row.dataset.conversationKey||"")!==key)continue;
    const identity=row.querySelector(".monitor-worker-identity");
    if(!identity)continue;
    let titleNode=identity.querySelector(".monitor-worker-chat-title");
    const title=monitorContextTitleDisplayFromRecord(rec,row.dataset.contextTitleLive||"",row.dataset.contextTitleFallback||"");
    if(!title){titleNode?.remove();continue;}
    if(!titleNode){titleNode=document.createElement("span");titleNode.className="monitor-worker-chat-title";identity.append(titleNode);}
    titleNode.textContent=title;
  }
}
//@@FN_END:monitorPatchContextTitleRows

//@@FN_START:monitorPersistentRoleClass
function monitorPersistentRoleClass(role) {

  return MONITOR_PERSISTENT_ROLE_CLASSES[String(role || "").toUpperCase()] || "";

}
//@@FN_END:monitorPersistentRoleClass

//@@FN_START:monitorPhysicalWindowPeerLocation
function monitorPhysicalWindowPeerLocation(endpoint, state, now = Date.now()) {

  if (!endpoint) return null;

  const instanceId = String(endpoint?.transport_instance_id || "").trim();

  const windowId = String(endpoint?.window_id ?? "").trim();

  if (!instanceId || !windowId) return null;

  const peers = (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((item) =>

    item !== endpoint

    && String(item?.presence_state || "").toUpperCase() === "OPEN"

    && String(item?.transport_instance_id || "").trim() === instanceId

    && String(item?.window_id ?? "").trim() === windowId

  );

  for (const peer of peers) {

    const location = monitorLocationForEndpoint(peer, now);

    if (!location) continue;

    const desktopId = String(location?.desktopId || "").trim();

    const desktopIndex = monitorDesktopState.desktopIds.indexOf(desktopId);

    if (desktopIndex >= 0) return { ...location, desktop: desktopIndex + 1 };

  }

  return null;

}
//@@FN_END:monitorPhysicalWindowPeerLocation

//@@FN_START:monitorPreviewAtPointer
function monitorPreviewAtPointer() {

  if (monitorHoverPointer.x < 0 || monitorHoverPointer.y < 0) return "";

  const element = document.elementFromPoint(monitorHoverPointer.x, monitorHoverPointer.y);

  const target = element?.closest?.(".monitor-desktop-thumb-window, .monitor-window-preview, .monitor-worker-row[data-hwnd]");

  return String(target?.dataset?.hwnd || "");

}
//@@FN_END:monitorPreviewAtPointer

//@@FN_START:monitorPublishSharedContextTitle
function monitorPublishSharedContextTitle(key, rec) {

  key=String(key||"").trim(); if(!key||!rec||typeof rec!=="object")return;

  const at=Number(rec.title_updated_ms||0); if(!(at>0))return;

  void monitorNative({type:"setSharedMonitorRuntime",kind:"alert",conversationKey:`${MONITOR_SHARED_CONTEXT_TITLE_PREFIX}${key}`,at:String(at),symbol:"T",tone:"context-title",label:JSON.stringify(rec)}).catch(()=>null);

}
//@@FN_END:monitorPublishSharedContextTitle

//@@FN_START:monitorPublishSharedInstance
async function monitorPublishSharedInstance(reason = "event") {

  const result = await monitorNative({type:"getSharedMonitorRuntime"}).catch(() => null);

  if (!result?.ok) return;

  const hostProfile=String(result.hostProfile||"").toUpperCase();

  if (!["GOOGLE","NAVER"].includes(hostProfile)) return;

  const hwnd=String(monitorDesktopState.hostWindowHwnd||"").trim();

  const instanceId = /^\d+$/.test(hwnd) && hwnd !== "0" ? hwnd : String(document.title||"MONITOR").trim();

  // Runtime presence is one current record per browser profile. Using the
  // transient HWND in the key left old rows behind after an extension reload.
  await monitorPublishSharedRuntime("alert",`${MONITOR_SHARED_INSTANCE_PREFIX}${hostProfile}`,{symbol:"",tone:"monitor-instance",label:JSON.stringify({profile:hostProfile,build_id:MONITOR_RUNTIME_BUILD_ID,manifest_version:chrome.runtime.getManifest().version,reload_token:String(monitorReloadToken||""),monitor_title:document.title,hwnd,reason:String(reason||"event"),thumbnail_background:monitorThumbnailBackgroundRuntimeDiagnostics(),thumbnail_native_trace:globalThis.MonitorNativeTrace?.summary?.("getDesktopVisualSnapshot")||null,thumbnail_projection:monitorThumbnailProjectionRuntimeDiagnostics(),seen_at_ms:Date.now()})});

}
//@@FN_END:monitorPublishSharedInstance

//@@FN_START:monitorPublishSharedRebootSnapshot
function monitorPublishSharedRebootSnapshot(snapshot=monitorRebootSnapshot){
  if (!MONITOR_FEATURE_RECOVERY_ENABLED) return;

  if(!snapshot||!Array.isArray(snapshot.items)||!snapshot.items.length)return;

  void monitorNative({type:"setSharedMonitorRuntime",kind:"alert",conversationKey:MONITOR_SHARED_REBOOT_SNAPSHOT_KEY,at:String(Number(snapshot.captured_at_ms)||Date.now()),symbol:"",tone:"reboot-snapshot",label:JSON.stringify(snapshot)}).catch(()=>null);

}
//@@FN_END:monitorPublishSharedRebootSnapshot

//@@FN_START:monitorPublishSharedRuntime
async function monitorPublishSharedRuntime(kind, conversationKey, payload = {}, at = Date.now()) {

  const key=String(conversationKey||"").trim(); if(!key)return null;

  try { return await monitorNative({type:"setSharedMonitorRuntime",kind,conversationKey:key,at:String(Number(at)||Date.now()),...payload}); } catch (_) { return null; }

}
//@@FN_END:monitorPublishSharedRuntime

//@@FN_START:monitorReconcilePendingTitles
function monitorReconcilePendingTitles(state){

  let changed=false;

  for(const ep of Array.isArray(state?.endpoints)?state.endpoints:[]){

    if(String(ep?.presence_state||"").toUpperCase()!=="OPEN")continue;

    const key=String(ep?.conversation_key||"").trim(), live=String(ep?.title||"").trim(); if(!key||!live)continue;

    const rec=monitorContextTitleRecord(key), pending=String(rec?.rename_pending_title||"").trim(); if(!pending||!monitorTitlesEquivalent(live,pending))continue;

    monitorContextTitles.set(key,{...rec,verified_title:pending,manual_title:"",context_title:"",rename_pending_title:"",rename_pending_at_ms:0,rename_error:"",manual_locked:rec.rename_manual_lock!==false,title_source:rec.rename_manual_lock===false?"AI_VERIFIED":"MANUAL_VERIFIED",title_updated_ms:Date.now()}); changed=true;

  }

  if(changed)persistMonitorContextTitles();

}
//@@FN_END:monitorReconcilePendingTitles

//@@FN_START:monitorRecordRefreshTiming
function monitorRecordRefreshTiming(startedAt, stages) {
  const totalMs = Math.max(0, performance.now() - startedAt);
  monitorRenderDiagnostics.refreshRuns += 1;
  monitorRenderDiagnostics.refreshLastMs = totalMs;
  monitorRenderDiagnostics.refreshSlowestMs = Math.max(monitorRenderDiagnostics.refreshSlowestMs, totalMs);
  monitorRenderDiagnostics.refreshLastStages = { ...stages, total: totalMs };
}
//@@FN_END:monitorRecordRefreshTiming

//@@FN_START:monitorRememberApprovedChatTransition
function monitorRememberApprovedChatTransition(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); if(!key)return; monitorApprovedChatTransitions.add(key);

  if(monitorApprovedChatTransitionsReady)chrome.storage.local.set({[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]:[...monitorApprovedChatTransitions]});

}
//@@FN_END:monitorRememberApprovedChatTransition

//@@FN_START:monitorReportMatchesTask
function monitorReportMatchesTask(report, task) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorReportMatchesTask"].apply(this, arguments); }
//@@FN_END:monitorReportMatchesTask

//@@FN_START:monitorRoleAdminCandidates
function monitorRoleAdminCandidates(state) {

  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];

  const counts = new Map();

  for (const ep of endpoints) if (String(ep?.presence_state||"").toUpperCase()==="OPEN") { const k=String(ep?.conversation_key||"").trim(); if(k) counts.set(k,(counts.get(k)||0)+1); }

  return endpoints.filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN").filter(ep=>{const k=String(ep?.conversation_key||"").trim();return k&&counts.get(k)===1;}).map(ep=>({conversation_key:String(ep.conversation_key).trim(),profile_id:String(ep?.profile_id||"").toUpperCase()})).sort((a,b)=>a.profile_id.localeCompare(b.profile_id)||a.conversation_key.localeCompare(b.conversation_key));

}
//@@FN_END:monitorRoleAdminCandidates

//@@FN_START:monitorRoleAdminErrorText
function monitorRoleAdminErrorText(value) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorRoleAdminErrorText"].apply(this, arguments); }
//@@FN_END:monitorRoleAdminErrorText

//@@FN_START:monitorRoleAdminPath
function monitorRoleAdminPath(action) { return `${ORCHESTRATOR_ROLE_ADMIN_URL}/${action}`; }
//@@FN_END:monitorRoleAdminPath

//@@FN_START:monitorRoleAdminPayload
function monitorRoleAdminPayload(action, roleRow, conversationKey="") {

  const payload={ role:String(roleRow?.role_id||""), expected_generation:Number(roleRow?.generation||0) };

  if(action==="assign"||action==="replace") payload.conversation_key=String(conversationKey||"").trim();

  return payload;

}
//@@FN_END:monitorRoleAdminPayload

//@@FN_START:monitorRoleAdminShort
function monitorRoleAdminShort(role) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorRoleAdminShort"].apply(this, arguments); }
//@@FN_END:monitorRoleAdminShort

//@@FN_START:monitorSelectedEntries
function monitorSelectedEntries(primaryHwnd, sourceDesktopId) {

  const primary = String(primaryHwnd || "");

  const selected = monitorSelectedHwnds.has(primary) ? [...monitorSelectedHwnds] : [primary];

  return selected.map((hwnd) => {

    const location = monitorWindowDesktopLocations.get(String(hwnd));

    return { hwnd: String(hwnd), sourceDesktopId: String(location?.desktopId || sourceDesktopId || "") };

  }).filter((item) => /^\d+$/.test(item.hwnd) && item.hwnd !== "0" && item.sourceDesktopId === sourceDesktopId);

}
//@@FN_END:monitorSelectedEntries

//@@FN_START:monitorSetLocalLlmEnabled
async function monitorSetLocalLlmEnabled(enabled) {
  if (monitorLocalLlmCommandState.inFlight) return null;

  monitorLocalLlmCommandState.generation += 1;
  monitorLocalLlmCommandState.pendingEnabled = Boolean(enabled);
  monitorLocalLlmStatusPromise = null;
  monitorLocalLlmCommandState.inFlight = true;
  monitorUpdateLocalLlmToggleButtons();

  try {
    const response = await actFetch(ORCHESTRATOR_LOCAL_LLM_CONTROL_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok) throw new Error(data?.error || ("HTTP " + response.status));

    monitorAdoptLocalLlmControlPayload(data);
    return data;
  } catch (error) {
    console.warn("Local LLM control failed", error);
    return null;
  } finally {
    monitorLocalLlmCommandState.inFlight = false;
    monitorLocalLlmCommandState.pendingEnabled = null;
    monitorUpdateLocalLlmToggleButtons();
    void monitorEnsureLocalLlmControlStatus(true);
  }
}
//@@FN_END:monitorSetLocalLlmEnabled

//@@FN_START:monitorSetRoleAssignMode
function monitorSetRoleAssignMode(mode) {

  const nextMode = monitorRoleAssignMode === mode ? "" : mode;

  monitorRoleAssignMode = nextMode;

  for (const button of document.querySelectorAll(".monitor-role-mode")) {

    button.classList.toggle("selected", Boolean(nextMode) && button.dataset.roleMode === nextMode);

  }

  const state = monitorLastAiState;

  const selectedWorker = nextMode && state ? monitorSelectedRoleWorker(state) : null;

  if (state) renderWorkers(state);

  if (selectedWorker) {

    setTimeout(() => {

      if (monitorRoleAssignMode === nextMode) void monitorApplyRoleMode(selectedWorker, state);

    }, 60);

  }

}
//@@FN_END:monitorSetRoleAssignMode

//@@FN_START:monitorShouldKeepExistingCapture
function monitorShouldKeepExistingCapture(existingState, existingSource, nextState) {
  const source = String(existingSource || "");
  return String(nextState || "") !== "captured"
    && String(existingState || "") === "captured"
    && (source.startsWith("blob:") || source.startsWith("data:image/"));
}
//@@FN_END:monitorShouldKeepExistingCapture

//@@FN_START:monitorSortLocationParts
function monitorSortLocationParts(worker, state) {

  const canonical = monitorCanonicalPhysicalLocation(worker, state);

  if (canonical?.desktop) return { desktop: canonical.desktop, slot: canonical.slot };

  const station = stationForMonitorWorker(worker, state), metadata = monitorStationMetadata(station);

  const desktop = Number(station?.desktop_id ?? station?.desktop_index ?? metadata.desktop_id ?? metadata.desktop_index);

  const slot = Number(station?.slot_index ?? metadata.slot_index);

  return { desktop: Number.isInteger(desktop) && desktop > 0 ? desktop : null, slot: Number.isInteger(slot) && slot > 0 ? slot : null };

}
//@@FN_END:monitorSortLocationParts

//@@FN_START:monitorStationMetadata
function monitorStationMetadata(station) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorStationMetadata"].apply(this, arguments); }
//@@FN_END:monitorStationMetadata

//@@FN_START:monitorSyncSharedRuntime
async function monitorSyncSharedRuntime() {

  if (monitorSharedRuntimeSyncBusy || !monitorPostWorkStorageReady) return;

  monitorSharedRuntimeSyncBusy = true;

  try {

    const result=await monitorNative({type:"getSharedMonitorRuntime"}); if(!result?.ok)return;

    const hostProfile=String(result.hostProfile||"").toUpperCase();

    let root=null; try{root=JSON.parse(String(result.runtimeJson||"{}"))||{};}catch(_){return;}

    monitorStartupSharedRuntimeConfirmed = true;

    const keys=Object.keys(root);

    if (!keys.length && !monitorSharedRuntimeReady && String(result.hostProfile||"").toUpperCase()==="GOOGLE") {

      for (const key of monitorPostWorkAlerts) {

        const detail=monitorChatAlertDetails.get(key)||{activity:"pause",tone:"general",label:"채팅 작업 완료"};

        await monitorPublishSharedRuntime("alert",key,{activity:detail.activity||"",warning:detail.warning===true,tone:detail.tone||"general",label:detail.label||"채팅 작업 완료"});

      }

      monitorSharedRuntimeReady=true;

      return;

    }

    if (!keys.length) return;

    for (const [key,row0] of Object.entries(root)) {

      const row=(row0&&typeof row0==="object")?row0:{};

      if(key.startsWith(MONITOR_SHARED_INSTANCE_PREFIX)) continue;

      if(key.startsWith(MONITOR_SHARED_CONTEXT_TITLE_PREFIX)){

        const chatKey=key.slice(MONITOR_SHARED_CONTEXT_TITLE_PREFIX.length);

        try{const shared=JSON.parse(String(row.label||"{}"));const sharedAt=Number(shared?.title_updated_ms||0),local=monitorContextTitles.get(chatKey)||{},localAt=Number(local?.title_updated_ms||0);if(chatKey&&sharedAt>localAt)monitorContextTitles.set(chatKey,shared);}catch(_){ }

        continue;

      }

      if(key===MONITOR_SHARED_REBOOT_SNAPSHOT_KEY){

        try{const shared=JSON.parse(String(row.label||"{}"));const sharedAt=Number(shared?.captured_at_ms||0);if(Array.isArray(shared?.items)&&shared.items.length&&sharedAt>=Number(monitorRebootSnapshot?.captured_at_ms||0)){monitorRebootSnapshot=shared;monitorRebootSnapshotReady=true;chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:shared});}}catch(_){}

        continue;

      }

      const generationAt=Number(row.generationAt||0);

      const tabMarker="::TAB:", tabMarkerAt=key.lastIndexOf(tabMarker);

      if(generationAt>0 && tabMarkerAt>0){

        const chatKey=key.slice(0,tabMarkerAt), tabId=key.slice(tabMarkerAt+tabMarker.length), directKey=`${chatKey}:${tabId}`;

        const current=monitorDirectGenerationByTab.get(directKey);

        if(generationAt>Number(current?.at||0)) monitorDirectGenerationByTab.set(directKey,{conversationKey:chatKey,generating:row.generating===true,completionCue:String(row.completionCue||"general"),...monitorDecodeSharedGenerationAttention(row),at:generationAt});

      } else if(generationAt>0) {

        const current=monitorDirectGenerationByConversation.get(key);

        if(generationAt>Number(current?.at||0)) monitorDirectGenerationByConversation.set(key,{conversationKey:key,generating:row.generating===true,completionCue:String(row.completionCue||"general"),...monitorDecodeSharedGenerationAttention(row),at:generationAt});

      }

      if(tabMarkerAt<0){

        const alertAt=Number(row.alertAt||0), ackAt=Number(row.ackAt||0);

        monitorSharedRuntimeAlertAt.set(key,alertAt); monitorSharedRuntimeAckAt.set(key,ackAt);

        if(alertAt>ackAt){const legacyTone=String(row.tone||"general");monitorPostWorkAlerts.add(key);monitorChatAlertDetails.set(key,{activity:String(row.activity||""),warning:row.warning===true||["failure","review","input","action","question"].includes(legacyTone),tone:legacyTone,label:String(row.label||"채팅 작업 완료")});monitorAcknowledgedPostWork.delete(key);}

        else if(ackAt>0){monitorPostWorkAlerts.delete(key);monitorChatAlertDetails.delete(key);monitorAcknowledgedPostWork.add(key);}

      }

    }

    if(!monitorSharedRuntimeInitialReconciled){

      const sharedKeys=new Set(keys);

      for(const key of [...monitorPostWorkAlerts]) if(!sharedKeys.has(key)){monitorPostWorkAlerts.delete(key);monitorChatAlertDetails.delete(key);}

      monitorSharedRuntimeInitialReconciled=true;

    }

    monitorSharedRuntimeReady=true;

    monitorPostWorkPersist();

    for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) applyPersistentMonitorRoleClass(preview, preview.dataset.hwnd||"");

    if(monitorLastAiState)renderWorkers(monitorLastAiState);

  } catch (_) {} finally { monitorSharedRuntimeSyncBusy=false; }

}
//@@FN_END:monitorSyncSharedRuntime

//@@FN_START:monitorSyncSharedState
async function monitorSyncSharedState(reason = "event", publishInstance = false) {

  const jobs = [syncMonitorSharedSelection(), monitorSyncSharedRuntime()];

  if (publishInstance) jobs.push(monitorPublishSharedInstance(reason));

  await Promise.allSettled(jobs);

}
//@@FN_END:monitorSyncSharedState

//@@FN_START:monitorTabBindingKey
function monitorTabBindingKey(endpoint) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorTabBindingKey"].apply(this, arguments); }
//@@FN_END:monitorTabBindingKey

//@@FN_START:monitorTitlesEquivalent
function monitorTitlesEquivalent(observed, requested) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorTitlesEquivalent"].apply(this, arguments); }
//@@FN_END:monitorTitlesEquivalent

//@@FN_START:monitorTrustedPhysicalWindowKey
function monitorTrustedPhysicalWindowKey(endpoint, location = null) {

  const explicit = endpointOsWindowHandle(endpoint);

  if (explicit) return `HWND:${explicit}`;

  const located = String(location?.hwnd || "").trim();

  if (!/^\d+$/.test(located) || located === "0") return "";

  // Only trust a native identity-index hit here. Geometry-only matches are deliberately

  // excluded because two separate Chrome windows can have identical bounds.

  const indexed = monitorWindowDesktopLocations.get(located);

  if (!indexed || String(indexed.conversationKey || "").trim() !== String(endpoint?.conversation_key || "").trim()) return "";

  return `HWND:${located}`;

}
//@@FN_END:monitorTrustedPhysicalWindowKey

//@@FN_START:monitorUpdateLocalLlmToggleButton
function monitorUpdateLocalLlmToggleButton(button) {
  if (!button) return;

  if (monitorLocalLlmCommandState.inFlight) {
    button.disabled = true;
    button.textContent = monitorLocalLlmCommandState.pendingEnabled === false ? "종료 중..." : "시작 중...";
    button.title = monitorLocalLlmCommandState.pendingEnabled === false
      ? "Local LLM 종료 요청 처리 중"
      : "Local LLM 시작 요청 처리 중";
    return;
  }

  const state = monitorLocalLlmReadyState();
  const powered = state === "ready";
  const partial = state === "partial";
  button.classList.toggle("is-on", powered);
  button.classList.toggle("is-partial", partial);
  button.disabled = false;
  button.textContent = powered ? "끄기" : "켜기";
  button.title = powered
    ? "끄기: Ollama를 종료합니다"
    : "켜기: Ollama를 시작하고 기본 모델을 로드합니다";
}
//@@FN_END:monitorUpdateLocalLlmToggleButton

//@@FN_START:monitorUpdateLocalLlmToggleButtons
function monitorUpdateLocalLlmToggleButtons() {
  for (const button of document.querySelectorAll(".monitor-local-llm-toggle")) {
    monitorUpdateLocalLlmToggleButton(button);
  }
}
//@@FN_END:monitorUpdateLocalLlmToggleButtons

//@@FN_START:monitorWorkIconState
function monitorWorkIconState(work, connection, alertDetail = null) {
  const value = String(work || "").toLowerCase();
  const active = ["running", "working", "busy", "executing", "in_progress"].includes(value) ? "play" : "";
  const waiting = ["waiting_resource", "waiting", "paused", "queued", "pending"].includes(value) ? "pause" : "";
  const complete = ["succeeded", "completed", "complete", "done"].includes(value) && connection === "connected" ? "complete" : "";
  // A disconnected, stopped, or cancelled process requires attention; it is
  // explicitly not a declaration that the project work can be closed.
  const warning = connection === "disconnected" || ["offline", "stopped", "cancelled", "canceled"].includes(value) || alertDetail?.warning === true;
  const activity = alertDetail?.activity || active || waiting || complete;
  const label = alertDetail?.label || (warning ? "사용자 조치 필요" : activity === "play" ? "실행" : activity === "pause" ? "일시 정지" : activity === "complete" ? "작업 완료 · 창을 닫아도 됨" : "상태 없음");
  return { activity, warning, label, tone: alertDetail?.tone || "general" };
}
//@@FN_END:monitorWorkIconState

//@@FN_START:persistMonitorContextTitles
function persistMonitorContextTitles() {

  if(!monitorContextTitlesReady) return;

  for(const [key,rec] of monitorContextTitles){
    const signature=JSON.stringify(rec||{});
    if(monitorPublishedContextTitleSignatures.get(key)===signature)continue;
    monitorPublishedContextTitleSignatures.set(key,signature);
    monitorPublishSharedContextTitle(key,rec);
  }

  if(monitorContextTitlePersistQueued)return;
  monitorContextTitlePersistQueued=true;
  queueMicrotask(()=>{
    monitorContextTitlePersistQueued=false;
    const value={};
    for(const [key,rec] of monitorContextTitles)value[key]=rec;
    chrome.storage.local.set({[MONITOR_CONTEXT_TITLE_STORAGE_KEY]:value});
  });

}
//@@FN_END:persistMonitorContextTitles

//@@FN_START:pruneMonitorEphemeralGenerationState
function pruneMonitorEphemeralGenerationState(state, now = Date.now()) {
  const openEndpoints = (Array.isArray(state?.endpoints) ? state.endpoints : []).filter(
    (endpoint) => String(endpoint?.presence_state || "").toUpperCase() === "OPEN"
  );
  const liveConversations = new Set(
    openEndpoints.map((endpoint) => String(endpoint?.conversation_key || "").trim()).filter(Boolean)
  );
  const liveTabs = new Set(
    openEndpoints.map((endpoint) => {
      const key = String(endpoint?.conversation_key || "").trim();
      const tabId = String(endpoint?.tab_id ?? "").trim();
      return key && tabId ? `${key}:${tabId}` : "";
    }).filter(Boolean)
  );
  const protectedConversation = (key) =>
    liveConversations.has(key)
    || monitorPostWorkAlerts.has(key)
    || monitorGhostCache.has(key)
    || monitorTrashRecords.has(key);

  for (const [key, record] of monitorDirectGenerationByConversation) {
    const at = Number(record?.at || 0);
    if (!protectedConversation(String(key)) && (!at || now - at > MONITOR_EPHEMERAL_GENERATION_TTL_MS)) {
      monitorDirectGenerationByConversation.delete(key);
    }
  }

  for (const [tabKey, record] of monitorDirectGenerationByTab) {
    const conversationKey = String(record?.conversationKey || String(tabKey).split(":")[0] || "").trim();
    const at = Number(record?.at || 0);
    if (
      !liveTabs.has(String(tabKey))
      && !protectedConversation(conversationKey)
      && (!at || now - at > MONITOR_EPHEMERAL_GENERATION_TTL_MS)
    ) {
      monitorDirectGenerationByTab.delete(tabKey);
    }
  }

}
//@@FN_END:pruneMonitorEphemeralGenerationState

//@@FN_START:publishMonitorSharedSelection
function publishMonitorSharedSelection() {

  const payload = {

    type: "setSharedMonitorSelection",

    highlightedHwnd: monitorHighlightedHwnd,

    hwndsCsv: [...monitorSelectedHwnds].join(","),

    selectedDesktopId: monitorSharedSelectedDesktopId || monitorDesktopState.observedDesktopId || "",

  };

  monitorSharedSelectionWritePending += 1;

  monitorSharedSelectionWriteSerial = monitorSharedSelectionWriteSerial

    .catch(() => {})

    .then(() => monitorNative(payload))

    .then((result) => {

      const revision = String(result?.revision || "");

      if (result?.ok && revision && compareMonitorSharedSelectionRevision(revision, monitorSharedSelectionRevision) >= 0) monitorSharedSelectionRevision = revision;

    })

    .catch(() => {})

    .finally(() => { monitorSharedSelectionWritePending = Math.max(0, monitorSharedSelectionWritePending - 1); });

}
//@@FN_END:publishMonitorSharedSelection

//@@FN_START:recheckMonitorHover
function recheckMonitorHover() {

  const pointerKey = monitorPreviewAtPointer();

  if (pointerKey || !monitorHoveredHwnd) { applyMonitorWindowHover(pointerKey); return; }

  applyMonitorWindowHover("");

}
//@@FN_END:recheckMonitorHover

//@@FN_START:refreshAiMonitor
async function refreshAiMonitor() {
  const refreshStartedAt = performance.now();
  const refreshStages = {};
  const markRefreshStage = (name) => { refreshStages[name] = Math.max(0, performance.now() - refreshStartedAt); };

  if (monitorRefreshBusy) { monitorRefreshQueued = true; return; }

  monitorRefreshBusy = true;

  let actStateConfirmed = false;

  try {

    const optionalFetch = (url, timeoutMs = 900) => Promise.race([

      actFetch(url, { cache: "no-store" }).catch(() => null),

      new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs)),

    ]);

    const stateResponse = await actFetch(ORCHESTRATOR_MONITOR_STATE_URL, { cache: "no-store" });

    const [reportsResponse, llmNodesResponse] = await Promise.all([

      optionalFetch(ORCHESTRATOR_PENDING_REPORTS_URL),

      optionalFetch(ORCHESTRATOR_LLM_NODES_URL, 5000),

    ]);

    markRefreshStage("ACT 수신");

    if (!stateResponse.ok) throw new Error(`STATE HTTP ${stateResponse.status}`);

    const state = await stateResponse.json();

    if (!state?.ok) throw new Error("Orchestrator state unavailable");

    monitorStartupStateConfirmed = true;

    const startupOpenEndpoints=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((endpoint)=>String(endpoint?.presence_state||"").toUpperCase()==="OPEN");

    monitorStartupEndpointFreshConfirmed=startupOpenEndpoints.every((endpoint)=>monitorEndpointFreshnessState(endpoint)!=="unresponsive");

    const llmNodeState = llmNodesResponse?.ok ? await llmNodesResponse.json().catch(() => null) : null;

    const previousLlmNodes = Array.isArray(monitorLastAiState?.llm_nodes) && monitorLastAiState.llm_nodes.length

      ? monitorLastAiState.llm_nodes

      : monitorCachedLlmNodes;

    const freshLlmNodes = llmNodeState?.ok && Array.isArray(llmNodeState?.llm_nodes) ? llmNodeState.llm_nodes : null;

    const transientEmptyLlmNodes = Array.isArray(freshLlmNodes) && freshLlmNodes.length === 0 && previousLlmNodes.length > 0 && monitorConsecutiveEmptyLlmResponses < 1;

    if (Array.isArray(freshLlmNodes)) {

      if (freshLlmNodes.length === 0) monitorConsecutiveEmptyLlmResponses += 1;

      else monitorConsecutiveEmptyLlmResponses = 0;

    }

    const effectiveFreshLlmNodes = transientEmptyLlmNodes ? null : freshLlmNodes;

    if (transientEmptyLlmNodes) monitorRefreshQueued = true;

    state.llm_nodes = effectiveFreshLlmNodes || previousLlmNodes;

    if (effectiveFreshLlmNodes) {

      monitorCachedLlmNodes = effectiveFreshLlmNodes;

      chrome.storage.local.set({ [MONITOR_LLM_CACHE_STORAGE_KEY]: effectiveFreshLlmNodes }).catch(() => {});

    }

    markRefreshStage("상태 정리");

    // From here on ACT state transport is confirmed healthy. Any later failure is

    // Monitor-side synchronization work and must not be reported as ACT disconnected.

    actStateConfirmed = true;

    let reportState = null;

    if (reportsResponse?.ok) reportState = await reportsResponse.json().catch(() => null);

    if (reportState?.ok) {

      monitorPendingDurableReports = Array.isArray(reportState?.reports) ? reportState.reports : [];

    } else if (reportsResponse?.status === 409) {

      monitorPendingDurableReports = [];

      const reportError = String(reportState?.error || "").trim();

      if (reportError === "CURRENT_ORCHESTRATOR_MISSING") {

        setMonitorStatus("ORCHESTRATOR 없음", false);

      } else {

        setMonitorStatus("보고 준비 중", false);

      }

    }

    monitorLastAiState = state;
    pruneMonitorEphemeralGenerationState(state);

    chrome.storage.local.set({ [MONITOR_AI_STATE_CACHE_KEY]: { at: Date.now(), state } }).catch(() => {});

    monitorReconcilePendingTitles(state);

    // Render ACT-authoritative nodes immediately. Physical identity/workplace sync below is enrichment only

    // and must not be able to leave the node list blank when ACT transport is already healthy.

    renderWorkers(state);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleInitialSemanticThumbSync();

    markRefreshStage("노드 렌더");

    // Physical desktop/window state is authoritative from Windows Native Host; ACT adds node/work meaning only.

    await Promise.race([refreshMonitorIdentityIndex(state), new Promise((resolve)=>setTimeout(resolve, 3000))]);

    markRefreshStage("창 식별");
    await syncMonitorPhysicalWorkplaces(state);
    markRefreshStage("데스크 동기화");

    const completionTransitionChanged = monitorSyncChatCompletionTransitions(state);

    const authoritativeAlertChanged = monitorSyncAuthoritativeCompletionAlerts(state);

    if (completionTransitionChanged || authoritativeAlertChanged) renderWorkers(state);

    monitorPostWorkLastObservedAt = Date.now();

    monitorPostWorkPersist();

    markRefreshStage("후처리");
    monitorStateFailureCount = 0;

    monitorStateFailureStartedAt = 0;

    setMonitorStatus("ACT 실행 중", true);

  } catch (error) {

    if (actStateConfirmed) {

      monitorStateFailureCount = 0;

      monitorStateFailureStartedAt = 0;

      setMonitorStatus("ACT 실행 중", true);

      console.warn("DesktopWindow Monitor post-ACT sync delayed", error);

    } else {

      scheduleMonitorStartupRecovery();

      monitorStateFailureCount += 1;

      if (!monitorStateFailureStartedAt) monitorStateFailureStartedAt = Date.now();

      if (Date.now() - monitorStateFailureStartedAt >= MONITOR_FAILURE_GRACE_MS) {

        setMonitorStatus("ACT \uC5F0\uACB0 \uB04A\uAE40", false);

        console.warn("DesktopWindow Monitor ACT state transport failed", error);

      }

    }

  } finally {

    monitorRecordRefreshTiming(refreshStartedAt, refreshStages);
    monitorRefreshBusy = false;
    // A restore can queue an authoritative badge resync while the full refresh owns the gate.
    // Consume it immediately when that gate opens instead of waiting for another window event.
    if (monitorConversationStateForceBadgeSyncPending && !monitorConversationStateRefreshBusy) {
      setTimeout(()=>{ void refreshMonitorConversationStateFast(); },0);
    }

    if (monitorRefreshQueued) {

      monitorRefreshQueued = false;

      setTimeout(() => { void refreshAiMonitor(); }, 0);

    }

  }

}
//@@FN_END:refreshAiMonitor

//@@FN_START:refreshMonitorAutoProcess
async function refreshMonitorAutoProcess(){

  try{const r=await actFetch(ORCHESTRATOR_AUTO_PROCESS_URL,{cache:'no-store'});const d=await r.json();if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);monitorAutoProcessEnabled=Boolean(d.enabled);monitorStructureActiveScopeKey=String(d.active_scope_key||"GLOBAL");monitorAutoProcessQuick.textContent=`AUTO: ${monitorAutoProcessEnabled?'ON':'OFF'}`;monitorAutoProcessQuick.title=`자동 처리 ${monitorAutoProcessEnabled?'ON':'OFF'} · 적용 구조: ${monitorStructureActiveScopeKey} · 클릭하여 ${monitorAutoProcessEnabled?'OFF':'ON'}`;monitorAutoProcessQuick.classList.toggle('is-on',monitorAutoProcessEnabled);monitorAutoProcessQuick.classList.toggle('is-off',!monitorAutoProcessEnabled);monitorAutoProcessQuick.classList.remove('is-unknown','is-error');}

  catch(e){monitorAutoProcessQuick.textContent='AUTO: ?';monitorAutoProcessQuick.title=monitorDiagTextError(e);monitorAutoProcessQuick.classList.remove('is-on','is-off');monitorAutoProcessQuick.classList.add('is-error');}

}
//@@FN_END:refreshMonitorAutoProcess

//@@FN_START:refreshMonitorContextTitle
async function refreshMonitorContextTitle(worker,state,endpoint=null,force=false){

  const input=monitorContextTitleInput(worker,state,endpoint), key=input.conversation_key; if(!key||monitorContextTitleInflight.has(key))return;

  const rec=monitorContextTitleRecord(key); if(rec.manual_locked&&!force)return;

  const sig=monitorContextTitleSignature(input), now=Date.now();

  if(!force&&now-Number(rec.last_attempt_ms||0)<60000)return;

  if(!force&&rec.signature===sig&&now-Number(rec.title_updated_ms||0)<MONITOR_CONTEXT_TITLE_REFRESH_MS)return;

  monitorContextTitles.set(key,{...rec,last_attempt_ms:now}); persistMonitorContextTitles();

  monitorContextTitleInflight.add(key);

  try{

    const r=await actFetch(ORCHESTRATOR_CONTEXT_TITLE_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)}); const data=await r.json();

    if(!r.ok||!data?.ok||!String(data?.title||"").trim())return;

    const provider=String(data.provider||"AI").toUpperCase(); const isFallback=provider==="FALLBACK";

    monitorContextTitles.set(key,{...rec,context_title:String(data.title).trim().slice(0,72),context_summary:String(data.summary||"").trim().slice(0,360),project_name:String(data.project_name||input.project_name||"").trim().slice(0,72),title_source:isFallback?"FALLBACK":"AI",title_updated_ms:isFallback?0:Date.now(),signature:isFallback?"":sig,manual_locked:false}); persistMonitorContextTitles(); monitorPatchContextTitleRows(key);

  }catch(_){ } finally{monitorContextTitleInflight.delete(key);}

}
//@@FN_END:refreshMonitorContextTitle

//@@FN_START:refreshMonitorRoleAdmin
async function refreshMonitorRoleAdmin() {

  if(monitorRoleAdminBusy)return; monitorRoleAdminBusy=true;

  try{const r=await actFetch(ORCHESTRATOR_ROLE_ADMIN_URL,{cache:"no-store"});const data=await r.json();if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);const signature=JSON.stringify([data.roles,monitorRoleAdminCandidates(monitorLastAiState||{}).map(x=>x.conversation_key)]);monitorRoleAdminState=data;setMonitorRoleAdminStatus("");if(signature!==monitorRoleAdminSignature){monitorRoleAdminSignature=signature;renderMonitorRoleAdmin();}}

  catch(error){setMonitorRoleAdminStatus(monitorRoleAdminErrorText(error?.message||error),true);}

  finally{monitorRoleAdminBusy=false;}

}
//@@FN_END:refreshMonitorRoleAdmin

//@@FN_START:refreshObservedWindows
async function refreshObservedWindows() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  if (!monitorIsActiveDesktopRenderer()) return false;

  const desktopId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || null;

  if (!desktopId) return;

  const frame = await captureDesktopFrame(desktopId, "main");

  if (!frame || monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] !== desktopId) return;

  monitorWindowLayer.dataset.desktopId = desktopId;

  reconcileFrame(monitorWindowLayer, frame, "monitor-window-preview");

  // Keep small desktop cards lightweight even for the selected desktop.

  // The large preview above is the only surface that needs real captured pixels.

  const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (visual?.isConnected) await refreshDesktopThumb(visual, desktopId);
  syncMonitorMinimizedNodeBadges(monitorLastAiState);

}
//@@FN_END:refreshObservedWindows

//@@FN_START:refreshWindowsCurrentState
async function refreshWindowsCurrentState() {
  if (monitorWindowsStateRefreshBusy) return;
  monitorWindowsStateRefreshBusy = true;
  try {
    await refreshVirtualDesktops();
  } finally {
    monitorWindowsStateRefreshBusy = false;
  }
}
//@@FN_END:refreshWindowsCurrentState

//@@FN_START:removeMonitorV2Window
function removeMonitorV2Window(hwnd, exceptDesktopId = "") {
  const key=String(hwnd||"");
  if (!/^\d+$/.test(key)) return;
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  for (const tile of monitorDesktopThumbs.children) {
    const id=String(tile.dataset.desktopId||"");
    if (id===String(exceptDesktopId||"")) continue;
    const visual=tile.querySelector(".monitor-desktop-thumb-visual");
    if (!visual) continue;
    renderer?.removeWindow(visual,id,key);
    // These are independent semantic overlays, not pixel-rendering surfaces.
    for (const selector of [
      `.monitor-window-status-layer[data-hwnd="${key}"]`,
      `.monitor-window-pause-overlay[data-hwnd="${key}"]`,
      `.monitor-window-desktop-badge[data-hwnd="${key}"]`,
      `.monitor-window-non-chat-countdown[data-hwnd="${key}"]`
    ]) visual.querySelector(selector)?.remove();
  }
}
//@@FN_END:removeMonitorV2Window

//@@FN_START:renderMonitorRoleAdmin
function renderMonitorRoleAdmin() {

  const rowsEl=document.getElementById("monitorRoleAdminRows"); if(!rowsEl)return; rowsEl.replaceChildren();

  const roles=Array.isArray(monitorRoleAdminState?.roles)?monitorRoleAdminState.roles:[];

  const candidates=monitorRoleAdminCandidates(monitorLastAiState||{});

  for(const role of MONITOR_ROLE_ADMIN_ROLES){

    const data=roles.find(x=>String(x?.role_id||"")===role)||{role_id:role,generation:0,claim_policy:"UNKNOWN",occupant:null,presence_state:"MISSING",present:false};

    const row=document.createElement("div"); row.className=`monitor-role-admin-row monitor-role-${monitorRoleAdminShort(role).toLowerCase()}`;

    const badge=document.createElement("span"); badge.className="monitor-role-admin-badge"; badge.textContent=monitorRoleAdminShort(role);

    const meta=document.createElement("span"); meta.className="monitor-role-admin-meta"; const occ=String(data?.occupant?.conversation_key||""); meta.textContent=`${data.present?"OPEN":String(data.presence_state||"OFFLINE")} · ${data.claim_policy||"?"} · g${Number(data.generation||0)}${occ?` · ${occ.slice(0,8)}`:""}`; meta.title=occ||"";

    const picker=document.createElement("select"); picker.className="monitor-role-admin-picker"; picker.setAttribute("aria-label",`${role} 대상 conversationKey`); const blank=document.createElement("option"); blank.value=""; blank.textContent="conversationKey 선택"; picker.append(blank);

    for(const item of candidates){const opt=document.createElement("option");opt.value=item.conversation_key;opt.textContent=`${item.profile_id||"?"} · ${item.conversation_key}`;picker.append(opt);} const saved=monitorRoleAdminSelection.get(role); if(saved&&candidates.some(x=>x.conversation_key===saved))picker.value=saved; else if(occ&&candidates.some(x=>x.conversation_key===occ))picker.value=occ;

    const controls=document.createElement("span"); controls.className="monitor-role-admin-actions";

    const make=(label,action)=>{const b=document.createElement("button");b.type="button";b.textContent=label;b.dataset.action=action;b.disabled=monitorRoleAdminInFlight.has(role)||(action!=="release"&&action!=="recruitment"&&!picker.value);b.addEventListener("click",()=>runMonitorRoleAdminAction(action,data,picker.value));return b;};

    controls.append(make("Assign","assign"),make("Replace","replace"),make("Release","release"),make("Open recruitment","recruitment"));

    picker.disabled=monitorRoleAdminInFlight.has(role); picker.addEventListener("change",()=>{monitorRoleAdminSelection.set(role,picker.value);for(const b of controls.querySelectorAll("button")){if(["assign","replace"].includes(b.dataset.action))b.disabled=monitorRoleAdminInFlight.has(role)||!picker.value;}});

    row.append(badge,meta,picker,controls); rowsEl.append(row);

  }

}
//@@FN_END:renderMonitorRoleAdmin

//@@FN_START:resetMonitorContextTitleToBrowser
function resetMonitorContextTitleToBrowser(key){

  key=String(key||"").trim(); if(!key)return; const rec=monitorContextTitleRecord(key);

  monitorContextTitles.set(key,{...rec,manual_title:"",context_title:"",context_summary:"",project_name:"",manual_locked:false,title_source:"BROWSER",title_updated_ms:Date.now(),signature:""}); persistMonitorContextTitles(); if(monitorLastAiState)renderWorkers(monitorLastAiState);

}
//@@FN_END:resetMonitorContextTitleToBrowser

//@@FN_START:runMonitorRoleAdminAction
async function runMonitorRoleAdminAction(action, roleRow, conversationKey="") {

  const role=String(roleRow?.role_id||""); const lock=action==="broadcast"?"broadcast":role; if(!lock||monitorRoleAdminInFlight.has(lock))return;

  if((action==="assign"||action==="replace")&&!String(conversationKey||"").trim()){setMonitorRoleAdminStatus("conversationKey 선택 필요",true);return;}

  monitorRoleAdminInFlight.add(lock); renderMonitorRoleAdmin(); setMonitorRoleAdminStatus(`${action}…`);

  try{const body=action==="broadcast"?{}:monitorRoleAdminPayload(action,roleRow,conversationKey);const r=await fetch(monitorRoleAdminPath(action),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const data=await r.json();if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);setMonitorRoleAdminStatus(action==="broadcast"?"상태 알림 전송됨":"적용됨");}

  catch(error){setMonitorRoleAdminStatus(monitorRoleAdminErrorText(error?.message||error),true);}

  finally{monitorRoleAdminInFlight.delete(lock);await refreshMonitorRoleAdmin();await refreshAiMonitor();renderMonitorRoleAdmin();}

}
//@@FN_END:runMonitorRoleAdminAction

//@@FN_START:runMonitorUtilityAction
async function runMonitorUtilityAction(button, pendingText, action) {
  if (!button || button.disabled) return;
  button.disabled = true;
  setMonitorStatus(pendingText, true, 5000);
  try {
    const result = await action();
    if (result?.ok === false) throw new Error(result.error || "복구 결과를 확인하지 못함");
    return result;
  } finally {
    button.disabled = false;
  }
}
//@@FN_END:runMonitorUtilityAction

//@@FN_START:scheduleMonitorBrowserVisualRefresh
function scheduleMonitorBrowserVisualRefresh(message) {
  const windowId = Number(message?.windowId);
  if (!Number.isInteger(windowId)) return;

  monitorBrowserVisualPendingWindowIds.add(windowId);
  if (monitorBrowserVisualRefreshTimer || monitorBrowserVisualRefreshInFlight) return;
  monitorBrowserVisualRefreshTimer = setTimeout(() => {
    monitorBrowserVisualRefreshTimer = 0;
    void flushMonitorBrowserVisualRefresh();
  }, MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS);
}
//@@FN_END:scheduleMonitorBrowserVisualRefresh

//@@FN_START:scheduleMonitorChatNavigationRefresh
function scheduleMonitorChatNavigationRefresh(message) {
  const tabId = Number(message?.tabId);
  if (!Number.isInteger(tabId) || tabId < 0) return;

  monitorChatNavigationPendingByTab.set(tabId, { ...message, tabId });
  if (monitorChatNavigationRefreshTimer) clearTimeout(monitorChatNavigationRefreshTimer);
  monitorChatNavigationRefreshTimer = setTimeout(async () => {
    monitorChatNavigationRefreshTimer = 0;
    const pending = [...monitorChatNavigationPendingByTab.values()];
    monitorChatNavigationPendingByTab.clear();
    if (!pending.length) return;

    try {
      await refreshMonitorEndpointRegistry();

      // Reuse the lightweight ACT state path once per event burst. Each event is
      // then applied to only its own browser window/HWND.
      await refreshMonitorConversationStateFast();
      const state = monitorLastAiState;
      let mappingMiss = false;
      for (const item of pending) {
        const result = applyMonitorChatNavigationIdentity(item, state);
        if (!result?.ok && result?.mappingMiss) mappingMiss = true;
      }

      // Full identity discovery is recovery-only and runs at most once for this
      // burst when targeted windowId -> HWND mapping is genuinely unavailable.
      if (mappingMiss && state) await refreshMonitorIdentityIndex(state, true);
    } catch (error) {
      console.warn("DesktopWindow Monitor chat navigation refresh failed", {
        tabIds: pending.map((item) => Number(item?.tabId)).filter(Number.isInteger),
        error: error?.message || String(error)
      });
    }
  }, 120);
}
//@@FN_END:scheduleMonitorChatNavigationRefresh

//@@FN_START:scheduleMonitorHoverRecheck
function scheduleMonitorHoverRecheck() {

  clearTimeout(monitorHoverRecheckTimer);

  monitorHoverRecheckTimer = setTimeout(() => {

    monitorHoverRecheckTimer = 0;

    recheckMonitorHover();

  }, 20);

}
//@@FN_END:scheduleMonitorHoverRecheck

//@@FN_START:scheduleMonitorPopupTopologyRefresh
function scheduleMonitorPopupTopologyRefresh(desktopIds) {
  for (const desktopId of desktopIds || []) {
    const key = String(desktopId || "").trim();
    if (key) monitorPopupTopologyPendingDesktopIds.add(key);
  }
  if (!monitorPopupTopologyPendingDesktopIds.size || monitorPopupTopologyRefreshTimer || monitorPopupTopologyRefreshInFlight) return;
  monitorPopupTopologyRefreshTimer = setTimeout(() => {
    monitorPopupTopologyRefreshTimer = 0;
    void flushMonitorPopupTopologyRefresh();
  }, MONITOR_POPUP_TOPOLOGY_REFRESH_DEBOUNCE_MS);
}
//@@FN_END:scheduleMonitorPopupTopologyRefresh

//@@FN_START:scheduleMonitorV2WindowRefresh
function scheduleMonitorV2WindowRefresh(event) {
  const id=String(event?.desktopId||"");
  const tile=[...monitorDesktopThumbs.children].find(t=>String(t.dataset.desktopId||"")===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  if (!visual?.isConnected || !globalThis.MonitorDesktopThumbnailV2) return false;
  // Source of pixels remains getDesktopVisualSnapshot/captureDesktopFrame only.
  // Never accept the old event's thumbnail-service snapshot, SVG or cache.
  void refreshDesktopThumb(visual,id).catch(()=>false);
  return true;
}
//@@FN_END:scheduleMonitorV2WindowRefresh

//@@FN_START:setMonitorManualContextTitle
function setMonitorManualContextTitle(key,title){

  key=String(key||"").trim(); title=String(title||"").trim(); if(!key)return;

  const rec=monitorContextTitleRecord(key); monitorContextTitles.set(key,{...rec,manual_title:title,manual_locked:Boolean(title),title_source:title?"MANUAL":"AI",title_updated_ms:Date.now()}); persistMonitorContextTitles(); if(monitorLastAiState)renderWorkers(monitorLastAiState);

}
//@@FN_END:setMonitorManualContextTitle

//@@FN_START:setMonitorRoleAdminStatus
function setMonitorRoleAdminStatus(text, bad=false) { const el=document.getElementById("monitorRoleAdminStatus"); if(!el)return; el.textContent=String(text||""); el.classList.toggle("error",Boolean(bad)); }
//@@FN_END:setMonitorRoleAdminStatus

//@@FN_START:setMonitorStatus
function setMonitorStatus(text, healthy, holdMs = 0) {

  if (!(Number(holdMs) > 0) && Date.now() < monitorStatusHoldUntil) return;

  if (Number(holdMs) > 0) monitorStatusHoldUntil = Date.now() + Number(holdMs);

  monitorService.textContent = text || (healthy ? "ACT 실행 중" : "ACT 꺼짐");

  monitorService.hidden = false;

  monitorService.classList.toggle("healthy", Boolean(healthy));


  const monitorServiceDiag = document.getElementById("monitorServiceDiag");


  if (monitorServiceDiag) {


    monitorServiceDiag.textContent = monitorService.textContent;


    monitorServiceDiag.classList.toggle("healthy", Boolean(healthy));


    monitorServiceDiag.style.color = healthy ? "rgba(154,236,181,.96)" : "rgba(255,211,145,.90)";


    monitorServiceDiag.title = monitorService.textContent;


  }

  monitorService.classList.toggle("unhealthy", !healthy);

}
//@@FN_END:setMonitorStatus

//@@FN_START:snapshotAllChromeHwnds
async function snapshotAllChromeHwnds() {

  const snap = await monitorNative({ type: "getAllChromeWindowHandles" }).catch(() => null);

  return new Set((Array.isArray(snap?.hwnds) ? snap.hwnds : []).map(String).filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0"));

}
//@@FN_END:snapshotAllChromeHwnds

//@@FN_START:syncMonitorPauseOverlay
function syncMonitorPauseOverlay(img, hwnd) {

  if (!img?.parentElement) return;

  const key = String(hwnd || "");

  let overlay = [...img.parentElement.querySelectorAll(".monitor-window-pause-overlay")].find((node)=>node.dataset.hwnd===key);

  const paused = img.classList.contains("monitor-window-paused");
  const userAttentionDetail = monitorHwndUserAttentionDetail(key, monitorLastAiState);
  const conversationKey=monitorVisualConversationForHwnd(key,monitorLastAiState);
  const completionDetail=monitorChatAlertDetail(conversationKey);

  const activity=monitorHwndIsGenerating(key, monitorLastAiState) ? "play" : (completionDetail?.activity || (paused ? "pause" : ""));
  const warning=userAttentionDetail?.warning === true || completionDetail?.warning === true;
  if (!activity && !warning) { overlay?.remove(); return; }

  if (!overlay) { overlay=document.createElement("span"); overlay.className="monitor-window-pause-overlay"; overlay.dataset.hwnd=key; img.parentElement.append(overlay); }

  const detail=userAttentionDetail||completionDetail||{tone:"general",label:"채팅 작업 완료"};

  delete overlay.dataset.symbol; overlay.title=detail.label;
  globalThis.MonitorStatusIcon?.render?.(overlay,{activity,warning});

  for(const tone of ["general","success","failure","review","question","input","action"]) overlay.classList.remove(`monitor-alert-tone-${tone}`);

  overlay.classList.add(`monitor-alert-tone-${detail.tone}`);

  overlay.classList.toggle("monitor-window-pause-overlay-thumb", img.classList.contains("monitor-desktop-thumb-window"));

  overlay.style.left=img.style.left; overlay.style.top=img.style.top; overlay.style.width=img.style.width; overlay.style.height=img.style.height;

  const z=Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)); overlay.style.zIndex=String(z);

}
//@@FN_END:syncMonitorPauseOverlay

//@@FN_START:syncMonitorPhysicalWorkplaces
async function syncMonitorPhysicalWorkplaces(state, force = false) {

  // Monitor is presentation/input UI and must never write physical workplace state.

  return;

}
//@@FN_END:syncMonitorPhysicalWorkplaces

//@@FN_START:syncMonitorSharedSelection
async function syncMonitorSharedSelection() {

  if (monitorSharedSelectionSyncBusy || monitorSharedSelectionWritePending > 0) return;

  monitorSharedSelectionSyncBusy = true;

  try { applyMonitorSharedSelection(await monitorNative({ type: "getSharedMonitorSelection" })); }

  catch (_) {}

  finally { monitorSharedSelectionSyncBusy = false; }

}
//@@FN_END:syncMonitorSharedSelection

//@@FN_START:syncMonitorStatusLayer
function syncMonitorStatusLayer(img, hwnd) {

  if (!img?.parentElement) return;

  const isThumb=img.classList.contains("monitor-desktop-thumb-window");

  const isPreview=img.classList.contains("monitor-window-preview");

  if (!isThumb && !isPreview) return;

  const key=String(hwnd||"");

  const surface=isThumb?"thumb":"preview";

  const parent=img.parentElement;

  let layer=[...parent.querySelectorAll(".monitor-window-status-layer")].find((node)=>node.dataset.hwnd===key&&node.dataset.surface===surface);

  if(!layer){

    layer=document.createElement("span");

    layer.className="monitor-window-status-layer";

    layer.dataset.hwnd=key;

    layer.dataset.surface=surface;

    layer.innerHTML='<span class="monitor-status-age"></span><span class="monitor-status-group"></span><span class="monitor-status-working"></span><span class="monitor-status-role"></span><span class="monitor-status-hover"></span><span class="monitor-status-selection"></span>';

  }

  if(img.nextElementSibling!==layer) parent.insertBefore(layer,img.nextSibling);

  layer.style.left=img.style.left;

  layer.style.top=img.style.top;

  layer.style.width=img.style.width;

  layer.style.height=img.style.height;

  const nativeZ=Math.max(1,Number(img.style.zIndex||img.dataset.nativeZIndex||1));

  layer.style.zIndex=String(nativeZ);

  const hue=img.style.getPropertyValue("--monitor-conversation-hue");

  if(hue) layer.style.setProperty("--monitor-conversation-hue",hue); else layer.style.removeProperty("--monitor-conversation-hue");

  const ageIdentity=monitorAgeIdentityForHwnd(key,monitorLastAiState);

  const age=Math.max(0,Math.min(100,Number(ageIdentity.ageing)||0));

  layer.style.setProperty("--monitor-window-age",`${age}%`);

  layer.classList.toggle("monitor-profile-google",ageIdentity.profileId==="GOOGLE");

  layer.classList.toggle("monitor-profile-naver",ageIdentity.profileId==="NAVER");

}
//@@FN_END:syncMonitorStatusLayer

//@@FN_START:syncMonitorTitle
function syncMonitorTitle() {

  if (!monitorTitle || !monitorTitleLine) return;

  const version = monitorExtensionVersion();
  monitorTitle.textContent = "BWM";
  if (monitorVersion) {
    monitorVersion.textContent = version ? `v${version}` : "버전 미확인";
    monitorVersion.title = version ? `실행 중인 BWM 버전 ${version} · BCT 연결 확인 중` : "실행 중인 확장 버전을 확인하지 못했습니다";
  }
  document.title = monitorWindowTitle();

}
//@@FN_END:syncMonitorTitle

//@@FN_START:toggleMonitorAutoProcess
async function toggleMonitorAutoProcess(){

  const next=!monitorAutoProcessEnabled;

  const r=await actFetch(ORCHESTRATOR_AUTO_PROCESS_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:next,scope_key:monitorStructureActiveScopeKey})});

  const d=await r.json();if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);monitorAutoProcessEnabled=Boolean(d.enabled);await refreshMonitorAutoProcess();showMonitorDiagText(`자동 처리: ${monitorAutoProcessEnabled?'ON · 새 결과를 감지하면 ORCHESTRATOR에 확인해 처리해 전송':'OFF · 결과는 ACT에만 보관'}`,false);

}
//@@FN_END:toggleMonitorAutoProcess

//@@FN_START:waitForNewChromeHwnd
async function waitForNewChromeHwnd(before, timeoutMs = 7000) {

  const started = Date.now();

  while (Date.now() - started < timeoutMs) {

    await new Promise((resolve) => setTimeout(resolve, 120));

    const now = await snapshotAllChromeHwnds();

    for (const hwnd of now) if (/^\d+$/.test(hwnd) && hwnd !== "0" && !before.has(hwnd)) return hwnd;

  }

  return "";

}
//@@FN_END:waitForNewChromeHwnd
