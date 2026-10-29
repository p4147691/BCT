/*@@MONITOR_FUNCTION:monitorAuthoritativeConversationForTask@@*/

/*@@MONITOR_FUNCTION:monitorAuthoritativeAlertDetail@@*/

/*@@MONITOR_FUNCTION:monitorSyncAuthoritativeCompletionAlerts@@*/

/*@@MONITOR_FUNCTION:monitorSyncChatCompletionTransitions@@*/


/*@@MONITOR_FUNCTION:monitorPostWorkPersist@@*/

/*@@MONITOR_FUNCTION:monitorAcknowledgePostWork@@*/

/*@@MONITOR_FUNCTION:monitorAcknowledgePostWorkForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorLiveRoleForConversation@@*/

/*@@MONITOR_FUNCTION:monitorEndpointGenerationIsActive@@*/

/*@@MONITOR_FUNCTION:monitorConversationIsGenerating@@*/

/*@@MONITOR_FUNCTION:monitorOpenEndpointForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorHwndIsGenerating@@*/

/*@@MONITOR_FUNCTION:monitorVisualConversationForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorConversationGroupVisual@@*/

/*@@MONITOR_FUNCTION:applyMonitorConversationGroupVisual@@*/

/*@@MONITOR_FUNCTION:applyPersistentMonitorRoleClass@@*/

let monitorHighlightedHwnd = "";

let monitorBctNodeHighlightedHwnd = "";

const monitorNodePanelSelection = globalThis.MonitorNodePanelSelection.create();

const monitorSelectedHwnds = new Set();

let monitorSharedSelectionRevision = "";

let monitorSharedSelectionSyncBusy = false;

let monitorSharedSelectionWriteSerial = Promise.resolve();

let monitorSharedSelectionWritePending = 0;

/*@@MONITOR_FUNCTION:compareMonitorSharedSelectionRevision@@*/

/*@@MONITOR_FUNCTION:publishMonitorSharedSelection@@*/

/*@@MONITOR_FUNCTION:applyMonitorSharedSelection@@*/

/*@@MONITOR_FUNCTION:syncMonitorSharedSelection@@*/

/*@@MONITOR_FUNCTION:monitorSyncSharedState@@*/

let monitorHoveredHwnd = "";

let monitorHoverPointer = { x: -1, y: -1 };

let monitorHoverRecheckTimer = 0;

/*@@MONITOR_FUNCTION:monitorPreviewAtPointer@@*/

/*@@MONITOR_FUNCTION:recheckMonitorHover@@*/

/*@@MONITOR_FUNCTION:applyMonitorWindowHover@@*/

window.addEventListener("pointermove", (event) => {

  monitorHoverPointer = { x: event.clientX, y: event.clientY };

  const preview = event.target?.closest?.(".monitor-desktop-thumb-window, .monitor-window-preview");

  const row = event.target?.closest?.(".monitor-worker-row[data-hwnd]");

  const key = String(preview?.dataset?.hwnd || row?.dataset?.hwnd || "");

  // Hover is a direct projection of the element currently under the pointer.
  // Clearing on an empty key prevents a previously hovered HWND from surviving
  // after the pointer moves onto unrelated Monitor UI.
  applyMonitorWindowHover(key);

}, true);

window.addEventListener("pointerleave", () => {

  monitorHoverPointer = { x: -1, y: -1 };

  applyMonitorWindowHover("");

}, true);

/*@@MONITOR_FUNCTION:scheduleMonitorHoverRecheck@@*/

/*@@MONITOR_FUNCTION:syncMonitorBctNodeTargetHighlight@@*/

/*@@MONITOR_FUNCTION:monitorBctNodeSelectionKey@@*/

/*@@MONITOR_FUNCTION:applyMonitorBctNodeHighlight@@*/

/*@@MONITOR_FUNCTION:applyMonitorWindowHighlight@@*/

/*@@MONITOR_FUNCTION:monitorEndpointFreshnessState@@*/

/*@@MONITOR_FUNCTION:resolveWorkerConnectionState@@*/

/*@@MONITOR_FUNCTION:resolveWorkerWorkState@@*/

// SVG icon semantics used by the node list and desktop-thumbnail overlay.
// Kept distinct from the legacy text symbol helper above so persisted old
// alert records cannot accidentally control the new visual meaning.
/*@@MONITOR_FUNCTION:monitorWorkIconState@@*/

const MONITOR_ROLE_ORDER = ["SUPERVISOR-A", "SUPERVISOR-B", "RELAY", "SOURCE", "WS2", "WORKER-A", "WORKER-B", "IMPLEMENTER", "MONITOR-IMPLEMENTER"];

