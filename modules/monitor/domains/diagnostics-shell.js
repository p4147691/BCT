//@@FN_START:applyMonitorWindowHighlight
function applyMonitorWindowHighlight(hwnd, options = {}) {

  const nextHwnd = String(hwnd || "");

  const changed = nextHwnd !== monitorHighlightedHwnd;

  if (!options.bctNode && !options.preserve && !options.remote) {
    monitorBctNodeHighlightedHwnd = "";
    monitorBctSelectedNodeKey = "";
  }

  if (options.preserve) { if (nextHwnd) monitorHighlightedHwnd = nextHwnd; }

  else if (options.toggle) {

    if (monitorSelectedHwnds.has(nextHwnd)) monitorSelectedHwnds.delete(nextHwnd); else if (nextHwnd) monitorSelectedHwnds.add(nextHwnd);

    monitorHighlightedHwnd = monitorSelectedHwnds.has(nextHwnd) ? nextHwnd : ([...monitorSelectedHwnds][0] || "");

  } else { monitorSelectedHwnds.clear(); if (nextHwnd) monitorSelectedHwnds.add(nextHwnd); monitorHighlightedHwnd = nextHwnd; }

  const previews = document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview");

  for (const preview of previews) {

    const selected = monitorSelectedHwnds.has(String(preview.dataset.hwnd || ""));

    preview.classList.toggle("monitor-window-highlighted", selected);

    preview.classList.toggle("monitor-window-row-hovered", !selected && Boolean(monitorHoveredHwnd) && String(preview.dataset.hwnd || "") === monitorHoveredHwnd);

    if (preview.dataset.nativeZIndex) preview.style.setProperty("z-index", preview.dataset.nativeZIndex, "important");

    syncMonitorPauseOverlay(preview, preview.dataset.hwnd || "");

  }

  for (const row of monitorWorkers.querySelectorAll(".monitor-worker-row")) {

    const selected = monitorSelectedHwnds.has(String(row.dataset.hwnd || ""));

    row.classList.toggle("monitor-worker-selected", selected);

    row.classList.toggle("monitor-worker-row-hovered", !selected && Boolean(monitorHoveredHwnd) && String(row.dataset.hwnd || "") === monitorHoveredHwnd);

    row.classList.remove("monitor-worker-select-pulse");

    if (selected && changed) { void row.offsetWidth; row.classList.add("monitor-worker-select-pulse"); }

  }

  syncMonitorBctNodeTargetHighlight();
  if (!options.remote && !options.preserve) publishMonitorSharedSelection();

}
//@@FN_END:applyMonitorWindowHighlight

//@@FN_START:applyMonitorWindowHover
function applyMonitorWindowHover(hwnd) {

  monitorHoveredHwnd = String(hwnd || "");

  for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const key = String(preview.dataset.hwnd || "");

    preview.classList.toggle("monitor-window-row-hovered", Boolean(monitorHoveredHwnd) && key === monitorHoveredHwnd && !monitorSelectedHwnds.has(key));

  }

  for (const row of monitorWorkers.querySelectorAll(".monitor-worker-row")) {

    const key = String(row.dataset.hwnd || "");

    row.classList.toggle("monitor-worker-row-hovered", Boolean(monitorHoveredHwnd) && key === monitorHoveredHwnd && !monitorSelectedHwnds.has(key));

  }

}
//@@FN_END:applyMonitorWindowHover

