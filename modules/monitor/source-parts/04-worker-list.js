/*@@MONITOR_FUNCTION:monitorGhostProtected@@*/

let monitorGhostPersistTimer = 0;

/*@@MONITOR_FUNCTION:monitorGhostPersist@@*/

/*@@MONITOR_FUNCTION:monitorClosedConversationRecoveryItems@@*/

/*@@MONITOR_FUNCTION:monitorClosedConversationPreviousLocation@@*/

/*@@MONITOR_FUNCTION:monitorClosedConversationContextTitle@@*/

/*@@MONITOR_FUNCTION:renderMonitorClosedConversationRecoveryPanel@@*/

/*@@MONITOR_FUNCTION:configureMonitorProviderLaunchButton@@*/

/*@@MONITOR_FUNCTION:rememberMonitorWorkerPlacement@@*/

/*@@MONITOR_FUNCTION:syncMonitorPhysicalWorkplaces@@*/

const MONITOR_WORKER_ORDER_KEY = "desktopWindowMonitorWorkerOrderV1";

const monitorWorkerOrderByDesktop = new Map();

let monitorWorkerOrderReady = false;

/*@@MONITOR_FUNCTION:monitorPersistWorkerOrder@@*/

/*@@MONITOR_FUNCTION:monitorSetWorkerOrder@@*/

/*@@MONITOR_FUNCTION:monitorRemoveWorkerOrderKey@@*/

/*@@MONITOR_FUNCTION:monitorMoveWorkerOrderKey@@*/

/*@@MONITOR_FUNCTION:monitorReorderWorkerKey@@*/

/*@@MONITOR_FUNCTION:monitorListDisplaySlots@@*/

/*@@MONITOR_FUNCTION:initializeMonitorWorkerOrderStorage@@*/

let monitorWorkerPointerInteractionActive = false;

let monitorDeferredWorkerRenderState = null;

let monitorWorkerPointerReleaseTimer = 0;

const MONITOR_WORKER_CLICK_SETTLE_MS = 550;
const MONITOR_WORKER_RENDER_MIN_INTERVAL_MS = 120;
let monitorWorkerRenderTimer = 0;
let monitorWorkerRenderPendingState = null;
let monitorWorkerRenderInFlight = false;
let monitorWorkerRenderLastAt = 0;

/*@@MONITOR_FUNCTION:flushDeferredMonitorWorkerRender@@*/

/*@@MONITOR_FUNCTION:settleMonitorWorkerPointerInteraction@@*/

monitorWorkers.addEventListener("pointerdown", (event) => {

  if (event.button !== 0 || !event.target.closest(".monitor-worker-row, .monitor-closed-conversation-row")) return;

  clearTimeout(monitorWorkerPointerReleaseTimer);

  monitorWorkerPointerInteractionActive = true;

}, true);

monitorWorkers.addEventListener("click", (event) => {

  if (!event.target.closest(".monitor-worker-row, .monitor-closed-conversation-row")) return;

  settleMonitorWorkerPointerInteraction();

});

document.addEventListener("pointerup", () => {

  if (monitorWorkerPointerInteractionActive) settleMonitorWorkerPointerInteraction();

}, true);

document.addEventListener("pointercancel", () => {

  if (monitorWorkerPointerInteractionActive) settleMonitorWorkerPointerInteraction(0);

}, true);

/*@@MONITOR_FUNCTION:monitorRenderDiagnosticText@@*/

/*@@MONITOR_FUNCTION:monitorLocalLlmReadyState@@*/

/*@@MONITOR_FUNCTION:monitorLocalLlmIsUsable@@*/

/*@@MONITOR_FUNCTION:monitorLocalLlmSummary@@*/

/*@@MONITOR_FUNCTION:monitorLocalLlmActivityText@@*/

const monitorLocalLlmCommandState = {
  inFlight: false,
  generation: 0,
  pendingEnabled: null,
};

/*@@MONITOR_FUNCTION:monitorUpdateLocalLlmToggleButtons@@*/

/*@@MONITOR_FUNCTION:monitorUpdateLocalLlmToggleButton@@*/

/*@@MONITOR_FUNCTION:monitorAdoptLocalLlmControlPayload@@*/

/*@@MONITOR_FUNCTION:monitorEnsureLocalLlmControlStatus@@*/

/*@@MONITOR_FUNCTION:monitorSetLocalLlmEnabled@@*/

/*@@MONITOR_FUNCTION:renderWorkers@@*/

/*@@MONITOR_FUNCTION:performMonitorWorkerRender@@*/

