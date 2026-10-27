/*@@MONITOR_FUNCTION:syncMonitorDesktopScrollArrows@@*/

monitorDesktopScrollLeft.addEventListener("click",()=>monitorDesktopScrollViewport.scrollBy({left:-monitorDesktopScrollStep(),behavior:"smooth"}));

monitorDesktopScrollRight.addEventListener("click",()=>monitorDesktopScrollViewport.scrollBy({left:monitorDesktopScrollStep(),behavior:"smooth"}));

monitorDesktopScrollViewport.addEventListener("scroll",syncMonitorDesktopScrollArrows,{passive:true});

window.addEventListener("resize",()=>requestAnimationFrame(syncMonitorDesktopScrollArrows));

const monitorCreateDesktop = document.getElementById("monitorCreateDesktop");

const monitorNodeTrash = document.getElementById("monitorNodeTrash");

const monitorNodeTrashUndo = document.getElementById("monitorNodeTrashUndo");

const monitorNodeTrashUndoButton = document.getElementById("monitorNodeTrashUndoButton");

const monitorNodeTrashUndoCountdown = document.getElementById("monitorNodeTrashUndoCountdown");

if (monitorClosedRecoveryMenu && monitorClosedRecoveryMenu.parentElement !== document.body) document.body.append(monitorClosedRecoveryMenu);

const monitorDesktopUndo = document.getElementById("monitorDesktopUndo");

const monitorDesktopUndoButton = document.getElementById("monitorDesktopUndoButton");

const monitorDesktopUndoCountdown = document.getElementById("monitorDesktopUndoCountdown");

const monitorUndoStack = [];

let monitorUndoTimer = 0;

let monitorUndoSessionExpiresAt = 0;

const MONITOR_UNDO_MAX = 8;

const MONITOR_UNDO_TTL_MS = 10000;

const MONITOR_TRASHED_NODES_KEY = "desktopWindowMonitorTrashedNodesV1";

const MONITOR_TRASH_RECORDS_KEY = "desktopWindowMonitorTrashRecordsV1";

const MONITOR_TRASHED_NOTES_KEY = "desktopWindowMonitorTrashedNotesV1";

const MONITOR_TRASHED_DESKTOPS_KEY = "desktopWindowMonitorTrashedDesktopsV1";

const MONITOR_NODE_TRASH_UNDO_MS = 5000;

const monitorTrashedConversationKeys = new Set();

const monitorTrashRecords = new Map();

const monitorTrashedNotes = new Map();

const monitorTrashedDesktops = new Map();

let monitorNodeTrashUndoSnapshot = null;

let monitorNodeTrashUndoExpiresAt = 0;

let monitorNodeTrashUndoTimer = 0;

const MONITOR_DESKTOP_TRASH_UNDO_MS = 0;

let monitorDeletedDesktopUndo = null;

let monitorDeletedDesktopUndoExpiresAt = 0;

let monitorDeletedDesktopUndoTimer = 0;

let monitorLocalHostWindowTitle = "";

let monitorDesktopState = { count: 1, currentIndex: 0, selectedIndex: null, currentDesktopId: null, hostDesktopId: null, hostWindowHwnd: null, observedDesktopId: null, desktopIds: [] };

// Per-desktop presentation policy is local Monitor state. It never changes ACT
// organization, role or task ownership, and uses the immutable desktop id.
const MONITOR_DESKTOP_MANAGEMENT_MODE_KEY = "desktopWindowMonitorDesktopManagementModesV1";
const MONITOR_DESKTOP_MANAGEMENT_MODES = new Set(["MANAGED", "OBSERVE_ONLY", "PROTECTED"]);
let monitorDesktopManagementModes = {};

/*@@MONITOR_FUNCTION:monitorDesktopManagementMode@@*/

/*@@MONITOR_FUNCTION:monitorDesktopManagementModeText@@*/

/*@@MONITOR_FUNCTION:monitorDesktopManagementNextMode@@*/

/*@@MONITOR_FUNCTION:monitorSetDesktopManagementMode@@*/

/*@@MONITOR_FUNCTION:monitorAttachDesktopManagementControl@@*/

chrome.storage.local.get([MONITOR_DESKTOP_MANAGEMENT_MODE_KEY], (data) => {
  const raw = data?.[MONITOR_DESKTOP_MANAGEMENT_MODE_KEY];
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const normalized = {};
    for (const [desktopId, mode] of Object.entries(raw)) {
      const id = String(desktopId || "").trim();
      const value = String(mode || "").toUpperCase();
      if (id && MONITOR_DESKTOP_MANAGEMENT_MODES.has(value)) normalized[id] = value;
    }
    monitorDesktopManagementModes = normalized;
  }
  if (monitorDesktopState.desktopIds.length) syncDesktopSwitcher();
});

let monitorRefreshBusy = false;

let monitorRefreshQueued = false;

const MONITOR_LLM_CACHE_STORAGE_KEY = "desktopWindowMonitorLlmNodesCacheV1";

let monitorCachedLlmNodes = [];

let monitorConsecutiveEmptyLlmResponses = 0;