//@@FN_START:cloneMonitorWindowSet
async function cloneMonitorWindowSet(entries, targetDesktopId, undoKind = "window-copy", undoExtra = {}) {

  const createdHwnds = []; const failed = [];

  for (const entry of entries) {

    const profileId = monitorProfileIdForHwnd(entry.hwnd);

    if (!profileId) { failed.push(entry.hwnd); continue; }

    const before = await snapshotAllChromeHwnds();

    const foreground = await monitorNative({ type: "getForegroundWindow" }).catch(() => null);

    const launch = await monitorNative({ type: "launchChatGptWindowCopy", sourceHwnd: entry.hwnd, profileId }).catch(() => null);

    if (!launch?.ok) { failed.push(entry.hwnd); continue; }

    const hwnd = await waitForNewChromeHwnd(before);

    if (!hwnd) { failed.push(entry.hwnd); continue; }

    const moved = await monitorNative({ type: "moveWindowToDesktop", hwnd, desktopId: targetDesktopId }).catch(() => null);

    if (!moved?.ok) { failed.push(entry.hwnd); await monitorNative({ type: "closeWindow", hwnd }).catch(() => null); continue; }

    await monitorNative({ type: "setWindowBoundsNoActivate", hwnd, left: launch.left, top: launch.top, width: launch.width, height: launch.height }).catch(() => null);

    if (foreground?.hwnd) await monitorNative({ type: "restoreForegroundWindow", hwnd: String(foreground.hwnd) }).catch(() => null);

    createdHwnds.push(hwnd);

  }

  if (createdHwnds.length) {

    showDesktopUndo({ kind: undoKind, hwnds: createdHwnds, targetDesktopId, ...undoExtra });

    invalidateMonitorDesktopFrames(targetDesktopId);

    setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(targetDesktopId); }, 180);

  }

  if (failed.length) setMonitorStatus(`Window copy partial failure - ok ${createdHwnds.length} / fail ${failed.length}`, false);

  return failed.length === 0 && createdHwnds.length > 0;

}
//@@FN_END:cloneMonitorWindowSet

//@@FN_START:configureMonitorProviderLaunchButton
function configureMonitorProviderLaunchButton(button, provider) {
  const normalizedProvider = String(provider || "").toUpperCase() === "GOOGLE" ? "GOOGLE" : "NAVER";
  const name = normalizedProvider === "GOOGLE" ? "Google" : "Naver";
  const type = normalizedProvider === "GOOGLE" ? "launchGoogleChatGpt" : "launchNaverChatGpt";

  button.dataset.provider = normalizedProvider;
  button.textContent = normalizedProvider === "GOOGLE" ? "G+" : "N+";
  button.title = `${name} ChatGPT 새 창 열기`;
  button.setAttribute("aria-label", `${name} ChatGPT 새 창 열기`);
  button.disabled = false;

  button.addEventListener("click", async () => {
    try {
      const result = await monitorNativeLaunchIsolated({ type });
      if (!result?.ok || !result?.launched) {
        throw new Error(result?.error || `${name} ChatGPT 실행 실패`);
      }
    } catch (error) {
      setMonitorStatus(`${name} ChatGPT 실행 실패 · ${error?.message || error}`, false);
    }
  });
}
//@@FN_END:configureMonitorProviderLaunchButton

//@@FN_START:createMonitorWindowCaptureService
function createMonitorWindowCaptureService({ maxEntries, maxWidth, maxHeight, quality }) {
  return globalThis.MonitorThumbnailService.create({
  maxConcurrent: 2,
  maxEntries,
  maxWidth,
  maxHeight,
  async capture({ hwnd, reason, maxWidth, maxHeight }) {
    return monitorCaptureScheduler.run(async () => {
      monitorRenderDiagnostics.captureRuns += 1;
      const captureTitle=String(monitorWindowDesktopLocations.get(String(hwnd))?.title||"");
      const capturedAt=Date.now();
      const capture = await monitorCoreNative({
        type: "captureWindow",
        hwnd,
        maxWidth,
        maxHeight,
        quality,
        reason
      }).catch(() => null);
      const source = capture?.ok ? String(capture.dataUri || "") : "";
      if (!source || capture?.captureEngine !== "wgc-oneshot") {
        monitorRevokeThumbWindowCaptureSource(source);
        monitorRenderDiagnostics.captureFailure += 1;
        return null;
      }
      const objectUrl = monitorCaptureDataUriToObjectUrl(source);
      monitorRenderDiagnostics.captureSuccess += 1;
      return {
        value: objectUrl,
        dispose: () => monitorRevokeThumbWindowCaptureSource(objectUrl),
        meta: {
          captureEngine: capture.captureEngine,
          width: Number(capture.width || 0),
          height: Number(capture.height || 0),
          captureTitle,capturedAt
        }
      };
    });
  }
  });
}
//@@FN_END:createMonitorWindowCaptureService

