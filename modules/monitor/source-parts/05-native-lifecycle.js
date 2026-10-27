/*@@MONITOR_FUNCTION:openMonitorBctRenameEditor@@*/

let monitorBctNodeInteractionService = null;
const monitorBctCollapsedScopes = new Set();
const monitorBctCollapsedWindowCards = new Set();
let monitorBctSuppressedClickKey = "";
let monitorBctSuppressScopeClickUntil = 0;

/*@@MONITOR_FUNCTION:installMonitorBctManagerLongPress@@*/

/*@@MONITOR_FUNCTION:getMonitorBctNodeInteractionService@@*/

/*@@MONITOR_FUNCTION:resolveMonitorBctNodeHwnd@@*/

/*@@MONITOR_FUNCTION:resolveMonitorBctNodeDisplayHwnd@@*/

/*@@MONITOR_FUNCTION:compareMonitorBctNodeDisplayOrder@@*/

/*@@MONITOR_FUNCTION:monitorBctSharedWindowGroups@@*/

/*@@MONITOR_FUNCTION:monitorFocusBctSharedWindowTab@@*/

/*@@MONITOR_FUNCTION:renderMonitorBctWindowNodes@@*/

/*@@MONITOR_FUNCTION:beginMonitorBctNodePointerDrag@@*/

/*@@MONITOR_FUNCTION:monitorBctStopDragInput@@*/

/*@@MONITOR_FUNCTION:monitorBctPointInsideScopeHeading@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeInsertionAt@@*/

// Keep the hit-zone and the visual insertion line governed by the SAME resolver.
const MONITOR_BCT_DROP_EDGE_X_PX = 22;
const MONITOR_BCT_DROP_EDGE_Y_PX = 10;
/*@@MONITOR_FUNCTION:monitorBctNodeDropListAt@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeDropAt@@*/

/*@@MONITOR_FUNCTION:updateMonitorBctNodePointerDrag@@*/

/*@@MONITOR_FUNCTION:endMonitorBctNodePointerDrag@@*/

/*@@MONITOR_FUNCTION:cancelMonitorBctNodePointerDrag@@*/

/*@@MONITOR_FUNCTION:clearMonitorBctNodeDropFeedback@@*/

/*@@MONITOR_FUNCTION:finishMonitorBctNodeDrag@@*/

/*@@MONITOR_FUNCTION:commitMonitorBctNodeDrop@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctWindowNodes@@*/

/*@@MONITOR_FUNCTION:renderMonitorGithubInbox@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctStatus@@*/


monitorBctNodesRefresh?.addEventListener("click", () => {
  void refreshMonitorBctWindowNodes();
});

void refreshMonitorBctStatus();
void refreshMonitorBctWindowNodes();

/*@@MONITOR_FUNCTION:refreshMonitorEndpointRegistry@@*/

if (monitorActRestart) monitorActRestart.addEventListener("click", async () => {
  if (monitorActRestart.disabled) return;
  monitorActRestart.disabled = true;
  setMonitorStatus("ACT 작업 상태 확인 후 재시작 요청 중…", true, 4000);
  try {
    const response = await actFetch("act:/admin/restart", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent: "RESTART_ACT" }),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || !result?.ok) {
      const counts = Number.isInteger(result?.active_tasks) || Number.isInteger(result?.pending_tasks)
        ? ` · 활성 ${result?.active_tasks || 0}, 대기 ${result?.pending_tasks || 0}` : "";
      throw new Error(String(result?.error || `HTTP ${response.status}`) + counts);
    }
    setMonitorStatus("ACT 재시작 요청 완료 · 잠시 후 상태를 다시 확인합니다", true, 5000);
  } catch (error) {
    setMonitorStatus("ACT 재시작 보류 · " + (error?.message || String(error)), false);
    monitorActRestart.disabled = false;
  }
});
if (monitorExtensionReload) monitorExtensionReload.addEventListener("click", () => {
  if (monitorExtensionReload.disabled) return;
  monitorExtensionReload.disabled = true;
  setMonitorStatus("확장을 다시 로드하고 Monitor 창을 복구합니다…", true, 2500);
  try {
    chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {});
  } catch (error) {
    monitorExtensionReload.disabled = false;
    setMonitorStatus("확장 리로드 실패 · " + (error?.message || String(error)), false);
  }
});

