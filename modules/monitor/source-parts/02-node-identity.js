/*@@MONITOR_FUNCTION:monitorLocationForEndpoint@@*/

/*@@MONITOR_FUNCTION:monitorExactConversationWindow@@*/

// Physical placement never allocates or infers official node numbers; ACT owns numbering.
// Legacy Dn-x labels are read only.  New ACT labels are global Nx identities;
// the current Dn position is derived independently from the desktop id.
/*@@MONITOR_FUNCTION:monitorNodeIdentityParts@@*/

/*@@MONITOR_FUNCTION:monitorPhysicalWindowPeerLocation@@*/

/*@@MONITOR_FUNCTION:monitorCanonicalPhysicalLocation@@*/

/*@@MONITOR_FUNCTION:monitorEndpointLocation@@*/

/*@@MONITOR_FUNCTION:resolveStableMonitorLocation@@*/

// Node numbering is ACT-authoritative. Monitor only projects ACT-assigned labels.

/*@@MONITOR_FUNCTION:monitorActBrowserNode@@*/

/*@@MONITOR_FUNCTION:monitorStableBrowserNodeKey@@*/

/*@@MONITOR_FUNCTION:monitorStableNodeSlotRecord@@*/

/*@@MONITOR_FUNCTION:monitorStableNodeSlot@@*/

/*@@MONITOR_FUNCTION:monitorBrowserDisplaySlots@@*/

/*@@MONITOR_FUNCTION:monitorWindowGroupKeyForWorker@@*/

/*@@MONITOR_FUNCTION:monitorGroupChatgptMembersForDisplay@@*/

// The desktop-label summary is reserved for minimized ChatGPT windows. Open
// ChatGPT windows render their BCT/RCC number directly on their thumbnail.
/*@@MONITOR_FUNCTION:monitorMinimizedNodeSlotsByDesktop@@*/

/*@@MONITOR_FUNCTION:monitorMinimizedNodeTokensByDesktop@@*/

/*@@MONITOR_FUNCTION:profileForMonitorWorker@@*/

/*@@MONITOR_FUNCTION:endpointForMonitorWorker@@*/

/*@@MONITOR_FUNCTION:monitorEndpointWindowKey@@*/

/*@@MONITOR_FUNCTION:monitorEndpointNativeChatExpired@@*/

/*@@MONITOR_FUNCTION:monitorEndpointIsMinimized@@*/

/*@@MONITOR_FUNCTION:monitorWorkersForState@@*/

// ACT state payloads are immutable snapshots in this UI. Rendering used to rebuild
// the same projection for every storage/identity callback, multiplying callback bursts.
const monitorConversationProjectionController = globalThis.MonitorConversationProjectionController.create({build: state => monitorWorkersForState(state)});

/*@@MONITOR_FUNCTION:monitorWorkersProjectionForState@@*/

/*@@MONITOR_FUNCTION:endpointRegistryIsAuthoritative@@*/

/*@@MONITOR_FUNCTION:endpointOsWindowHandle@@*/

/*@@MONITOR_FUNCTION:monitorTrustedPhysicalWindowKey@@*/

/*@@MONITOR_FUNCTION:monitorResolvedWorkerHwnd@@*/

const MONITOR_PERSISTENT_ROLE_CLASSES = {

  ORCHESTRATOR: "monitor-role-orchestrator",

  COORDINATOR_1: "monitor-role-coordinator-1",

  COORDINATOR_2: "monitor-role-coordinator-2",

};

const monitorRoleByHwnd = new Map();

const MONITOR_SYSTEM_NODE_STORAGE_KEY = "desktopWindowMonitorSystemNodesV1";

const monitorSystemNodeKeys = new Set((()=>{ try { const v=JSON.parse(localStorage.getItem(MONITOR_SYSTEM_NODE_STORAGE_KEY)||"[]"); return Array.isArray(v)?v:[]; } catch (_) { return []; } })());

/*@@MONITOR_FUNCTION:monitorPersistSystemNodes@@*/

/*@@MONITOR_FUNCTION:monitorMarkSystemNode@@*/

const monitorDirectGenerationByConversation = new Map();

const monitorDirectGenerationByTab = new Map();

const MONITOR_DIRECT_GENERATION_TTL_MS = 3500;
const monitorNodeGenerationAPI = globalThis.MonitorNodeGenerationState.create({
  readTab: key => monitorDirectGenerationByTab.get(key),
  readConversation: key => monitorDirectGenerationByConversation.get(key),
  readTabEntries: () => monitorDirectGenerationByTab.values(),
  openEndpointForHwnd: (hwnd,state) => monitorOpenEndpointForHwnd(hwnd,state),
  ttlMs: MONITOR_DIRECT_GENERATION_TTL_MS,
});

/*@@MONITOR_FUNCTION:monitorDirectConversationGenerationState@@*/

/*@@MONITOR_FUNCTION:monitorDirectEndpointUserAttention@@*/

/*@@MONITOR_FUNCTION:monitorUserAttentionVisualDetail@@*/