//@@FN_START:drainMonitorWindowLifecycleEvents
async function drainMonitorWindowLifecycleEvents() {
  if (monitorWindowLifecycleDrainBusy) return;
  monitorWindowLifecycleDrainBusy = true;
  try {
    while (monitorWindowLifecyclePendingEvents.size) {
      const next = monitorWindowLifecyclePendingEvents.entries().next().value;
      if (!next) break;
      const [hwnd, event] = next;
      monitorWindowLifecyclePendingEvents.delete(hwnd);
      await handleMonitorWindowLifecycleEvent(event);
    }
  } finally {
    monitorWindowLifecycleDrainBusy = false;
    if (monitorWindowLifecyclePendingEvents.size) void drainMonitorWindowLifecycleEvents();
  }
}
//@@FN_END:drainMonitorWindowLifecycleEvents

//@@FN_START:handleMonitorWindowLifecycleEvent
async function handleMonitorWindowLifecycleEvent(event) {

  const hwnd=String(event?.hwnd||"").trim();

  if (!/^\d+$/.test(hwnd)||hwnd==="0") return;
  if (hwnd === String(monitorDesktopState.hostWindowHwnd || "")) {
    await chrome.runtime.sendMessage({ type:"monitor-save-popup-window-bounds" }).catch(() => null);
    return;
  }

  const prior=monitorWindowDesktopLocations.get(hwnd)||{};

  const desktopId=String(event?.desktopId||prior.desktopId||"").trim();
  if (!desktopId) {
    for (const tile of monitorDesktopThumbs.children) {
      const id=String(tile.dataset.desktopId||"");
      const visual=tile.querySelector(".monitor-desktop-thumb-visual");
      if (id&&visual?.isConnected) void refreshDesktopThumb(visual,id).catch(()=>false);
    }
    return;
  }

  const previousDesktopId=String(prior.desktopId||"").trim();

  const vw=Math.max(1,Number(event.previewVirtualWidth)||1), vh=Math.max(1,Number(event.previewVirtualHeight)||1);

  const vl=Number(event.previewVirtualLeft)||0, vt=Number(event.previewVirtualTop)||0;
  const lifecycleReason=String(event?.reason||"").toLowerCase();
  // Native notifications are allowed to use either `iconic: true` or the
  // lifecycle reason. The picture-hiding and node-badge paths must agree.
  const minimized=monitorMinimizedNodeBadgeContract?.minimizedEvent?.(event) || lifecycleReason==="minimized" || Boolean(event.iconic);
  const restoring=Boolean(prior.iconic)&&!minimized&&event.visible!==false;

  const apply=(img)=>{ img.style.display=(minimized||event.visible===false)?"none":""; img.style.left=`${((Number(event.left)-vl)/vw)*100}%`; img.style.top=`${((Number(event.top)-vt)/vh)*100}%`; img.style.width=`${(Number(event.width)/vw)*100}%`; img.style.height=`${(Number(event.height)/vh)*100}%`; syncMonitorStatusLayer(img,hwnd); syncMonitorPauseOverlay(img,hwnd); if(!restoring)syncMonitorDesktopNumberBadge(img,hwnd); syncMonitorNonChatCountdown(img,hwnd); };

  if (!previousDesktopId || previousDesktopId===desktopId) for (const img of document.querySelectorAll(`.monitor-window-preview[data-hwnd="${hwnd}"]`)) apply(img);

  // Position is event data, not a pixel capture. Apply it to the existing V2
  // HWND node immediately; the slower WGC refresh runs independently below.
  const eventTile=[...monitorDesktopThumbs.children].find((item)=>String(item.dataset.desktopId||"")===desktopId);
  const eventVisual=eventTile?.querySelector(".monitor-desktop-thumb-visual");
  globalThis.MonitorDesktopThumbnailV2?.windowEvent?.(eventVisual,desktopId,event);

  monitorWindowDesktopLocations.set(hwnd,{...prior,hwnd,desktopId,desktop:monitorDesktopState.desktopIds.indexOf(desktopId)+1,title:String(event.title||prior.title||""),className:String(event.className||prior.className||""),left:Number(event.left),top:Number(event.top),width:Number(event.width),height:Number(event.height),iconic:minimized,visible:event.visible!==false,at:Date.now()});
  syncMonitorMinimizedNodeBadges(monitorLastAiState);
  if (minimized) scheduleMonitorMinimizedBadgeConvergence(hwnd);
  const badgeTile=[...monitorDesktopThumbs.children].find((item)=>String(item.dataset.desktopId||"")===desktopId);
  const badgeVisual=badgeTile?.querySelector(".monitor-desktop-thumb-visual");
  if (restoring) {
    badgeVisual?.querySelectorAll(`.monitor-thumbnail-tab-badge[data-hwnd="${hwnd}"], .monitor-window-desktop-badge[data-hwnd="${hwnd}"]`).forEach((node)=>node.remove());
    for (const img of document.querySelectorAll(`.monitor-window-preview[data-hwnd="${hwnd}"], .monitor-desktop-thumb-window[data-hwnd="${hwnd}"]`)) syncMonitorDesktopNumberBadge(img,hwnd);
    if (badgeVisual?.isConnected) syncMonitorThumbnailTabBadges(badgeVisual,"monitor-desktop-thumb-window");
    void refreshMonitorConversationStateFast(true).catch(()=>{});
  } else if (badgeVisual?.isConnected) syncMonitorThumbnailTabBadges(badgeVisual,"monitor-desktop-thumb-window");

  const reason=String(event?.reason||"").toLowerCase();

  const lifecycleHidden=reason==="hidden"||minimized||event.visible===false;
  if (lifecycleHidden) {
    monitorThumbnailService.invalidate(hwnd);
    removeMonitorV2Window(hwnd);
  }

  if (lifecycleHidden) {

    invalidateMonitorDesktopFrames(desktopId);

    return;

  }

  const cloakEvent=reason==="cloaked"||reason==="uncloaked";
  if (cloakEvent) {
    monitorThumbnailService.invalidate(hwnd);
    scheduleMonitorV2WindowRefresh(event);
    return;
  }

  monitorThumbnailService.invalidate(hwnd);

  if (previousDesktopId && previousDesktopId!==desktopId) {
    void actFetch("act:/monitor/node-state/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(()=>refreshAiMonitor()).catch(()=>{});
    await actFetch("act:/monitor/node-state/refresh",{method:"POST"}).catch(()=>null);
    await refreshAiMonitor().catch(()=>{});

    removeMonitorV2Window(hwnd,desktopId);

    scheduleMonitorV2WindowRefresh(event);

    return;

  }

  invalidateMonitorDesktopFrames(desktopId);

  const selectedDesktopId=String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex]||"");
  const selectedDesktop=desktopId===selectedDesktopId;
  if (selectedDesktop) {
    scheduleMonitorV2WindowRefresh(event);
    return;
  }

  scheduleMonitorV2WindowRefresh(event);

}
//@@FN_END:handleMonitorWindowLifecycleEvent