/*@@MONITOR_FUNCTION:monitorExactSelectedChatNode@@*/

/*@@MONITOR_FUNCTION:runMonitorUtilityAction@@*/

monitorRccReload?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorRccReload, "RCC의 정확한 현재 인스턴스를 확인 중…", async () => {
    if (!Array.isArray(monitorBctWindowNodesCache)) await refreshMonitorBctWindowNodes();
    const instances = [...new Set((monitorBctWindowNodesCache || [])
      .filter((node) => !node.displayStale && node.instanceState === "OPEN")
      .map((node) => String(node.instanceId || "").trim()).filter(Boolean))];
    if (instances.length !== 1) throw new Error(`RCC_RELOAD_EXACT_INSTANCE_REQUIRED:${instances.length}`);
    await monitorBctShell.reloadRcc(instances[0]);
    setMonitorStatus("RCC 리로드 영수증을 확인했습니다. 연결 복구를 기다립니다.", true, 5000);
    globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 1400);
    return { ok:true };
  }).catch((error) => setMonitorStatus(`RCC 리로드 실패 · ${error?.message || error}`, false, 6000));
});

monitorBctRecover?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorBctRecover, "BCT Core Supervisor 복구 상태를 확인 중…", async () => {
    const result = await monitorNative({ type:"recoverBctCore" });
    if (!result?.ok || result?.verified !== true) throw new Error(result?.error || "BCT_CORE_RECOVERY_UNVERIFIED");
    await refreshMonitorBctStatus();
    setMonitorStatus(result.alreadyReady ? "BCT Core가 이미 정상입니다." : "BCT Core 시작·복구와 READY를 확인했습니다.", true, 4500);
    return result;
  }).catch((error) => setMonitorStatus(`BCT 시작·복구 실패 · ${error?.message || error}`, false, 6500));
});

monitorMcpTunnelRecover?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorMcpTunnelRecover, "MCP 터널 Supervisor 복구 상태를 확인 중…", async () => {
    const result = await monitorNative({ type:"recoverMcpTunnel" });
    if (!result?.ok || result?.verified !== true) throw new Error(result?.error || "BCT_TUNNEL_RECOVERY_UNVERIFIED");
    setMonitorStatus(result.alreadyReady ? "MCP 터널이 이미 정상입니다." : "MCP 터널 복구와 health/ready를 확인했습니다.", true, 4500);
    return result;
  }).catch((error) => setMonitorStatus(`MCP 터널 복구 실패 · ${error?.message || error}`, false, 6500));
});

monitorBctControlRefresh?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorBctControlRefresh, "선택한 ChatGPT 탭의 BC 도구 연결을 새로 읽는 중…", async () => {
    const node = monitorExactSelectedChatNode();
    if (!node?.conversationKey) throw new Error("BC_REFRESH_SELECT_EXACT_CHAT_NODE_FIRST");
    if (node.generating === true) throw new Error("BC_REFRESH_CHAT_IS_GENERATING");
    const result = await chrome.runtime.sendMessage({
      type:"monitor-refresh-exact-chatgpt-tab",
      tabId:node.tabId,
      windowId:node.windowId,
      conversationKey:node.conversationKey,
    });
    if (!result?.ok || result?.reloaded !== true) throw new Error(result?.error || "BC_REFRESH_UNVERIFIED");
    setMonitorStatus(`${node.nodeLabel || "선택 노드"} ChatGPT 탭을 다시 불러왔습니다. BC 도구가 다시 연결됩니다.`, true, 5000);
    return result;
  }).catch((error) => setMonitorStatus(`BC 도구 새로고침 실패 · ${error?.message || error}`, false, 6500));
});
if (monitorNodeSync) monitorNodeSync.addEventListener("click", async () => {
  if (monitorNodeSync.disabled) return;
  monitorNodeSync.disabled = true;
  setMonitorStatus("노드 동기화 중…", true, 3000);
  try {
    await refreshMonitorEndpointRegistry();

    await refreshAiMonitor();
    await refreshMonitorRoleAdmin();

    const openEndpoints = (Array.isArray(monitorLastAiState?.endpoints) ? monitorLastAiState.endpoints : [])
      .filter((endpoint) => String(endpoint?.presence_state || "").toUpperCase() === "OPEN");
    const conversationCounts = new Map();
    for (const endpoint of openEndpoints) {
      const key = String(endpoint?.conversation_key || "").trim();
      const tabId = String(endpoint?.tab_id ?? "").trim();
      if (!key || !tabId) continue;
      conversationCounts.set(key, (conversationCounts.get(key) || 0) + 1);
    }
    const matched = [...conversationCounts.values()].filter((count) => count === 1).length;
    const ambiguous = [...conversationCounts.values()].filter((count) => count > 1).length;
    setMonitorStatus(
      ambiguous
        ? ("노드 동기화 완료 · " + matched + "개 일치 · " + ambiguous + "개 중복 확인 필요")
        : ("노드 동기화 완료 · " + matched + "개 일치"),
      ambiguous === 0,
      3000
    );
  } catch (error) {
    setMonitorStatus("노드 동기화 실패 · " + (error?.message || String(error)), false, 3500);
  } finally {
    monitorNodeSync.disabled = false;
  }
});