/*@@MONITOR_FUNCTION:monitorConversationUserAttentionDetail@@*/

/*@@MONITOR_FUNCTION:monitorHwndUserAttentionDetail@@*/

const MONITOR_SHARED_USER_ATTENTION_PREFIX="__DWUA1__:";
/*@@MONITOR_FUNCTION:monitorEncodeSharedUserAttention@@*/
/*@@MONITOR_FUNCTION:monitorDecodeSharedGenerationAttention@@*/

const MONITOR_COMPLETION_STABLE_MS = 1800;

const monitorCompletionAlertTimers = new Map();

/*@@MONITOR_FUNCTION:monitorCancelScheduledCompletionAlert@@*/

/*@@MONITOR_FUNCTION:monitorScheduleChatCompletionAlert@@*/

/*@@MONITOR_FUNCTION:monitorApplyDirectUserClick@@*/

let monitorChatNavigationRefreshTimer = 0;
const monitorChatNavigationPendingByTab = new Map();

/*@@MONITOR_FUNCTION:monitorBrowserWindowIdForEndpoint@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctCurrentSessionWindowHwnd@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctBrowserWindowGeometry@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctDisplayWindowHwnd@@*/

/*@@MONITOR_FUNCTION:monitorBctCurrentSessionHwnd@@*/

/*@@MONITOR_FUNCTION:monitorBctDisplaySessionHwnd@@*/

/*@@MONITOR_FUNCTION:monitorHwndForBrowserWindowId@@*/

/*@@MONITOR_FUNCTION:monitorDisplayHwndForBrowserWindowId@@*/

/*@@MONITOR_FUNCTION:applyMonitorChatNavigationIdentity@@*/

const monitorBrowserVisualPendingWindowIds = new Set();
const monitorBrowserVisualTabsByWindow = new Map();
let monitorBrowserVisualRefreshTimer = 0;
let monitorBrowserVisualRefreshInFlight = false;
let monitorBrowserRosterRefreshPending = false;
const MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS = 120;

/*@@MONITOR_FUNCTION:applyMonitorBrowserVisualTabSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorBrowserVisualTabsForWindow@@*/

/*@@MONITOR_FUNCTION:scheduleMonitorBrowserVisualRefresh@@*/

/*@@MONITOR_FUNCTION:flushMonitorBrowserVisualRefresh@@*/

const monitorPopupTopologyPendingDesktopIds = new Set();
let monitorPopupTopologyRefreshTimer = 0;
let monitorPopupTopologyRefreshInFlight = false;
const MONITOR_POPUP_TOPOLOGY_REFRESH_DEBOUNCE_MS = 360;

/*@@MONITOR_FUNCTION:scheduleMonitorPopupTopologyRefresh@@*/

/*@@MONITOR_FUNCTION:flushMonitorPopupTopologyRefresh@@*/

/*@@MONITOR_FUNCTION:scheduleMonitorChatNavigationRefresh@@*/