//@@FN_START:monitorDiagTextError
function monitorDiagTextError(error){return String(error?.message||error||'unknown').slice(0,180);}
//@@FN_END:monitorDiagTextError

//@@FN_START:monitorExtensionVersion
function monitorExtensionVersion() {
  try { return String(globalThis.chrome?.runtime?.getManifest?.().version || "").trim(); }
  catch (_) { return ""; }
}
//@@FN_END:monitorExtensionVersion

//@@FN_START:monitorRenderDiagnosticText
function monitorRenderDiagnosticText(){
  const elapsedMs=Math.max(1,Date.now()-monitorRenderDiagnostics.startedAt);
  const elapsedSec=elapsedMs/1000;
  let visibleWorkers=0;
  try{
    if(monitorLastAiState){
      const projected=monitorWorkersProjectionForState(monitorLastAiState);
      visibleWorkers=projected.filter((worker)=>isMonitorVisibleWorker(worker,monitorLastAiState)).length;
    }
  }catch(_){}
  const documentNodes=document.getElementsByTagName("*").length;
  const monitorNodes=monitorRoot?.querySelectorAll?.("*")?.length||0;
  const workerDomNodes=monitorWorkers?.querySelectorAll?.("*")?.length||0;
  const requestRate=(monitorRenderDiagnostics.renderRequests/elapsedSec).toFixed(2);
  const runRate=(monitorRenderDiagnostics.renderRuns/elapsedSec).toFixed(2);
  const roughCreates=monitorRenderDiagnostics.renderRuns*visibleWorkers*15;
  const roughListeners=monitorRenderDiagnostics.renderRuns*visibleWorkers*14;
  const thumbnailStats=monitorThumbnailService?.stats?.()||{};
  return [
    "Monitor 런타임 진단",
    MonitorNativeTrace.export(),
    `build: ${MONITOR_BUILD_ID}`,
    `renderer 시작: ${new Date(monitorRenderDiagnostics.startedAt).toLocaleString()}`,
    `pixel visuals: ${MONITOR_PIXEL_VISUALS_ENABLED} · window capture: ${MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED}`,
    `renderWorkers 요청: ${monitorRenderDiagnostics.renderRequests} · ${requestRate}/s`,
    `전체 worker DOM 렌더: ${monitorRenderDiagnostics.renderRuns} · ${runRate}/s`,
    `ACT 전체 갱신: ${monitorRenderDiagnostics.refreshRuns}회 · 최근 ${Math.round(monitorRenderDiagnostics.refreshLastMs)}ms · 최장 ${Math.round(monitorRenderDiagnostics.refreshSlowestMs)}ms`,
    `ACT 갱신 단계(최근): ${Object.entries(monitorRenderDiagnostics.refreshLastStages||{}).map(([name,ms])=>`${name} ${Math.round(Number(ms)||0)}ms`).join(" · ")||"아직 없음"}`,
    `현재 visible workers: ${visibleWorkers}`,
    `DOM nodes: document ${documentNodes} · Monitor ${monitorNodes} · worker panel ${workerDomNodes}`,
    `현재 구조: worker당 createElement 15곳 · listener 14곳`,
    `현재 worker 수 기준 누적 생성부하 추정: DOM ${roughCreates} · listener ${roughListeners}`,
    `pending render: ${Boolean(monitorWorkerRenderPendingState)} · in-flight: ${Boolean(monitorWorkerRenderInFlight)}`,
    `thumbnail service: requested ${Number(thumbnailStats.requested||0)} · started ${Number(thumbnailStats.started||0)} · completed ${Number(thumbnailStats.completed||0)} · failed ${Number(thumbnailStats.failed||0)}`,
    `thumbnail live: active ${Number(thumbnailStats.active||0)} · queued ${Number(thumbnailStats.queuedNow||0)} · cached ${Number(thumbnailStats.cached||0)} · max active ${Number(thumbnailStats.maxObservedActive||0)}`,
    `thumbnail disposal: stale ${Number(thumbnailStats.staleDiscarded||0)} · evicted ${Number(thumbnailStats.evicted||0)} · disposed ${Number(thumbnailStats.disposedResults||0)}`,
  ].join("\n");
}
//@@FN_END:monitorRenderDiagnosticText