chrome.storage.onChanged.addListener((changes,areaName)=>{
  if(areaName!=="local")return;
  let shouldRender=false;
  if(changes[MONITOR_NODE_BINDINGS_KEY]){
    const nextValues=Array.isArray(changes[MONITOR_NODE_BINDINGS_KEY]?.newValue)?changes[MONITOR_NODE_BINDINGS_KEY].newValue:[];
    const nextSignature=monitorNodeBindingsSignature(nextValues);
    const bindingsActuallyChanged=nextSignature!==monitorPersistedNodeBindingsSignature;
    monitorPersistedNodeBindingsSignature=nextSignature;
    monitorNodeBindings.clear();
    for(const item of nextValues){
      if(!item?.conversation_key)continue;
      const transport=String(item?.transport_instance_id||"").trim(),tabId=String(item?.tab_id??"").trim(),hwnd=String(item?.hwnd||"").trim(),windowId=String(item?.window_id??"").trim();
      if(transport&&tabId)monitorNodeBindings.set(`tab:${transport}:${tabId}`,item);
      if(transport&&windowId)monitorNodeBindings.set(`lineage:${transport}:${windowId}`,item);
      if(/^\d+$/.test(hwnd)&&hwnd!=="0")monitorNodeBindings.set(`hwnd:${hwnd}`,item);
    }
    monitorNodeBindingsReady=true;
    shouldRender=bindingsActuallyChanged;
  }
  if(changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]){
    monitorApprovedChatTransitions.clear();
    for(const item of Array.isArray(changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]?.newValue)?changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY].newValue:[])if(String(item||"").trim())monitorApprovedChatTransitions.add(String(item));
    monitorApprovedChatTransitionsReady=true;
    shouldRender=true;
  }
  if(shouldRender&&monitorLastAiState)renderWorkers(monitorLastAiState);
});

chrome.storage.local.get([MONITOR_NODE_BINDINGS_KEY,MONITOR_APPROVED_CHAT_TRANSITIONS_KEY],(data)=>{

  const storedNodeBindings=Array.isArray(data?.[MONITOR_NODE_BINDINGS_KEY])?data[MONITOR_NODE_BINDINGS_KEY]:[];
  monitorPersistedNodeBindingsSignature=monitorNodeBindingsSignature(storedNodeBindings);
  for(const item of storedNodeBindings){

    if(!item?.conversation_key)continue;

    const transport=String(item?.transport_instance_id||"").trim(),tabId=String(item?.tab_id??"").trim(),hwnd=String(item?.hwnd||"").trim(),windowId=String(item?.window_id??"").trim();

    if(transport&&tabId)monitorNodeBindings.set(`tab:${transport}:${tabId}`,item);

    if(transport&&windowId)monitorNodeBindings.set(`lineage:${transport}:${windowId}`,item);

    if(/^\d+$/.test(hwnd)&&hwnd!=="0")monitorNodeBindings.set(`hwnd:${hwnd}`,item);

  }

  for(const item of Array.isArray(data?.[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY])?data[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]:[])if(String(item||"").trim())monitorApprovedChatTransitions.add(String(item));

  monitorNodeBindingsReady=true;

  monitorApprovedChatTransitionsReady=true;

  if(monitorLastAiState)renderWorkers(monitorLastAiState);

});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_GHOST_CACHE_KEY,MONITOR_GHOST_HIDDEN_KEY],(data)=>{for(const item of Array.isArray(data?.[MONITOR_GHOST_CACHE_KEY])?data[MONITOR_GHOST_CACHE_KEY]:[])if(item?.conversation_key)monitorGhostCache.set(String(item.conversation_key),item);for(const key of Array.isArray(data?.[MONITOR_GHOST_HIDDEN_KEY])?data[MONITOR_GHOST_HIDDEN_KEY]:[])monitorHiddenGhosts.add(String(key));monitorGhostStorageReady=true;});

