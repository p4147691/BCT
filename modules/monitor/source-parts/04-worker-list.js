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

  monitorNodeTrash.addEventListener("click",(event)=>{if(monitorNodeTrash.classList.contains("monitor-node-trash-drop-target")||monitorNodeTrash.classList.contains("monitor-node-trash-drop-success"))return;event.stopPropagation();monitorClosedConversationPickerOpen=!monitorClosedConversationPickerOpen;monitorClosedRecoveryMenu.hidden=!monitorClosedConversationPickerOpen;if(monitorClosedConversationPickerOpen){positionMonitorTrashRecoveryMenu();if(monitorLastAiState)monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));}});

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
const monitorBctShell = globalThis.MonitorBctShell?.create?.();
const monitorWindowHwndContract = globalThis.MonitorWindowHwndContract?.create?.();
const monitorMinimizedNodeBadgeContract = globalThis.MonitorMinimizedNodeBadgeContract;
// Null means BCT not yet observed; [] means BCT observed an empty node list.
let monitorBctWindowNodesCache = null;
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
let monitorBctWindowNodeRefreshBusy = false;
let monitorBctWindowNodeRefreshPending = false;
let monitorMinimizedBadgeConvergenceTimer = 0;
let monitorBctProjectionGeneration = 0;
let monitorBctProjectionConvergenceTimer = 0;
let monitorBctProjectionConvergenceKey = "";
let monitorBctProjectionConvergenceAttempt = 0;
let monitorBctProjectionConvergenceInflight = false;
let monitorBctThumbnailProjectionAttemptKeys = new Set();
const MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS = Object.freeze([0, 450, 1400]);

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

/*@@MONITOR_FUNCTION:monitorBctNodeLocationText@@*/