//@@FN_START:monitorWindowCanRefreshPixels
function monitorWindowCanRefreshPixels(item) {
  // A Shell-cloaked HWND can still yield its real WGC pixels.  The capture
  // result, not the virtual-desktop cloak flag, decides whether pixels exist.
  // Minimized windows are excluded earlier and have no current surface here.
  return Boolean(item) && item.iconic !== true;
}
//@@FN_END:monitorWindowCanRefreshPixels

//@@FN_START:monitorWindowCaptureService
function monitorWindowCaptureService(profile) {
  if (profile === "frozen") return monitorThumbnailCaptureServices.frozen;
  return profile === "preview" ? monitorThumbnailCaptureServices.preview : monitorThumbnailCaptureServices.thumb;
}
//@@FN_END:monitorWindowCaptureService

//@@FN_START:monitorWindowFallbackDataUri
function monitorWindowFallbackDataUri(item = null) {
  const policy = bwmUiLayoutControl?.read?.()?.captureFallback;
  if (policy?.mode !== "legacy") {
    // Transparent canvas keeps exact HWND geometry and drag target.
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270"><rect x="8" y="8" width="214" height="52" rx="8" fill="#1b2431" fill-opacity=".94" stroke="#56687e"/><rect x="19" y="19" width="26" height="28" rx="4" fill="#3b82f6"/><path d="M26 28h13m-13 6h13m-13 6h10" stroke="#fff" stroke-width="2"/><text x="55" y="39" fill="#e8edf5" font-family="Segoe UI,sans-serif" font-size="17">Preview unavailable</text></svg>';
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }
  const title = String(item?.title || "창 미리보기").trim() || "창 미리보기";
  const label = title.length > 18 ? `${title.slice(0, 17)}…` : title;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270"><rect width="480" height="270" fill="#161a20"/><rect x="18" y="18" width="444" height="234" rx="14" fill="#202630" stroke="#475160" stroke-width="2"/><rect x="42" y="52" width="46" height="46" rx="8" fill="#3b82f6"/><path d="M53 65h24v5H53zm0 10h24v5H53zm0 10h16v5H53z" fill="#fff"/><text x="106" y="82" fill="#e8edf5" font-family="Segoe UI, sans-serif" font-size="22">${label.replace(/[&<>]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;"})[character])}</text><text x="42" y="132" fill="#9aa6b5" font-family="Segoe UI, sans-serif" font-size="16">미리보기 대신 앱 정보 표시</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
//@@FN_END:monitorWindowFallbackDataUri

//@@FN_START:monitorWindowTitle
function monitorWindowTitle() {
  const version = monitorExtensionVersion();
  return version ? `BCT Window Monitor · ${version}` : "BCT Window Monitor";
}
//@@FN_END:monitorWindowTitle

//@@FN_START:monitorWindowUsesFrozenCapture
function monitorWindowUsesFrozenCapture(item) {
  return monitorIsOwnWindowTitle(item?.title);
}
//@@FN_END:monitorWindowUsesFrozenCapture

//@@FN_START:moveMonitorWindowSet
async function moveMonitorWindowSet(entries, targetDesktopId, undoKind = "window-move", undoExtra = {}) {

  const uniqueEntries = [...new Map((Array.isArray(entries) ? entries : []).filter((entry)=>entry?.hwnd).map((entry)=>[String(entry.hwnd), entry])).values()];

  const eligible = uniqueEntries.filter((entry)=>entry.sourceDesktopId && entry.sourceDesktopId !== targetDesktopId);

  const moved = [];

  for (const entry of eligible) {

    const result = await monitorNative({ type: "moveWindowToDesktop", hwnd: entry.hwnd, desktopId: targetDesktopId }).catch(() => null);

    if (result?.ok) moved.push({ hwnd: entry.hwnd, desktopId: entry.sourceDesktopId });

  }

  if (moved.length) {

    showDesktopUndo({ kind: undoKind, entries: moved, targetDesktopId, ...undoExtra });

    invalidateMonitorDesktopFrames(...eligible.map((x) => x.sourceDesktopId), targetDesktopId);

    setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(...eligible.map((x) => x.sourceDesktopId), targetDesktopId); }, 120);

    setTimeout(() => { void refreshAiMonitor(); }, 260);

  }

  return moved.length === eligible.length;

}
//@@FN_END:moveMonitorWindowSet