chrome.storage.local.get([MONITOR_CONTEXT_TITLE_STORAGE_KEY],(data)=>{const raw=data?.[MONITOR_CONTEXT_TITLE_STORAGE_KEY]||{};for(const [key,value] of Object.entries(raw))if(key&&value&&typeof value==="object")monitorContextTitles.set(String(key),value);monitorContextTitlesReady=true;for(const [key,value] of monitorContextTitles){monitorPublishedContextTitleSignatures.set(key,JSON.stringify(value||{}));monitorPublishSharedContextTitle(key,value);}void monitorSyncSharedRuntime();if(monitorLastAiState)renderWorkers(monitorLastAiState);});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_REBOOT_SNAPSHOT_KEY],(data)=>{const raw=data?.[MONITOR_REBOOT_SNAPSHOT_KEY];if(raw&&typeof raw==="object"&&Array.isArray(raw.items))monitorRebootSnapshot=raw;monitorRebootSnapshotReady=true;});

let monitorStateFailureCount = 0;

let monitorStateFailureStartedAt = 0;

const MONITOR_FAILURE_GRACE_MS = 3000;

let monitorActHealthWasDown = false;

/*@@MONITOR_FUNCTION:scheduleMonitorStartupRecovery@@*/

/*@@MONITOR_FUNCTION:refreshActHealth@@*/

/*@@MONITOR_FUNCTION:refreshAiMonitor@@*/

let monitorNativePort = null;

const monitorNativePending = new Map();
let monitorNativeRequestSequence = 0;

let monitorWallpaperNativePort = null;
const monitorWallpaperNativePending = new Map();
let monitorWallpaperNativeRequestSequence = 0;
let monitorWallpaperNativeQueue = Promise.resolve();

const monitorDesktopVisualSource = globalThis.MonitorDesktopVisualSource.create({ request: monitorWallpaperNativeRequest });
const monitorThumbnailLayerPolicy = globalThis.MonitorThumbnailLayerPolicy.create(
  globalThis.MonitorThumbnailLayerPolicy.MODES.BACKGROUND_WINDOWS
);
globalThis.MonitorDesktopThumbnailV2.configure({
  visualSource: monitorDesktopVisualSource,
  readFrame: desktopId => captureDesktopFrame(desktopId, "thumb"),
  afterWindowRender: decorateMonitorThumbnailWindows,
  layerPolicy: monitorThumbnailLayerPolicy,
});

/*@@MONITOR_FUNCTION:monitorCaptureDataUriToObjectUrl@@*/

/*@@MONITOR_FUNCTION:ensureMonitorNativePort@@*/

/*@@MONITOR_FUNCTION:handleMonitorForegroundChangedEvent@@*/

// V2 owns all bottom desktop-thumbnail pixels and HWND DOM. Legacy lifecycle
// events may request refresh/removal; they must never create/modify tile images.
/*@@MONITOR_FUNCTION:removeMonitorV2Window@@*/
/*@@MONITOR_FUNCTION:scheduleMonitorV2WindowRefresh@@*/

/*@@MONITOR_FUNCTION:scheduleMonitorWindowLifecycleEvent@@*/

/*@@MONITOR_FUNCTION:drainMonitorWindowLifecycleEvents@@*/

/*@@MONITOR_FUNCTION:handleMonitorWindowLifecycleEvent@@*/

/*@@MONITOR_FUNCTION:monitorNative@@*/

/*@@MONITOR_FUNCTION:monitorControlNativeRequest@@*/

/*@@MONITOR_FUNCTION:ensureMonitorWallpaperNativePort@@*/

/*@@MONITOR_FUNCTION:monitorWallpaperNativeRequest@@*/

/*@@MONITOR_FUNCTION:monitorNativeLaunchIsolated@@*/

/*@@MONITOR_FUNCTION:monitorControlNativeIsolatedRequest@@*/