const MONITOR_STARTUP_SETTLE_MS = 700;

let monitorStartupRecoveryTimer = null;

let monitorStartupRecoveryUsed = false;

let monitorStartupStateConfirmed = false;

let monitorStartupSharedRuntimeConfirmed = false;

let monitorStartupEndpointFreshConfirmed = false;

let monitorInitialThumbBatchDone = false;
let monitorInitialWindowBatchDone = false;
let monitorInitialThumbStage = "not-started";
let monitorInitialThumbError = "";
/*@@MONITOR_FUNCTION:refreshInitialBackgroundThumbs@@*/
let monitorInitialSemanticThumbSyncDone = false;
let monitorInitialSemanticThumbSyncInflight = false;
let monitorInitialSemanticThumbSyncTimer = 0;

let monitorSharedSelectedDesktopId = "";

let monitorSharedSelectionReady = false;

/*@@MONITOR_FUNCTION:monitorApplySharedDesktopSelection@@*/

let monitorStatusHoldUntil = 0;

/*@@MONITOR_FUNCTION:setMonitorStatus@@*/

const MONITOR_ROLE_ADMIN_ROLES = ["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"];

const monitorRoleAdminInFlight = new Set();

const monitorRoleAdminSelection = new Map();

const monitorRoleMutationInFlight = new Set();

let monitorRoleAssignMode = "";

let monitorRoleAdminState = null;

let monitorRoleAdminSignature = "";

let monitorRoleAdminBusy = false;

/*@@MONITOR_FUNCTION:monitorRoleAdminCandidates@@*/

/*@@MONITOR_FUNCTION:monitorRoleAdminPath@@*/

/*@@MONITOR_FUNCTION:monitorRoleAdminPayload@@*/

/*@@MONITOR_FUNCTION:monitorRoleAdminErrorText@@*/

/*@@MONITOR_FUNCTION:monitorSelectedRoleWorker@@*/

/*@@MONITOR_FUNCTION:monitorSetRoleAssignMode@@*/

/*@@MONITOR_FUNCTION:monitorExactOpenEndpoint@@*/

/*@@MONITOR_FUNCTION:monitorBootstrapExempt@@*/

/*@@MONITOR_FUNCTION:monitorApplyRoleMode@@*/

/*@@MONITOR_FUNCTION:monitorTurnWorkerOff@@*/

/*@@MONITOR_FUNCTION:monitorRoleAdminShort@@*/

/*@@MONITOR_FUNCTION:setMonitorRoleAdminStatus@@*/

/*@@MONITOR_FUNCTION:renderMonitorRoleAdmin@@*/

/*@@MONITOR_FUNCTION:refreshMonitorRoleAdmin@@*/

/*@@MONITOR_FUNCTION:runMonitorRoleAdminAction@@*/

const MONITOR_AGENT_GROUPS = [

  { key: "chatgpt", label: "ChatGPT" },

  { key: "external-llm", label: "External LLM" },

  { key: "local-llm", label: "Local LLM" },

];

/*@@MONITOR_FUNCTION:isMonitorVisibleWorker@@*/

/*@@MONITOR_FUNCTION:classifyMonitorWorker@@*/

/*@@MONITOR_FUNCTION:monitorWorkerReadyForUse@@*/

/*@@MONITOR_FUNCTION:monitorIsExplicitCodexResource@@*/

/*@@MONITOR_FUNCTION:monitorCodexResourceProfile@@*/

/*@@MONITOR_FUNCTION:monitorIsActionableCodexResource@@*/

/*@@MONITOR_FUNCTION:activateMonitorCodexResource@@*/

/*@@MONITOR_FUNCTION:monitorLlmWorkersFromState@@*/

/*@@MONITOR_FUNCTION:monitorLocalModelIsLoaded@@*/

/*@@MONITOR_FUNCTION:monitorLocalOllamaModels@@*/

/*@@MONITOR_FUNCTION:monitorLlmRuntimePresentation@@*/

/*@@MONITOR_FUNCTION:monitorCodexWorkersFromState@@*/

/*@@MONITOR_FUNCTION:cleanMonitorWorkerName@@*/

/*@@MONITOR_FUNCTION:stationForMonitorWorker@@*/

/*@@MONITOR_FUNCTION:monitorStationMetadata@@*/

const monitorWindowDesktopLocations = new Map();

const monitorNonChatStartedByHwnd = new Map();

const MONITOR_NODE_BINDINGS_KEY = "desktopWindowMonitorNodeBindingsV1";

const MONITOR_APPROVED_CHAT_TRANSITIONS_KEY = "desktopWindowMonitorApprovedChatTransitionsV1";

const monitorNodeBindings = new Map();

const monitorApprovedChatTransitions = new Set();

let monitorNodeBindingsReady = false;

let monitorApprovedChatTransitionsReady = false;

let monitorPersistedNodeBindingsSignature = "";

/*@@MONITOR_FUNCTION:monitorCanonicalJsonValue@@*/

/*@@MONITOR_FUNCTION:monitorCanonicalNodeBindings@@*/