//@@FN_START:normalizeMonitorWindowTitle
function normalizeMonitorWindowTitle(value) { return String(value || "").trim().replace(/\s+-\s+(?:Google\s+)?Chrome$/i, "").trim(); }
//@@FN_END:normalizeMonitorWindowTitle

//@@FN_START:refreshActHealth
async function refreshActHealth() {

  try {

    const response = await actFetch(ORCHESTRATOR_HEALTH_URL, { cache: "no-store" });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const health = await response.json();

    if (!health?.ok || health?.service !== "Agent Orchestrator") throw new Error("ACT health unavailable");

    const recovered = monitorActHealthWasDown;

    monitorActHealthWasDown = false;

    setMonitorStatus("ACT 실행 중", true);

    if (recovered) await refreshAiMonitor();

  } catch (_) {

    monitorActHealthWasDown = true;

    setMonitorStatus("ACT 연결 끊김", false);

  }

}
//@@FN_END:refreshActHealth

//@@FN_START:refreshMonitorActDiagnostic
async function refreshMonitorActDiagnostic(){

  try{

    const response=await actFetch(ORCHESTRATOR_HEALTH_URL,{cache:'no-store'});

    if(!response.ok)throw new Error(`HTTP ${response.status}`);

    const health=await response.json();

    const good=health?.ok===true && health?.service==='Agent Orchestrator';

    monitorDiagAct.textContent=`ACT: ${good?'OK':'DOWN'}`;

    monitorDiagAct.title='';
    monitorDiagAct.classList.toggle('is-on',good);
    monitorDiagAct.classList.toggle('is-error',!good);
    monitorDiagAct.classList.remove('is-unknown','is-off','is-warn');

  }catch(e){

    monitorDiagAct.textContent='ACT: ERROR';
    monitorDiagAct.title=monitorDiagTextError(e);
    monitorDiagAct.classList.remove('is-on','is-off','is-warn','is-unknown');
    monitorDiagAct.classList.add('is-error');

  }

}
//@@FN_END:refreshMonitorActDiagnostic