/*@@MONITOR_FUNCTION:monitorSortLocationParts@@*/

/*@@MONITOR_FUNCTION:monitorWorkerSortKey@@*/

/*@@MONITOR_FUNCTION:compareMonitorWorkers@@*/

const monitorLastPlacementByConversation = new Map();

const monitorDetachedRestorePending = new Set();

const MONITOR_GHOST_CACHE_KEY = "desktopWindowMonitorGhostCacheV1";

const MONITOR_SHARED_REBOOT_SNAPSHOT_KEY = "__MONITOR_REBOOT_SNAPSHOT__";

const MONITOR_SHARED_CONTEXT_TITLE_PREFIX = "__MONITOR_CONTEXT_TITLE__:";

const MONITOR_REBOOT_SNAPSHOT_KEY = "desktopWindowMonitorRebootSnapshotV1";

const MONITOR_CONTEXT_TITLE_STORAGE_KEY = "desktopWindowMonitorContextTitlesV1";

const MONITOR_CONTEXT_TITLE_REFRESH_MS = 10 * 60 * 1000;

const monitorContextTitles = new Map();

const monitorContextTitleInflight = new Set();

let monitorContextTitlesReady = false;
const monitorPublishedContextTitleSignatures = new Map();
let monitorContextTitlePersistQueued = false;

const MONITOR_GHOST_HIDDEN_KEY = "desktopWindowMonitorGhostHiddenV1";

const MONITOR_GHOST_CACHE_MAX = 80;

const MONITOR_GHOST_TEXT_MAX = 1200;



const monitorHiddenGhosts = new Set();

let monitorGhostStorageReady = false;

const monitorRecoveryPickerState = globalThis.MonitorRecoveryPickerState.create();

const monitorRecoverySnapshotState = globalThis.MonitorRecoverySnapshotState.create({ captured_at_ms:0, items:[] });
const monitorRecoveryInventoryController = globalThis.MonitorRecoveryInventory.create({toEpoch: value => monitorGhostTime(value)});

let monitorRebootSnapshotReady = false;

let monitorRebootRestoreActive = false;

const monitorRebootRestorePendingKeys = new Set();

/*@@MONITOR_FUNCTION:monitorGhostBoundText@@*/

/*@@MONITOR_FUNCTION:monitorGhostTime@@*/

/*@@MONITOR_FUNCTION:monitorGhostWorkerId@@*/

/*@@MONITOR_FUNCTION:monitorGhostTaskForWorker@@*/

/*@@MONITOR_FUNCTION:monitorGhostMeaningfulTitle@@*/

/*@@MONITOR_FUNCTION:monitorContextTitleRecord@@*/

/*@@MONITOR_FUNCTION:monitorTitlesEquivalent@@*/

/*@@MONITOR_FUNCTION:monitorReconcilePendingTitles@@*/

/*@@MONITOR_FUNCTION:monitorContextTitleDisplay@@*/

/*@@MONITOR_FUNCTION:monitorContextTitleDisplayFromRecord@@*/

/*@@MONITOR_FUNCTION:monitorPatchContextTitleRows@@*/

/*@@MONITOR_FUNCTION:monitorPublishSharedRebootSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorCaptureRebootSnapshot@@*/


/*@@MONITOR_FUNCTION:monitorPublishSharedContextTitle@@*/

/*@@MONITOR_FUNCTION:persistMonitorContextTitles@@*/

/*@@MONITOR_FUNCTION:monitorContextTitleInput@@*/

/*@@MONITOR_FUNCTION:monitorContextTitleSignature@@*/

/*@@MONITOR_FUNCTION:refreshMonitorContextTitle@@*/

/*@@MONITOR_FUNCTION:setMonitorManualContextTitle@@*/

/*@@MONITOR_FUNCTION:resetMonitorContextTitleToBrowser@@*/

/*@@MONITOR_FUNCTION:monitorLifecycleTooltip@@*/

/*@@MONITOR_FUNCTION:requestMonitorConversationRename@@*/

/*@@MONITOR_FUNCTION:attachMonitorContextTitleMenu@@*/

/*@@MONITOR_FUNCTION:monitorContextTitlePart@@*/

/*@@MONITOR_FUNCTION:monitorWorkerMeaningfulTitle@@*/

/*@@MONITOR_FUNCTION:monitorWorkerContextTitle@@*/

/*@@MONITOR_FUNCTION:monitorGhostAgeing@@*/

/*@@MONITOR_FUNCTION:monitorGhostArchiveAgeing@@*/
