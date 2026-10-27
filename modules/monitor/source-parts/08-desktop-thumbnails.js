/*@@MONITOR_FUNCTION:syncDesktopSwitcher@@*/

/*@@MONITOR_FUNCTION:refreshObservedWindows@@*/

globalThis.addEventListener("bwm-thumbnail-policy-changed", () => {
  const ids = [...(monitorDesktopState.desktopIds || [])].filter(Boolean);
  if (!ids.length || !monitorIsActiveDesktopRenderer()) return;
  invalidateMonitorDesktopFrames(...ids);
  void refreshSelectedThumb().catch(() => false);
  void refreshBackgroundThumbs(...ids).catch(() => []);
});
/*@@MONITOR_FUNCTION:refreshSelectedThumb@@*/

/*@@MONITOR_FUNCTION:refreshInitialWindowThumbs@@*/

/*@@MONITOR_FUNCTION:refreshInitialSelectedThumb@@*/

/*@@MONITOR_FUNCTION:refreshBackgroundThumbs@@*/

/*@@MONITOR_FUNCTION:scheduleInitialSemanticThumbSync@@*/

let monitorThumbnailLayoutSignature = "";

/*@@MONITOR_FUNCTION:applyMonitorLiveWindowGeometry@@*/

/*@@MONITOR_FUNCTION:monitorThumbnailLayoutWatch@@*/

let monitorWindowsStateRefreshBusy = false;

/*@@MONITOR_FUNCTION:refreshWindowsCurrentState@@*/

/*@@MONITOR_FUNCTION:renderLightweightDesktopCards@@*/

/*@@MONITOR_FUNCTION:renderVirtualDesktops@@*/

let monitorHostResolveRetryCount = 0;

let monitorHostResolveRetryTimer = 0;

/*@@MONITOR_FUNCTION:refreshVirtualDesktops@@*/

/*@@MONITOR_FUNCTION:flashDesktopTransition@@*/

/*@@MONITOR_FUNCTION:primeSelectedDesktopPreview@@*/

/*@@MONITOR_FUNCTION:selectVirtualDesktopPreview@@*/

/*@@MONITOR_FUNCTION:expireDesktopUndoSession@@*/

/*@@MONITOR_FUNCTION:resetDesktopUndoSessionExpiry@@*/

/*@@MONITOR_FUNCTION:pushDesktopUndoSnapshot@@*/

/*@@MONITOR_FUNCTION:peekDesktopUndoSnapshot@@*/

/*@@MONITOR_FUNCTION:commitDesktopUndoRestore@@*/

/*@@MONITOR_FUNCTION:updateDesktopUndoUi@@*/

/*@@MONITOR_FUNCTION:showDesktopUndo@@*/

/*@@MONITOR_FUNCTION:updateDeletedDesktopTrashUi@@*/

/*@@MONITOR_FUNCTION:showDeletedDesktopTrashUndo@@*/

/*@@MONITOR_FUNCTION:undoDeletedDesktopTrash@@*/

/*@@MONITOR_FUNCTION:removeVirtualDesktopPreview@@*/

/*@@MONITOR_FUNCTION:removeCreatedDesktopIfSafe@@*/