//@@FN_START:refreshMonitorCurrentDiagnosticView
async function refreshMonitorCurrentDiagnosticView(){
  const button=document.getElementById('monitorDiagRefresh');
  if(button?.disabled)return;
  const active=monitorDiagnostics.querySelector('[data-monitor-diag-view].is-active');
  const view=String(active?.dataset?.monitorDiagView||'overview');
  const label=String(active?.textContent||view);
  if(button){button.disabled=true;button.classList.add('is-refreshing');}
  try{
    if(view==='overview'){
      await Promise.allSettled([refreshMonitorActDiagnostic(),refreshMonitorAutoProcess()]);
      showMonitorDiagText(`종합 관제\n${monitorDiagAct.textContent} · ${monitorAutoProcessQuick.textContent}\n현재 관제 상태를 다시 확인했습니다.`);
      return;
    }
    if(view==='act'){
      await refreshMonitorActDiagnostic();
      showMonitorDiagText(`ACT 관제\n${monitorDiagAct.textContent}`);
      return;
    }
    if(view==='monitor'){
      showMonitorDiagText(monitorRenderDiagnosticText());
      return;
    }
    showMonitorDiagText(`${label} 관제 · 세부 수집기 연결 전`);
  }finally{
    if(button){button.disabled=false;button.classList.remove('is-refreshing');}
  }
}
//@@FN_END:refreshMonitorCurrentDiagnosticView

//@@FN_START:scheduleMonitorWindowLifecycleEvent
function scheduleMonitorWindowLifecycleEvent(event) {
  const hwnd = String(event?.hwnd || "").trim();
  if (!/^\d+$/.test(hwnd) || hwnd === "0") return;
  monitorWindowLifecyclePendingEvents.set(hwnd, event);
  if (!monitorWindowLifecycleDrainBusy) void drainMonitorWindowLifecycleEvents();
}
//@@FN_END:scheduleMonitorWindowLifecycleEvent

//@@FN_START:showMonitorDiagText
function showMonitorDiagText(text){monitorDiagLog.textContent=String(text||'');monitorDiagLog.hidden=false;monitorDiagLogCopyState.textContent='';}
//@@FN_END:showMonitorDiagText