/*@@MONITOR_FUNCTION:monitorNodeBindingsSignature@@*/

/*@@MONITOR_FUNCTION:monitorPersistNodeBindings@@*/

/*@@MONITOR_FUNCTION:monitorChatTransitionKey@@*/

/*@@MONITOR_FUNCTION:monitorChatTransitionIsApproved@@*/

/*@@MONITOR_FUNCTION:monitorRememberApprovedChatTransition@@*/

/*@@MONITOR_FUNCTION:monitorBrowserLineageKey@@*/

/*@@MONITOR_FUNCTION:monitorTabBindingKey@@*/

/*@@MONITOR_FUNCTION:monitorStableNodeForWindow@@*/

/*@@MONITOR_FUNCTION:monitorStableNodeForEndpoint@@*/

/*@@MONITOR_FUNCTION:monitorStoreNodeBinding@@*/

/*@@MONITOR_FUNCTION:monitorNodeChatChangeState@@*/

// Keep a short-lived last-known-good node location so transient F5/navigation/window

// churn does not immediately relabel a known node as UNMAPPED.

const monitorLastKnownNodeLocations = new Map();

const MONITOR_WINDOW_LOCATION_TTL_MS = 15000;

const MONITOR_NODE_CHECKING_TTL_MS = 12000;

const MONITOR_WINDOW_IDENTITY_TTL_MS = 2000;

const MONITOR_NON_CHAT_GRACE_MS = 30000;

const monitorWindowIdentityInflight = new Set();

const MONITOR_IDENTITY_INDEX_REFRESH_MS = 1800;

let monitorIdentityIndexRefreshAt = 0;

let monitorIdentityIndexInflight = null;

/*@@MONITOR_FUNCTION:normalizeMonitorWindowTitle@@*/

let monitorLastAiState = null;

const MONITOR_AI_STATE_CACHE_KEY = "desktopWindowMonitorAiStateCacheV1";

const MONITOR_AI_STATE_CACHE_TTL_MS = 600000;

let monitorStructureOpen = false;

const MONITOR_STRUCTURE_LINK_KEY = "desktopWindowMonitorStructureLinksV1";

const MONITOR_STRUCTURE_NODE_CONTROL_KEY = "desktopWindowMonitorStructureNodeControlsV1";

let monitorStructureSocketDraft = { orchestrator:null, aux1:null, aux2:null, managers:{} };

let monitorStructureLinkOverrides = {};

// Draft-only participation state.  This is intentionally separate from the
// live ACT/list exemption state until placement is confirmed.
let monitorStructurePlacementExemptions = {};

/*@@MONITOR_FUNCTION:monitorStructureNodeIsPlacementExempt@@*/

let monitorStructureNodeControls = {};

let monitorStructureResourceEdges = [];

let monitorStructureAiNodes = [];

let monitorStructureWorkspaces = [];

let monitorStructureExecutorMetrics = null;

let monitorStructureOrganizationGeneration = null;

let monitorStructureResourceDragId = "";

let monitorStructureDirty = false;
const MONITOR_STRUCTURE_HISTORY_LIMIT = 40;
const monitorStructureUndoStack = [];
const monitorStructureRedoStack = [];

let monitorStructureRelationDragKey = "";

const MONITOR_STRUCTURE_BASELINE_KEY = "desktopWindowMonitorStructureBaselineV2";
const MONITOR_STRUCTURE_WORKING_DRAFT_KEY = "desktopWindowMonitorStructureWorkingDraftV1";
const MONITOR_STRUCTURE_LEGACY_DRAFT_KEY = "desktopWindowMonitorStructureTempDraftV1";
let monitorStructureBaseline = null;
let monitorStructureAuthorityLoaded = false;

let monitorStructureDeskMembership = {};

let monitorStructureBundleDesk = {};
let monitorStructureManagerBundleDesk = {};
let monitorStructureLinkMode=false;
let monitorStructureLinkSourceKey="";
const MONITOR_STRUCTURE_CONNECTIONS_ENABLED=true;

let monitorStructureEdgePointer = { child:"", pointerId:null, startX:0, startY:0, moved:false };

let monitorStructureNodePointer = { nodeKey:"", pointerId:null, startX:0, startY:0, moved:false };

let monitorStructureSuppressNodeClickUntil = 0;
let monitorStructurePointerGhost = null;

let monitorStructureActiveScopeKey = "GLOBAL";

/*@@MONITOR_FUNCTION:rememberMonitorDesktopWindows@@*/

/*@@MONITOR_FUNCTION:monitorHwndHasOpenChatEndpoint@@*/

/*@@MONITOR_FUNCTION:refreshMonitorWindowIdentity@@*/

/*@@MONITOR_FUNCTION:refreshMonitorIdentityIndex@@*/


/*@@MONITOR_FUNCTION:monitorOpenEndpointsForConversation@@*/

/*@@MONITOR_FUNCTION:monitorFreshNativeLocations@@*/

/*@@MONITOR_FUNCTION:monitorEndpointInstanceId@@*/

/*@@MONITOR_FUNCTION:monitorEndpointGeometry@@*/