/*@@MONITOR_FUNCTION:positionMonitorTrashRecoveryMenu@@*/

if (monitorNodeTrash && monitorClosedRecoveryMenu) {

  monitorNodeTrash.style.cursor="pointer";

  monitorNodeTrash.addEventListener("click",(event)=>{if(monitorNodeTrash.classList.contains("monitor-node-trash-drop-target")||monitorNodeTrash.classList.contains("monitor-node-trash-drop-success"))return;event.stopPropagation();monitorClosedConversationPickerOpen=!monitorClosedConversationPickerOpen;monitorClosedRecoveryMenu.hidden=!monitorClosedConversationPickerOpen;if(monitorClosedConversationPickerOpen){positionMonitorTrashRecoveryMenu();monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState||{}));}});

  monitorClosedRecoveryMenu.addEventListener("pointerdown",()=>{clearTimeout(monitorWorkerPointerReleaseTimer);monitorWorkerPointerInteractionActive=true;},true);

  monitorClosedRecoveryMenu.addEventListener("click",()=>settleMonitorWorkerPointerInteraction(),true);

  window.addEventListener("resize",()=>{if(monitorClosedConversationPickerOpen)positionMonitorTrashRecoveryMenu();});

  document.addEventListener("pointerdown",(event)=>{if(!monitorClosedConversationPickerOpen)return;if(event.target.closest?.("#monitorNodeTrash,#monitorClosedRecoveryMenu"))return;monitorClosedConversationPickerOpen=false;monitorClosedRecoveryMenu.hidden=true;},true);

}

initializeMonitorWorkerOrderStorage();

const monitorExtensionReload = document.getElementById("monitorExtensionReload");
const monitorRccReload = document.getElementById("monitorRccReload");
const monitorBctRecover = document.getElementById("monitorBctRecover");
const monitorMcpTunnelRecover = document.getElementById("monitorMcpTunnelRecover");
const monitorBctControlRefresh = document.getElementById("monitorBctControlRefresh");

const monitorActRestart = document.getElementById("monitorActRestart");

const monitorNodeSync = document.getElementById("monitorNodeSync");

const monitorBctNodeSummary = document.getElementById("monitorBctNodeSummary");
const monitorBctNodesRefresh = document.getElementById("monitorBctNodesRefresh");
const monitorBctNodeViewModeControl = document.getElementById("monitorBctNodeViewMode");
const monitorBctRoleUndo = document.getElementById("monitorBctRoleUndo");
const monitorBctRoleRedo = document.getElementById("monitorBctRoleRedo");
const monitorBctRoleUndoStack = [];
const monitorBctRoleRedoStack = [];
let monitorBctRoleHistoryBusy = false;
const MONITOR_BCT_ROLE_HISTORY_LIMIT = 30;
/*@@MONITOR_FUNCTION:updateMonitorBctRoleHistoryUi@@*/
/*@@MONITOR_FUNCTION:recordMonitorBctRoleHistory@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeHistoryState@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeHistoryOrders@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeHistoryMatches@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeHistoryOrdersMatch@@*/
/*@@MONITOR_FUNCTION:applyMonitorBctRoleHistory@@*/
monitorBctRoleUndo?.addEventListener("click", () => void applyMonitorBctRoleHistory("undo"));
monitorBctRoleRedo?.addEventListener("click", () => void applyMonitorBctRoleHistory("redo"));
const monitorBctShell = globalThis.MonitorBctShell?.create?.();
const monitorRccCommandCatalog = globalThis.MonitorRccCommandCatalog?.create?.({
  document,
  shell: monitorBctShell,
});
const monitorWindowHwndContract = globalThis.MonitorWindowHwndContract?.create?.();
const monitorMinimizedNodeBadgeContract = globalThis.MonitorMinimizedNodeBadgeContract;
// Null means BCT not yet observed; [] means BCT observed an empty node list.
let monitorBctWindowNodesCache = null;
// Durable Manager truth includes closed conversations that cannot appear in
// the RCC window list. It is display/conflict evidence only, never authority
// to perform automatic role succession.
let monitorBctManagerStatuses = Object.freeze([]);

/*@@MONITOR_FUNCTION:monitorBctNodeDisplayState@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeObservedKey@@*/
/*@@MONITOR_FUNCTION:loadMonitorBctNodeFirstObservedAt@@*/
/*@@MONITOR_FUNCTION:persistMonitorBctNodeFirstObservedAt@@*/
/*@@MONITOR_FUNCTION:observeMonitorBctNodeFirstSeen@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeObservedAgeText@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeBurdenScore@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeDetail@@*/
/*@@MONITOR_FUNCTION:setMonitorBctNodeViewMode@@*/