monitorDesktopUndoButton.addEventListener("click", async () => {

  updateDesktopUndoUi(); const snapshot = peekDesktopUndoSnapshot(); if (!snapshot) return; monitorDesktopUndoButton.disabled = true;

  try {

    if (["window-move", "create-move"].includes(snapshot.kind)) {

      for (const entry of Array.isArray(snapshot.entries) ? snapshot.entries : []) await monitorNative({ type: "moveWindowToDesktop", hwnd: String(entry.hwnd), desktopId: String(entry.desktopId) }).catch(() => null);

      if (snapshot.kind === "create-move") await removeCreatedDesktopIfSafe(snapshot);

      commitDesktopUndoRestore(); updateDesktopUndoUi(); await refreshVirtualDesktops(); refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(...(Array.isArray(snapshot.entries) ? snapshot.entries.map((entry)=>String(entry.desktopId||"")) : []), String(snapshot.targetDesktopId||"")); return;

    }

    if (["window-copy", "create-copy"].includes(snapshot.kind)) {

      for (const hwnd of Array.isArray(snapshot.hwnds) ? snapshot.hwnds : []) await monitorNative({ type: "closeWindow", hwnd: String(hwnd) }).catch(() => null);

      if (snapshot.kind === "create-copy") await removeCreatedDesktopIfSafe(snapshot);

      commitDesktopUndoRestore(); updateDesktopUndoUi(); refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(String(snapshot.targetDesktopId||"")); return;

    }

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const result = await monitorNative({ type: "restoreVirtualDesktop", hwnds: snapshot.hwnds });

    if (!result?.ok) throw new Error(result?.error || "데스크톱 복구 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const restoredId = resultIds.find((id) => !beforeIds.has(id)) || resultIds[resultIds.length - 1] || null;

    commitDesktopUndoRestore(); updateDesktopUndoUi();

    monitorDesktopState.observedDesktopId = restoredId;

    renderVirtualDesktops(result); selectVirtualDesktopPreview(monitorDesktopState.selectedIndex); settleNewDesktopWallpaper(restoredId).catch(() => {});

  } catch (error) { setMonitorStatus(`데스크톱 복구 실패 · ${error?.message || error}`, false); }

  finally { monitorDesktopUndoButton.disabled = false; }

});

/*@@MONITOR_FUNCTION:settleNewDesktopWallpaper@@*/

monitorCreateDesktop.addEventListener("click", async () => {

  if (Date.now() < monitorCreateDesktopDropConsumedUntil || monitorCreateDesktopDropBusy) return;

  monitorCreateDesktop.disabled = true;

  try {

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const result = await monitorNative({ type: "createVirtualDesktop" });

    if (!result?.ok) throw new Error(result?.error || "새 데스크톱 생성 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const createdId = resultIds.find((id) => !beforeIds.has(id)) || resultIds[resultIds.length - 1] || null;

    monitorDesktopState.observedDesktopId = createdId;

    renderVirtualDesktops(result);

    selectVirtualDesktopPreview(monitorDesktopState.selectedIndex);

    settleNewDesktopWallpaper(createdId).catch(() => {});

  } catch (error) {

    monitorCreateDesktop.title = error?.message || String(error);

  } finally { monitorCreateDesktop.disabled = false; }

});

let monitorExpandedGeometry = null;

monitorCollapse.addEventListener("click", () => {

  const wasCollapsed = monitorRoot.classList.contains("collapsed");

  if (!wasCollapsed) {

    const rootRect = monitorRoot.getBoundingClientRect();

    monitorExpandedGeometry = {

      top: rootRect.top,

      right: Math.max(0, window.innerWidth - rootRect.right),

      width: rootRect.width,

      height: rootRect.height

    };

    monitorRoot.style.width = "";

    monitorRoot.style.height = "";

    monitorRoot.classList.add("collapsed");

    monitorRoot.style.left = "auto";

    monitorRoot.style.right = `${Math.round(monitorExpandedGeometry.right)}px`;

    monitorRoot.style.top = `${Math.round(monitorExpandedGeometry.top)}px`;

  } else {

    monitorRoot.classList.remove("collapsed");

    monitorRoot.style.left = "auto";

    monitorRoot.style.right = `${Math.round(monitorExpandedGeometry?.right ?? 12)}px`;

    monitorRoot.style.top = `${Math.round(monitorExpandedGeometry?.top ?? 12)}px`;

    if (monitorExpandedGeometry?.width) monitorRoot.style.width = `${Math.round(monitorExpandedGeometry.width)}px`;

    if (monitorExpandedGeometry?.height) monitorRoot.style.height = `${Math.round(monitorExpandedGeometry.height)}px`;

  }

  const collapsed = monitorRoot.classList.contains("collapsed");

  if (collapsed && monitorStructureOpen) closeMonitorStructure();

  document.body.classList.toggle("desktop-window-monitor-collapsed", collapsed);
  if (!collapsed) requestAnimationFrame(syncMonitorPanelToDesktopSwitcher);

  syncMonitorSideNote();

  monitorCollapse.classList.toggle("is-collapsed", collapsed);

  monitorCollapse.title = collapsed ? "Monitor 펼치기" : "Monitor 접기";

  if (!collapsed) {

    refreshObservedWindows();

    refreshSelectedThumb();

  }

});

let monitorDeploymentCheckBusy = false;
let monitorDeploymentCheckQueued = false;

let monitorReloadToken = null;
let monitorReloadAckToken = "";
let monitorDeploymentReloadRequested = false;

/*@@MONITOR_FUNCTION:checkMonitorDeploymentUpdate@@*/

// Desktop selection is synchronized through the Native shared selection state so

// NAVER/GOOGLE Chrome profiles observe the same desktop.

monitorSharedSelectionReady = true;

if (MONITOR_ACTIVE_STARTUP_ENABLED) {
  chrome.storage.local.get([MONITOR_POST_WORK_STORAGE_KEY, MONITOR_LLM_CACHE_STORAGE_KEY, MONITOR_AI_STATE_CACHE_KEY], (data) => {
    const saved=data?.[MONITOR_POST_WORK_STORAGE_KEY]||{};
    for(const key of Array.isArray(saved.worked)?saved.worked:[]) monitorWorkedConversationKeys.add(String(key));
    for(const key of Array.isArray(saved.acknowledged)?saved.acknowledged:[]) monitorAcknowledgedPostWork.add(String(key));
    for(const reportId of Array.isArray(saved.acknowledgedReports)?saved.acknowledgedReports:[]) monitorAcknowledgedReportIds.add(String(reportId));
    for(const key of Array.isArray(saved.alerts)?saved.alerts:[]) monitorPostWorkAlerts.add(String(key));
    for(const [key,detail] of Object.entries(saved.details||{})) if(key&&detail&&typeof detail==="object") monitorChatAlertDetails.set(String(key),detail);
    for(const key of monitorPostWorkAlerts) if(!monitorChatAlertDetails.has(key)) monitorChatAlertDetails.set(key,{symbol:"!",tone:"general",label:"채팅 작업 완료"});
    const observed=Number(saved.lastObservedAt||0); if(Number.isFinite(observed)&&observed>0) monitorPostWorkLastObservedAt=observed;
    monitorCachedLlmNodes = Array.isArray(data?.[MONITOR_LLM_CACHE_STORAGE_KEY]) ? data[MONITOR_LLM_CACHE_STORAGE_KEY] : [];
    const cachedAiState=data?.[MONITOR_AI_STATE_CACHE_KEY];
    if(cachedAiState?.state?.ok===true && Date.now()-Number(cachedAiState?.at||0)<=MONITOR_AI_STATE_CACHE_TTL_MS){
      monitorLastAiState=cachedAiState.state;
      renderWorkers(monitorLastAiState);
    }
    monitorPostWorkStorageReady=true;
    if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) {
      void monitorSyncSharedState("startup", true);
      void (async () => {
        try { await refreshMonitorEndpointRegistry(); }
        catch (error) { console.warn("BCT Window Monitor legacy endpoint reconciliation failed", error); }
        await refreshAiMonitor();
      })();
      scheduleMonitorStartupRecovery();
    }
  });
  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();
  void refreshWindowsCurrentState();
  checkMonitorDeploymentUpdate();
}

// Lightweight endpoint/node-state refresh keeps same-tab conversation changes responsive
// without running the heavier full refresh/sync pipeline for every state change.
let monitorConversationStateRefreshBusy = false;
let monitorConversationStateForceBadgeSyncPending = false;
let monitorConversationStateSignatureCache = "";

/*@@MONITOR_FUNCTION:monitorConversationStateSignature@@*/

/*@@MONITOR_FUNCTION:refreshMonitorConversationStateFast@@*/

if (MONITOR_ACTIVE_STARTUP_ENABLED && MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) void refreshMonitorConversationStateFast();
if (MONITOR_ACT_STARTUP_TEST_ENABLED) {
  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();
  void (async () => {
    try { await refreshMonitorEndpointRegistry(); }
    catch (error) { console.warn("DesktopWindow Monitor ACT-only endpoint reconciliation failed", error); }
    await refreshAiMonitor();
  })();
  void refreshMonitorConversationStateFast();
}

// ACT health is checked only on startup/focus/actions; no periodic liveness polling.

// Shared runtime sync is event-driven: startup/focus/state changes.

// Windows desktop structure + window layout now share one adaptive Native Host polling loop.

// Non-chat countdown updates are event-driven; no global 1s countdown loop.

// monitorThumbnailLayoutWatch is driven by refreshWindowsCurrentState().

// Shared desktop selection is read on startup/focus; local changes publish immediately.

// Post-work acknowledgement shares the single foreground click sampler below; do not consume click state in a second poll.

// Thumbnail pixels refresh only when window layout changes or an explicit UI event requests it.

// Deployment/reload checks are event-driven: startup/focus.

let monitorFocusRefreshQueued = false;

window.addEventListener("focus", () => {
  if (!MONITOR_ACTIVE_STARTUP_ENABLED) return;
  if (monitorFocusRefreshQueued) return;
  monitorFocusRefreshQueued = true;
  queueMicrotask(() => {
  monitorFocusRefreshQueued = false;

  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();

  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshAiMonitor();

  void refreshMonitorBctStatus();
  void refreshMonitorBctWindowNodes();

  void refreshWindowsCurrentState();

  void monitorSyncSharedState("focus", true);

  void monitorNotesFeature.refreshContent();

  void monitorNotesFeature.refreshView();

  void checkMonitorDeploymentUpdate();

  });

});

/* MONITOR_BOTTOM_DIAGNOSTICS_V1 */

const monitorAutoProcessQuick=document.createElement("button");

monitorAutoProcessQuick.id="monitorAutoProcessQuick";

monitorAutoProcessQuick.type="button";

monitorAutoProcessQuick.textContent="자동 처리 OFF";

monitorAutoProcessQuick.className="monitor-diagnostics-status-item monitor-diagnostics-status-toggle is-unknown";

const monitorStructureQuick=document.createElement("button");

monitorStructureQuick.id="monitorStructureQuick"; monitorStructureQuick.type="button"; monitorStructureQuick.textContent="조직도";

document.getElementById("monitorNodeSync")?.after(monitorStructureQuick);

const monitorStructurePanel=document.createElement("aside"); monitorStructurePanel.id="monitorStructurePanel"; monitorStructurePanel.hidden=true;

monitorStructurePanel.style.cssText="position:fixed;z-index:2147483646;right:22px;top:72px;width:min(520px,calc(100vw - 44px));max-height:calc(100vh - 120px);overflow:auto;padding:12px;border:1px solid rgba(255,255,255,.20);border-radius:12px;background:rgba(10,14,20,.97);box-shadow:0 14px 44px rgba(0,0,0,.55);color:#eef3f8;font:12px/1.4 'Segoe UI','Malgun Gothic',sans-serif";

monitorStructurePanel.innerHTML=`<div class="monitor-org-head"><strong>조직도</strong><button id="monitorStructureClose" type="button">×</button></div><div class="monitor-org-pyramid"><svg id="monitorStructureLinks" class="monitor-org-links" aria-hidden="true"></svg><div id="monitorStructureManagers" class="monitor-org-managers"></div><div class="monitor-org-codex-manager"><strong>CODEX MANAGER</strong><div id="monitorStructureCodexManagerState" class="monitor-org-codex-manager-state">UNASSIGNED ? CODEX workspace</div><small>Dedicated code-management slot; real ChatGPT Manager identity is assigned separately.</small></div><div class="monitor-org-resource-pool-title">Shared AI Resource Pool <small>ACT state view ? execution owned by ACT/Hybrid</small></div><div class="monitor-org-resource-pools"><section><strong>LOCAL</strong><div id="monitorStructureLocalPool" class="monitor-org-resource-pool"></div></section><section><strong>EXTERNAL</strong><div id="monitorStructureExternalPool" class="monitor-org-resource-pool"></div></section><section class="monitor-org-codex-pool"><strong>CODEX</strong><div id="monitorStructureCodexPool" class="monitor-org-resource-pool"></div></section></div></div><div id="monitorStructureStatus" class="monitor-org-status">노드 드래그: 빈 역할 노드 또는 +에 놓아 Desk 이동 · 노드에 놓아 연결 · 선=실제 관리 연결 · 실행 후 ACT 확정</div><div class="monitor-org-actions"><button id="monitorStructureUndo" type="button" class="monitor-org-history" title="조직도 변경 되돌리기" aria-label="조직도 변경 되돌리기" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7 4 12l5 5M5 12h8a6 6 0 0 1 6 6"/></svg></button><button id="monitorStructureRedo" type="button" class="monitor-org-history" title="조직도 변경 다시하기" aria-label="조직도 변경 다시하기" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 7 5 5-5 5m4-5h-8a6 6 0 0 0-6 6"/></svg></button><button id="monitorStructureClear" type="button" class="monitor-org-clear" title="마지막 안정 조직도 상태로 되돌리기">초기화</button><button id="monitorStructureAutoLayout" type="button" title="현재 실제 노드 위치 기준으로 다시 배치">자동배치</button><button id="monitorStructurePlacementSave" type="button" title="역할·관리선은 확정하지 않고 실제 Desk 위치만 적용">위치 변경 확정</button><button id="monitorStructureSave" type="button" class="monitor-org-save">실행</button></div>`;

document.body.append(monitorStructurePanel);

// Organization-chart presentation is canonical in monitor.css (MONITOR_ORG_UI_CANONICAL_V1).

let monitorStructureHtmlDragGhost=null;

/*@@MONITOR_FUNCTION:monitorStructureFinishHtmlDragGhost@@*/

/*@@MONITOR_FUNCTION:monitorStructureTrackHtmlDragGhost@@*/

/*@@MONITOR_FUNCTION:monitorStructureUseNodeDragGhost@@*/

document.addEventListener("dragover",monitorStructureTrackHtmlDragGhost,true);
document.addEventListener("dragend",monitorStructureFinishHtmlDragGhost,true);
document.addEventListener("drop",monitorStructureFinishHtmlDragGhost,true);

const monitorDiagnostics=document.createElement("details");

monitorDiagnostics.className="monitor-bottom-diagnostics";
monitorDiagnostics.hidden=true;

monitorDiagnostics.innerHTML=`<summary class="monitor-diagnostics-summary"><span class="monitor-diagnostics-label">진단</span><span id="monitorServiceDiag" class="monitor-diagnostics-message">ACT 확인 중…</span><button id="monitorDiagToggle" class="monitor-diagnostics-toggle" type="button" title="진단 상세 화면 펼치기/접기" aria-label="진단 상세 화면 펼치기">펼치기</button></summary><div class="monitor-diagnostics-body"><div class="monitor-diagnostics-topline"><div id="monitorDiagStatusBar" class="monitor-diagnostics-status-bar"><span id="monitorDiagAct" class="monitor-diagnostics-status-item is-unknown">ACT: ?</span></div><div class="monitor-diagnostics-toolbar"><span id="monitorDiagLogCopyState" class="monitor-diagnostics-copy-state"></span><button id="monitorDiagLogCopy" class="monitor-diagnostics-icon-button" type="button" title="현재 관제 내용 복사" data-tip="현재 관제 내용 복사" aria-label="현재 관제 내용 복사"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7h11v13H8z"></path><path d="M5 17H3V4h11v2"></path></svg></button><button id="monitorDiagRefresh" class="monitor-diagnostics-icon-button" type="button" title="현재 선택한 관제 정보 다시 확인" data-tip="현재 선택한 관제 정보 다시 확인" aria-label="현재 선택한 관제 정보 다시 확인"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66"></path><path d="M20 4v7h-7"></path></svg></button></div></div><pre id="monitorDiagLog" class="monitor-diagnostics-log">종합 관제 · 아래 항목을 선택하면 이 영역에 세부 정보가 표시됩니다.</pre><div id="monitorDiagFooter" class="monitor-diagnostics-footer"><div class="monitor-diagnostics-tabs"><button class="monitor-diagnostics-tab is-active" type="button" data-monitor-diag-view="overview">종합</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="act">ACT</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="github">GitHub</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="monitor">Monitor</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="console">Console</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="windows">Windows</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="runner">Runner</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="rcc">RCC</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="rally">Rally</button></div></div></div>`;

monitorRoot.append(monitorDiagnostics);

const monitorServiceDiagInitial=document.getElementById('monitorServiceDiag');


if(monitorServiceDiagInitial && monitorService){


  monitorServiceDiagInitial.textContent=monitorService.textContent;


  const healthy=monitorService.classList.contains('healthy');


  monitorServiceDiagInitial.classList.toggle('healthy',healthy);


  monitorServiceDiagInitial.style.color=healthy?"rgba(154,236,181,.96)":"rgba(255,211,145,.90)";


  monitorServiceDiagInitial.title=monitorService.textContent;


}

const monitorDiagAct=document.getElementById('monitorDiagAct');

const monitorDiagLog=document.getElementById('monitorDiagLog');

const monitorDiagLogCopyState=document.getElementById('monitorDiagLogCopyState');

const monitorDiagToggle=document.getElementById('monitorDiagToggle');
const monitorDiagStatusBar=document.getElementById('monitorDiagStatusBar');
monitorAutoProcessQuick.textContent='AUTO: ?';
monitorAutoProcessQuick.title='자동 처리 상태 · 클릭하여 ON/OFF';
monitorDiagStatusBar?.append(monitorAutoProcessQuick);

let monitorAutoProcessEnabled=false;

/*@@MONITOR_FUNCTION:monitorStructureNodeFromWorker@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeIdentityTokens@@*/

/*@@MONITOR_FUNCTION:monitorStructureAvailableNodes@@*/