chrome.runtime.onMessage.addListener((message, sender) => {

  if (message?.type === "desktop-window-user-click") { monitorApplyDirectUserClick(message, sender); return; }
  if (message?.type === "monitor-popup-topology-changed") {
    if (!monitorDesktopIdentityState.snapshot().hostDesktopId || monitorDesktopIdentityState.snapshot().hostDesktopId !== monitorDesktopIdentityState.snapshot().currentDesktopId) return;
    const desktopIds = [...new Set((Array.isArray(message?.desktopIds) ? message.desktopIds : []).map((value) => String(value || "").trim()).filter(Boolean))];
    if (!desktopIds.length) return;
    scheduleMonitorPopupTopologyRefresh(desktopIds);
    return;
  }

  if (message?.type === "monitor-browser-visual-changed") {
    scheduleMonitorBrowserVisualRefresh(message);
    return;
  }

  if (message?.type === "monitor-chat-navigation-changed") {
    scheduleMonitorChatNavigationRefresh(message);
    return;
  }

  if (message?.type !== "desktop-window-generation-telemetry") return;

  const key=String(message?.conversationKey||"").trim(); if(!key)return;

  if(message?.systemNode===true) monitorMarkSystemNode(key);

  const wasGenerating=monitorDirectConversationGenerationState(key)===true;

  const previous=monitorDirectGenerationByConversation.get(key);

  const messageAttentionKind=String(message?.userAttention?.kind||"").trim().toUpperCase();
  const messageUserAttention=["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(messageAttentionKind)?{kind:messageAttentionKind,label:String(message?.userAttention?.label||"사용자 조치 필요")}:null;
  const next={conversationKey:key,generating:message?.generating===true,attentionCue:String(message?.attentionCue||""),completionCue:String(message?.completionCue||"general"),userAttention:messageUserAttention,at:Number(message?.at)||Date.now()};

  const senderTabId=String(message?.sourceTabId ?? sender?.tab?.id ?? "").trim();

  if(senderTabId)monitorDirectGenerationByTab.set(`${key}:${senderTabId}`,next);

  if(monitorObservedState.snapshot()){

    const endpoints=Array.isArray(monitorObservedState.snapshot()?.endpoints)?monitorObservedState.snapshot().endpoints:[];
    const exactEndpoint=senderTabId?endpoints.find((item)=>String(item?.conversation_key||"").trim()===key && String(item?.tab_id??"").trim()===senderTabId):null;
    const conversationEndpoints=endpoints.filter((item)=>String(item?.conversation_key||"").trim()===key && String(item?.presence_state||"").toUpperCase()==="OPEN");
    const endpoint=exactEndpoint || (conversationEndpoints.length===1?conversationEndpoints[0]:null);

    if(endpoint){ const endpointTabId=String(endpoint?.tab_id??"").trim(); if(endpointTabId)monitorDirectGenerationByTab.set(`${key}:${endpointTabId}`,next); endpoint.last_seen_at=new Date(next.at).toISOString(); endpoint.presence_state="OPEN"; }

  }

  monitorDirectGenerationByConversation.set(key,next);
  if(next.generating===true){
    const expectedGenerationState=next;
    setTimeout(()=>{
      if(monitorDirectGenerationByConversation.get(key)!==expectedGenerationState)return;
      if(monitorDirectConversationGenerationState(key)!==null)return;
      void refreshMonitorConversationStateFast(true);
    },MONITOR_DIRECT_GENERATION_TTL_MS+100);
  }

  const sharedGenerationKey=senderTabId?`${key}::TAB:${senderTabId}`:key;

  void monitorPublishSharedRuntime("generation",sharedGenerationKey,{generating:next.generating,attentionCue:monitorEncodeSharedUserAttention(next.attentionCue,next.userAttention),completionCue:next.completionCue,userAttention:next.userAttention},next.at);

  const isGenerating=monitorDirectConversationGenerationState(key)===true;

  if (isGenerating) { monitorCancelScheduledCompletionAlert(key); monitorGenerationSeen.set(key,true); monitorWorkedConversationKeys.add(key); monitorPostWorkAlerts.delete(key); monitorChatAlertDetails.delete(key); monitorAcknowledgedPostWork.delete(key); monitorPostWorkPersist(); }

  if ((wasGenerating || previous?.generating===true || monitorGenerationSeen.get(key)===true) && !isGenerating) monitorScheduleChatCompletionAlert(key,next.attentionCue,next.completionCue);

  if (!previous || previous.generating!==next.generating || previous.attentionCue!==next.attentionCue || previous.completionCue!==next.completionCue || String(previous?.userAttention?.kind||"")!==String(next.userAttention?.kind||"") || String(previous?.userAttention?.label||"")!==String(next.userAttention?.label||"")) {

    for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) applyPersistentMonitorRoleClass(preview, preview.dataset.hwnd||"");

    if (monitorObservedState.snapshot()) renderWorkers(monitorObservedState.snapshot());

  }

});

const monitorWorkingByHwnd = new Set();

const monitorPausedByHwnd = new Set();

const monitorWorkedConversationKeys = new Set();

const monitorAcknowledgedPostWork = new Set();

const monitorPostWorkAlerts = new Set();

const monitorChatAlertDetails = new Map();

const monitorGenerationSeen = new Map();

const monitorAcknowledgedReportIds = new Set();

const monitorAuthoritativeReportByConversation = new Map();

let monitorPendingDurableReports = [];

const MONITOR_POST_WORK_STORAGE_KEY = "desktopWindowMonitorPostWorkV2";

let monitorPostWorkLastObservedAt = Date.now();

let monitorPostWorkStorageReady = false;

let monitorPostWorkPersistTimer = 0;

let monitorSharedRuntimeSyncBusy = false;

const MONITOR_SHARED_INSTANCE_PREFIX = "__MONITOR_INSTANCE__:";

const MONITOR_RUNTIME_BUILD_ID = "alert-sync-20260922-0450";

let monitorSharedRuntimeReady = false;

let monitorSharedRuntimeInitialReconciled = false;

const monitorSharedRuntimeAlertAt = new Map();

const monitorSharedRuntimeAckAt = new Map();

const MONITOR_EPHEMERAL_GENERATION_TTL_MS = 30 * 60 * 1000;

/*@@MONITOR_FUNCTION:pruneMonitorEphemeralGenerationState@@*/

/*@@MONITOR_FUNCTION:monitorPublishSharedRuntime@@*/

/*@@MONITOR_FUNCTION:monitorPublishSharedInstance@@*/

/*@@MONITOR_FUNCTION:monitorSyncSharedRuntime@@*/

/*@@MONITOR_FUNCTION:monitorPersistentRoleClass@@*/

/*@@MONITOR_FUNCTION:monitorIsActivelyWorking@@*/

/*@@MONITOR_FUNCTION:monitorIsPostWorkWaiting@@*/

/*@@MONITOR_FUNCTION:monitorCreateChatCompletionAlert@@*/

/*@@MONITOR_FUNCTION:monitorChatAlertDetail@@*/

/*@@MONITOR_FUNCTION:monitorReportMatchesTask@@*/