if (monitorBctNodeViewModeControl) {
  monitorBctNodeViewModeControl.value = monitorBctNodeDisplayState().viewMode;
  monitorBctNodeViewModeControl.addEventListener("change", () => {
    setMonitorBctNodeViewMode(monitorBctNodeViewModeControl.value);
  });
}
let monitorBctDeferredNodeRender = null;
// Exact-conversation optimistic role projections survive unrelated stale
// status replies while a role write is being persisted.  A projection is
// removed only after Core reports the same state or the bounded hold expires.
const monitorBctRoleSavePendingByKey = new Map();
const MONITOR_BCT_NODE_ORDER_KEY = "desktopWindowMonitorBctNodeOrderV1";
const monitorBctNodeOrderByScope = new Map();
let monitorBctNodeOrderReady = false;
chrome.storage.local.get([MONITOR_BCT_NODE_ORDER_KEY], (data) => {
  const saved = data?.[MONITOR_BCT_NODE_ORDER_KEY] || {};
  for (const [scopeId, keys] of Object.entries(saved)) {
    if (Array.isArray(keys)) monitorBctNodeOrderByScope.set(scopeId, keys.map(String).filter(Boolean));
  }
  monitorBctNodeOrderReady = true;
  if (Array.isArray(monitorBctWindowNodesCache)) renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
});
let monitorBctDraggedNodeKey = "";
let monitorBctDragGhost = null;
let monitorBctPointerDrag = null;
let monitorBctNativePreviewToken = "";
let monitorBctNativePreviewSequence = 0;

/*@@MONITOR_FUNCTION:stopMonitorBctNativePreview@@*/

let monitorBctNodeReorderPending = false;
let monitorBctCurrentSessionWindowHwnd = new Map();
let monitorBctDisplayWindowHwnd = new Map();
let monitorBctBrowserWindows = new Map();
let monitorBctLastDisplayResolution = null;
let monitorBctWindowNodeRefreshBusy = false;
let monitorBctWindowNodeRefreshPending = false;
// A reload can observe cached RCC rows while Chrome/RCC complete their own
// restart. Revalidate only during this bounded warm-up; this is not a poll.
const MONITOR_BCT_STARTUP_REVALIDATION_DELAYS_MS = Object.freeze([250, 800, 1800, 3200]);
let monitorBctStartupRevalidationTimer = 0;
let monitorBctStartupRevalidationAttempts = 0;
let monitorMinimizedBadgeConvergenceTimer = 0;
let monitorBctProjectionGeneration = 0;
let monitorBctProjectionConvergenceTimer = 0;
let monitorBctProjectionConvergenceKey = "";
let monitorBctProjectionConvergenceAttempt = 0;
let monitorBctProjectionConvergenceInflight = false;
let monitorBctThumbnailProjectionAttemptKeys = new Set();
// This is an event-bound, finite reconciliation after Chrome changes routes or
// windows.  It is not an ambient polling loop: the final two reads cover the
// delayed Native virtual-desktop/Chrome HWND snapshot that otherwise leaves a
// just-restored Dot node at D? until a user click creates another lifecycle
// event.
const MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS = Object.freeze([0, 450, 1400, 3500, 8000]);

/*@@MONITOR_FUNCTION:scheduleMonitorMinimizedBadgeConvergence@@*/
if (monitorWorkers) monitorWorkers.dataset.columns = "3";

/*@@MONITOR_FUNCTION:resetMonitorBctProjectionConvergence@@*/

/*@@MONITOR_FUNCTION:refreshMonitorBctThumbnailProjectionForDesktop@@*/

/*@@MONITOR_FUNCTION:monitorBctProjectionHasUnresolvedLineage@@*/

/*@@MONITOR_FUNCTION:scheduleMonitorBctProjectionConvergence@@*/

/*@@MONITOR_FUNCTION:monitorBctRenameErrorText@@*/
let monitorBctRenameEditor = null;

/*@@MONITOR_FUNCTION:closeMonitorBctRenameEditor@@*/

/*@@MONITOR_FUNCTION:openMonitorTrashRecovery@@*/

/*@@MONITOR_FUNCTION:monitorBctRoleTagsFromText@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeRoleSummary@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeRoleRank@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeLocationText@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeSurfaceText@@*/
/*@@MONITOR_FUNCTION:monitorBctNodeBurden@@*/
