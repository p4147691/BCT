const MONITOR_CONTROL_HOST = "com.pas40.desktop_window_monitor_control";

const MONITOR_CORE_HOST = MONITOR_CONTROL_HOST;

const ORCHESTRATOR_STATE_URL = "act:/state";
const ORCHESTRATOR_MONITOR_STATE_URL = "act:/monitor/state";

const ORCHESTRATOR_LLM_NODES_URL = "act:/llm-nodes";
const ORCHESTRATOR_LOCAL_LLM_STATUS_URL = "act:/local-llm/status";
const ORCHESTRATOR_LOCAL_LLM_CONTROL_URL = "act:/local-llm/control";
const LOCAL_LLM_UI_URL = "http://127.0.0.1:7865/";

let monitorLocalLlmControlState = null;
let monitorLocalLlmStatusPromise = null;

const ORCHESTRATOR_HEALTH_URL = "act:/health";

const ORCHESTRATOR_PENDING_REPORTS_URL = "act:/orchestrator/reports/pending";

const ORCHESTRATOR_AUTO_PROCESS_URL = "act:/orchestrator/auto-process";

const ORCHESTRATOR_HIERARCHY_URL = "act:/organization/hierarchy";

const ORCHESTRATOR_LAYOUT_SAVE_URL = "act:/organization/layout-save";

const ORCHESTRATOR_ORG_RESOURCES_URL = "act:/organization/resources";

const ORCHESTRATOR_ORG_AI_NODES_URL = "act:/organization/ai-nodes";

const ORCHESTRATOR_ORG_WORKSPACES_URL = "act:/organization/workspaces";

const ORCHESTRATOR_EXECUTOR_METRICS_URL = "act:/metrics/executors";

const ORCHESTRATOR_NODE_CONTROL_URL = "act:/organization/node-control";

const ORCHESTRATOR_ROLE_ADMIN_URL = "act:/role-admin";

const ORCHESTRATOR_BOOTSTRAP_EXEMPT_URL = "act:/bootstrap/exempt";

const ORCHESTRATOR_NOTE_AI_URL = "act:/monitor/note/organize";

const ORCHESTRATOR_CONTEXT_TITLE_URL = "act:/monitor/context-title";

const ORCHESTRATOR_CONVERSATION_RENAME_URL = "act:/monitor/conversation-title/rename";

const ORCHESTRATOR_CONVERSATION_CLOSE_TAB_URL = "act:/monitor/conversation/close-tab";

// ACT transport is isolated in monitor-act-transport.js.
// Monitor consumes one narrow public boundary: actFetch.
const actFetch = globalThis.MonitorActTransport && globalThis.MonitorActTransport.actFetch;
if (typeof actFetch !== "function") throw new Error("MONITOR_ACT_TRANSPORT_MISSING");

function monitorExtensionVersion() {
  try { return String(globalThis.chrome?.runtime?.getManifest?.().version || "").trim(); }
  catch (_) { return ""; }
}

function monitorWindowTitle() {
  const version = monitorExtensionVersion();
  return version ? `BCT Window Monitor · ${version}` : "BCT Window Monitor";
}

function monitorIsOwnWindowTitle(value) {
  const title = String(value || "").trim();
  return title === "BCT Window Monitor" || title.startsWith("BCT Window Monitor ·") ||
    title === "DWM" || title.startsWith("DWM ·") || title.startsWith("DesktopWindow Monitor");
}

document.title = monitorWindowTitle();

const monitorRoot = document.createElement("aside");

monitorRoot.className = "desktop-window-monitor";

monitorRoot.setAttribute("aria-label", "BWM");

monitorRoot.innerHTML = `















  <header class="monitor-header">















    <div class="monitor-title-block"><div class="monitor-title-line"><strong id="monitorTitle">BWM</strong><span id="monitorVersion" class="monitor-version" role="status"></span><span id="monitorService" style="display:none">호환 계층 확인 중…</span></div><div class="monitor-utility-actions" role="toolbar" aria-label="BWM 복구 도구"><button id="monitorExtensionReload" type="button" title="이미 설치된 BWM 코드를 다시 읽습니다. GitHub 소스나 설치본을 배포하지는 않습니다.">확장 리로드</button><button id="monitorRccReload" type="button" title="현재 관측된 정확한 RCC 인스턴스 하나를 BCT 영수증 경로로 다시 로드합니다.">RCC 리로드</button><button id="monitorBctRecover" type="button" title="Windows의 BCT Core Supervisor 공식 작업을 실행하고 READY를 확인합니다.">BCT 시작·복구</button><button id="monitorMcpTunnelRecover" type="button" title="Windows의 BCT Tunnel Supervisor 공식 작업을 실행하고 health/ready를 확인합니다.">MCP 터널 복구</button><button id="monitorBctControlRefresh" type="button" title="선택한 정확한 ChatGPT 대화 탭을 다시 불러와 BC 도구 연결을 새로 읽습니다.">BC 도구 새로고침</button></div></div>















    <div class="monitor-header-actions"><button id="monitorCollapse" type="button" title="Monitor 전체 접기" aria-label="Monitor 전체 접기">−</button></div>















  </header>















  <div id="monitorClosedRecoveryMenu" class="monitor-closed-recovery-menu" hidden></div>















  <section class="monitor-section monitor-ai-section">















    <div class="monitor-bct-nodes-head"><strong>연결된 창</strong><span id="monitorBctNodeSummary">확인 중…</span><button id="monitorBctNodesRefresh" type="button" title="RCC 노드 목록 다시 조회" hidden>새로고침</button></div>
    <div id="monitorWorkers" class="monitor-workers monitor-bct-nodes" aria-live="polite"></div>
    <div id="monitorGithubInbox" class="monitor-bct-node-empty" aria-live="polite"></div>















  </section>















  `;

// Presentation-only layout: no controls or identities are recreated.
const bwmUiLayoutControl = window.MonitorUiLayout?.create?.(
  monitorRoot, chrome.storage, (error) => console.warn("BWM UI layout rejected", error),
  { onCaptureFallbackChange: () => globalThis.dispatchEvent(new Event("bwm-thumbnail-policy-changed")) }
);

// Runtime feature boundaries. Keep these explicit so future isolation does not
// require deleting UI or startup code from the production path.
const MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED = true;
const MONITOR_FEATURE_MEMO_ENABLED = true;
const MONITOR_FEATURE_RECOVERY_ENABLED = true;
const MONITOR_ACTIVE_STARTUP_ENABLED = true;
const MONITOR_ACT_STARTUP_TEST_ENABLED = false;
const MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED = false;
const MONITOR_NODE_RENDER_ENABLED = false;
const MONITOR_NODE_RENDER_PROJECTION_ONLY = false;
const MONITOR_BCT_NODE_SUMMARY_ENABLED = true;

// Event-only runtime diagnostics. These counters live only in this renderer;
// they never write storage and never schedule work.
const MONITOR_BUILD_ID = "20261013-bct-window-monitor-3";
const monitorRenderDiagnostics = {
  startedAt: Date.now(),
  renderRequests: 0,
  renderRuns: 0,
  captureRequests: 0,
  captureRuns: 0,
  captureSuccess: 0,
  captureFailure: 0,
  blobCreates: 0,
  blobRevokes: 0,
  refreshRuns: 0,
  refreshLastMs: 0,
  refreshSlowestMs: 0,
  refreshLastStages: {},
};

function monitorRecordRefreshTiming(startedAt, stages) {
  const totalMs = Math.max(0, performance.now() - startedAt);
  monitorRenderDiagnostics.refreshRuns += 1;
  monitorRenderDiagnostics.refreshLastMs = totalMs;
  monitorRenderDiagnostics.refreshSlowestMs = Math.max(monitorRenderDiagnostics.refreshSlowestMs, totalMs);
  monitorRenderDiagnostics.refreshLastStages = { ...stages, total: totalMs };
}

chrome.runtime.sendMessage({ type:"monitor-register-popup-window" }).catch(() => {});

const monitorNotesFeature = globalThis.MonitorNotesFeature?.create({
  document,
  enabled: MONITOR_FEATURE_MEMO_ENABLED,
  sharedNotePort: Object.freeze({
    getContent: () => monitorNative({ type: "getSharedNote" }),
    setContent: (text) => monitorNative({ type: "setSharedNote", text }),
    getView: () => monitorNative({ type: "getSharedMonitorNoteView" }),
    setView: (ratio) => monitorNative({ type: "setSharedMonitorNoteView", ratio }),
  }),
  aiPort: Object.freeze({
    async organize(payload) {
      const response = await actFetch(ORCHESTRATOR_NOTE_AI_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);
      return data;
    },
  }),
  onTrash: (note) => trashMonitorNote(note),
  onStatus: (message, ok) => setMonitorStatus(message, ok),
  errorText: (value) => monitorRoleAdminErrorText(value),
  onLayoutChange: () => syncMonitorSideNote(),
  requestFrame: requestAnimationFrame,
  cancelFrame: cancelAnimationFrame,
  setTimer: setTimeout,
  clearTimer: clearTimeout,
});
if (!monitorNotesFeature) throw new Error("MONITOR_NOTES_FEATURE_MISSING");

const monitorPreviewWallpaper = document.createElement("div");

monitorPreviewWallpaper.className = "monitor-preview-wallpaper";

monitorPreviewWallpaper.setAttribute("aria-hidden", "true");

const monitorWindowLayer = document.createElement("div");

monitorWindowLayer.className = "monitor-window-layer";

monitorWindowLayer.setAttribute("aria-hidden", "true");

const monitorTransitionFlash = document.createElement("div");

monitorTransitionFlash.className = "monitor-transition-flash";

monitorTransitionFlash.setAttribute("aria-hidden", "true");

const monitorDesktopSwitcher = document.createElement("nav");

monitorDesktopSwitcher.className = "monitor-desktop-switcher";

monitorDesktopSwitcher.setAttribute("aria-label", "가상 데스크톱 미리보기");

monitorDesktopSwitcher.innerHTML = `<button id="monitorDesktopScrollLeft" class="monitor-desktop-scroll-arrow monitor-desktop-scroll-left" type="button" aria-label="데스크톱 썸네일 왼쪽으로 이동">◀</button><div id="monitorDesktopScrollViewport" class="monitor-desktop-scroll-viewport"><div id="monitorDesktopThumbs" class="monitor-desktop-thumbs"></div></div><button id="monitorDesktopScrollRight" class="monitor-desktop-scroll-arrow monitor-desktop-scroll-right" type="button" aria-label="데스크톱 썸네일 오른쪽으로 이동">▶</button><button id="monitorCreateDesktop" class="monitor-create-desktop" type="button"><span class="monitor-create-plus">+</span><span>&#49352; &#45936;&#49828;&#53356;&#53681;</span></button><button id="monitorNodeTrash" class="monitor-node-trash monitor-node-trash-fixed" type="button" title="노드 목록 또는 썸네일을 여기로 끌어 삭제" aria-label="노드 휴지통"><span class="monitor-node-trash-icon">🗑</span><span>휴지통</span></button><div id="monitorNodeTrashUndo" class="monitor-node-trash-undo" hidden><button id="monitorNodeTrashUndoButton" type="button" title="방금 버린 노드 복구"><span>↶</span><span id="monitorNodeTrashUndoCountdown">30s</span></button></div><div id="monitorDesktopUndo" class="monitor-desktop-undo" hidden><button id="monitorDesktopUndoButton" type="button" title="&#49325;&#51228;&#54620; &#45936;&#49828;&#53356;&#53681; &#46104;&#46028;&#47532;&#44592;" aria-label="&#49325;&#51228;&#54620; &#45936;&#49828;&#53356;&#53681; &#46104;&#46028;&#47532;&#44592;"><span class="monitor-undo-icon" aria-hidden="true">&#x21B6;</span><span id="monitorDesktopUndoCountdown" class="monitor-undo-countdown">30s</span></button></div>`;

document.body.prepend(monitorPreviewWallpaper, monitorWindowLayer, monitorTransitionFlash);

const monitorPreviewBackground = globalThis.MonitorPreviewBackground.create({
  element:monitorPreviewWallpaper,
  contract:globalThis.MonitorThumbnailContract,
});

const monitorSketchStoragePort = Object.freeze({
  get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch (_) { return false; } },
  remove(key) { try { localStorage.removeItem(key); return true; } catch (_) { return false; } },
});
const monitorSketchFeature = globalThis.MonitorSketchFeature?.create({
  document,
  storage: monitorSketchStoragePort,
  ImageCtor: Image,
  requestFrame: requestAnimationFrame,
  setTimer: setTimeout,
  clearTimer: clearTimeout,
  onLayoutChange: () => syncMonitorSideNote(),
});
if (!monitorSketchFeature) throw new Error("MONITOR_SKETCH_FEATURE_MISSING");
document.body.append(monitorDesktopSwitcher, monitorSketchFeature.element, monitorNotesFeature.element, monitorRoot);
if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED && !MONITOR_FEATURE_RECOVERY_ENABLED) monitorDesktopSwitcher.style.setProperty("display", "none", "important");

const MONITOR_DESKTOP_SWITCHER_GAP_PX = 12;
function syncMonitorPanelToDesktopSwitcher() {
  if (!monitorRoot || !monitorDesktopSwitcher || monitorRoot.classList.contains("collapsed")) return;
  const rootRect = monitorRoot.getBoundingClientRect();
  const switcherRect = monitorDesktopSwitcher.getBoundingClientRect();
  if (!Number.isFinite(switcherRect.top) || switcherRect.height < 1 || switcherRect.top <= rootRect.top + 120) return;
  const targetHeight = Math.max(260, Math.floor(switcherRect.top - rootRect.top - MONITOR_DESKTOP_SWITCHER_GAP_PX));
  const targetPx = `${targetHeight}px`;
  if (monitorRoot.style.height !== targetPx) monitorRoot.style.height = targetPx;
  if (monitorRoot.style.maxHeight !== targetPx) monitorRoot.style.maxHeight = targetPx;
}
const queueMonitorPanelToDesktopSwitcherSync = () => requestAnimationFrame(() => {
  syncMonitorPanelToDesktopSwitcher();
  syncMonitorSideNote();
});
if (MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED || MONITOR_FEATURE_RECOVERY_ENABLED) {
  new ResizeObserver(queueMonitorPanelToDesktopSwitcherSync).observe(monitorDesktopSwitcher);
  window.addEventListener("resize", queueMonitorPanelToDesktopSwitcherSync);
  queueMonitorPanelToDesktopSwitcherSync();
}

document.body.classList.add("desktop-window-monitor-active");

const monitorTitle = document.getElementById("monitorTitle");

const monitorVersion = document.getElementById("monitorVersion");

const monitorWorkRecoveryMount = document.getElementById("monitorWorkRecoveryMount");

if (monitorWorkRecoveryMount && globalThis.MonitorWorkRecovery) monitorWorkRecoveryMount.append(createMonitorWorkRecoveryButton());

const monitorTitleLine = monitorTitle?.closest(".monitor-title-line");

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

syncMonitorTitle();

const monitorTitleResizeObserver = new ResizeObserver(syncMonitorTitle);

monitorTitleResizeObserver.observe(monitorRoot);

requestAnimationFrame(syncMonitorTitle);

/* Recovery owns deleted-note storage; Notes receives it through one callback. */
function persistMonitorTrashedNotes(){
  chrome.storage.local.set({[MONITOR_TRASHED_NOTES_KEY]:[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,100)});
}

function trashMonitorNote(note){
  if(!note?.id)return;monitorTrashedNotes.set(String(note.id),{...note,trashed_at_ms:Date.now()});persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();
}

function restoreMonitorTrashedNote(id){
  const key=String(id),note=monitorTrashedNotes.get(key);if(!note)return;
  if(!monitorNotesFeature.restoreNote(note))return;
  monitorTrashedNotes.delete(key);persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();
}

function deleteMonitorTrashedNote(id){monitorTrashedNotes.delete(String(id));persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}

function clearMonitorTrashedNotes(){monitorTrashedNotes.clear();persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}

/* Composition only: place Notes, then place Sketch to its left. */
function syncMonitorSideNote(){
  const boardCollapsed=monitorRoot.classList.contains("collapsed");
  if(boardCollapsed){
    monitorNotesFeature.layout({boardCollapsed:true});
    monitorSketchFeature.layout({boardCollapsed:true});
    return;
  }
  const rootRect=monitorRoot.getBoundingClientRect();
  const noteLayout=monitorNotesFeature.layout({boardCollapsed:false,rootRect});
  monitorSketchFeature.layout({boardCollapsed:false,rootRect,noteLeft:noteLayout.left});
}

if (MONITOR_FEATURE_MEMO_ENABLED) {
  setTimeout(() => { void monitorNotesFeature.refreshContent(); }, 250);
  setTimeout(() => { void monitorNotesFeature.refreshView(); }, 320);
  new ResizeObserver(syncMonitorSideNote).observe(monitorRoot);
  window.addEventListener("resize", syncMonitorSideNote);
  requestAnimationFrame(syncMonitorSideNote);
}

const monitorService = document.getElementById("monitorService");

const monitorWorkers = document.getElementById("monitorWorkers");
const monitorGithubInbox = document.getElementById("monitorGithubInbox");

const monitorCollapse = document.getElementById("monitorCollapse");
monitorCollapse.classList.add("monitor-collapse-chevron");
monitorCollapse.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg>';

const monitorClosedRecovery = document.getElementById("monitorClosedRecovery");

const monitorClosedRecoveryMenu = document.getElementById("monitorClosedRecoveryMenu");

const monitorDesktopThumbs = document.getElementById("monitorDesktopThumbs");

const monitorDesktopScrollViewport = document.getElementById("monitorDesktopScrollViewport");

const monitorDesktopScrollLeft = document.getElementById("monitorDesktopScrollLeft");

const monitorDesktopScrollRight = document.getElementById("monitorDesktopScrollRight");

function monitorDesktopScrollStep(){const tile=monitorDesktopThumbs.querySelector(".monitor-desktop-thumb");return Math.max(132,Math.round(tile?.getBoundingClientRect?.().width||156)+8);}
function syncMonitorDesktopScrollArrows(){const max=Math.max(0,monitorDesktopScrollViewport.scrollWidth-monitorDesktopScrollViewport.clientWidth);const overflow=max>4;monitorDesktopScrollLeft.hidden=!overflow;monitorDesktopScrollRight.hidden=!overflow;if(!overflow)return;monitorDesktopScrollLeft.disabled=monitorDesktopScrollViewport.scrollLeft<=2;monitorDesktopScrollRight.disabled=monitorDesktopScrollViewport.scrollLeft>=max-2;}

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

let monitorUndoTimer = 0;

const MONITOR_UNDO_MAX = 8;
const MONITOR_UNDO_TTL_MS = 10000;
const monitorRecoveryUndoSession = globalThis.MonitorRecoveryUndoSession.create({maxEntries: MONITOR_UNDO_MAX, ttlMs: MONITOR_UNDO_TTL_MS});

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
const monitorDesktopModeController = globalThis.MonitorDesktopModeController.create({
  persist: snapshot => chrome.storage.local.set({ [MONITOR_DESKTOP_MANAGEMENT_MODE_KEY]: snapshot }).catch(() => {})
});

function monitorDesktopManagementMode(desktopId) { return monitorDesktopModeController.get(desktopId); }

function monitorDesktopManagementModeText(mode) {
  if (mode === "MANAGED") return "관리";
  if (mode === "PROTECTED") return "보호";
  return "보기";
}

function monitorDesktopManagementNextMode(mode) { return monitorDesktopModeController.next(mode); }

function monitorSetDesktopManagementMode(desktopId, nextMode) {
  const id = String(desktopId || "").trim();
  const mode = String(nextMode || "").toUpperCase();
  if (!monitorDesktopModeController.set(id, mode)) return;
  setMonitorStatus(`D${Math.max(1, monitorDesktopState.desktopIds.indexOf(id) + 1)} · ${monitorDesktopManagementModeText(mode)}`, true);
  syncDesktopSwitcher();
}

function monitorAttachDesktopManagementControl(label, desktopId) {
  if (!label || !desktopId) return;
  let control = label.querySelector(".monitor-desktop-management-control");
  if (!control) {
    control = document.createElement("span");
    control.className = "monitor-desktop-management-control";
    control.setAttribute("role", "button");
    control.tabIndex = 0;
    const cycle = (event) => {
      event.preventDefault(); event.stopPropagation();
      const id = String(control.dataset.desktopId || "");
      monitorSetDesktopManagementMode(id, monitorDesktopManagementNextMode(monitorDesktopManagementMode(id)));
    };
    control.addEventListener("pointerdown", (event) => { event.stopPropagation(); });
    control.addEventListener("click", cycle);
    control.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") cycle(event); });
    label.insertBefore(control, label.querySelector(".monitor-desktop-label-text"));
  }
  const mode = monitorDesktopManagementMode(desktopId);
  control.dataset.desktopId = String(desktopId);
  control.dataset.mode = mode;
  control.textContent = mode === "MANAGED" ? "◆" : (mode === "PROTECTED" ? "🔒" : "○");
  control.title = `데스크 관리: ${monitorDesktopManagementModeText(mode)} · 클릭하여 변경`;
  control.setAttribute("aria-label", control.title);
}

chrome.storage.local.get([MONITOR_DESKTOP_MANAGEMENT_MODE_KEY], (data) => {
  const raw = data?.[MONITOR_DESKTOP_MANAGEMENT_MODE_KEY];
  monitorDesktopModeController.hydrate(raw);
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
async function refreshInitialBackgroundThumbs() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) {
    monitorInitialThumbStage = "disabled";
    return false;
  }
  const selectedId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "";
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refreshBackground) {
    monitorInitialThumbStage = "renderer-unavailable";
    monitorInitialThumbError = "THUMBNAIL_BACKGROUND_RENDERER_UNAVAILABLE";
    return false;
  }
  let pending = [
    selectedId,
    ...monitorDesktopState.desktopIds.filter((id) => id && id !== selectedId)
  ].filter(Boolean);
  if (!pending.length) {
    monitorInitialThumbStage = "no-desktops";
    monitorInitialThumbError = "NO_DESKTOP_IDS";
    return false;
  }

  monitorInitialThumbStage = "background-requesting";
  monitorInitialThumbError = "";
  const retryDelays = [160, 420];
  for (let attempt = 0; pending.length; attempt += 1) {
    const failed = [];
    for (const desktopId of pending) {
      const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (!visual?.isConnected) { failed.push(desktopId); continue; }
      const result = await renderer.refreshBackground(visual, desktopId).catch(() => null);
      if (result?.wallpaperReady !== true) failed.push(desktopId);
    }
    pending = failed;
    if (!pending.length || attempt >= retryDelays.length) break;
    await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
  }
  monitorInitialThumbStage = pending.length ? "background-failed" : "background-ready";
  monitorInitialThumbError = pending.length ? `UNREADY_DESKTOPS:${pending.join(",")}` : "";
  return pending.length === 0;
}
let monitorInitialSemanticThumbSyncDone = false;
let monitorInitialSemanticThumbSyncInflight = false;
let monitorInitialSemanticThumbSyncTimer = 0;

let monitorSharedSelectedDesktopId = "";

let monitorSharedSelectionReady = false;

function monitorApplySharedDesktopSelection(desktopId) {

  const id = String(desktopId || "").trim(); monitorSharedSelectedDesktopId = id;

  if (!monitorSharedSelectionReady || !id || !monitorDesktopState.desktopIds.includes(id) || monitorDesktopState.observedDesktopId === id) return;

  monitorDesktopState.observedDesktopId = id;

  renderVirtualDesktops({ count:monitorDesktopState.count, currentIndex:monitorDesktopState.currentIndex, desktopIds:monitorDesktopState.desktopIds, currentDesktopId:monitorDesktopState.currentDesktopId, hostDesktopId:monitorDesktopState.hostDesktopId, hostWindowHwnd:monitorDesktopState.hostWindowHwnd });

  refreshObservedWindows();

}

let monitorStatusHoldUntil = 0;

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

const MONITOR_ROLE_ADMIN_ROLES = ["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"];

const monitorRoleAdminInFlight = new Set();

const monitorRoleAdminSelection = new Map();

const monitorRoleMutationInFlight = new Set();

let monitorRoleAssignMode = "";

let monitorRoleAdminState = null;

let monitorRoleAdminSignature = "";

let monitorRoleAdminBusy = false;

function monitorRoleAdminCandidates(state) {

  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];

  const counts = new Map();

  for (const ep of endpoints) if (String(ep?.presence_state||"").toUpperCase()==="OPEN") { const k=String(ep?.conversation_key||"").trim(); if(k) counts.set(k,(counts.get(k)||0)+1); }

  return endpoints.filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN").filter(ep=>{const k=String(ep?.conversation_key||"").trim();return k&&counts.get(k)===1;}).map(ep=>({conversation_key:String(ep.conversation_key).trim(),profile_id:String(ep?.profile_id||"").toUpperCase()})).sort((a,b)=>a.profile_id.localeCompare(b.profile_id)||a.conversation_key.localeCompare(b.conversation_key));

}

function monitorRoleAdminPath(action) { return `${ORCHESTRATOR_ROLE_ADMIN_URL}/${action}`; }

function monitorRoleAdminPayload(action, roleRow, conversationKey="") {

  const payload={ role:String(roleRow?.role_id||""), expected_generation:Number(roleRow?.generation||0) };

  if(action==="assign"||action==="replace") payload.conversation_key=String(conversationKey||"").trim();

  return payload;

}

function monitorRoleAdminErrorText(value) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorRoleAdminErrorText"].apply(this, arguments); }

function monitorSelectedRoleWorker(state) {

  const selected = [...monitorSelectedHwnds];

  if (selected.length !== 1) return null;

  const hwnd = String(selected[0] || "");

  return monitorWorkersForState(state).find((worker) => {

    if (classifyMonitorWorker(worker) !== "chatgpt" || !String(worker?.conversation_key || "").trim()) return false;

    const location = monitorEndpointLocation(worker, state);

    return String(monitorResolvedWorkerHwnd(worker, state, location) || "") === hwnd;

  }) || null;

}

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

function monitorExactOpenEndpoint(state, conversationKey) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorExactOpenEndpoint"].apply(this, arguments); }

async function monitorBootstrapExempt(body){
  const r=await actFetch(ORCHESTRATOR_BOOTSTRAP_EXEMPT_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);
  return {r,data};
}

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

async function monitorTurnWorkerOff(worker,state) {

  const key=String(worker?.conversation_key||"").trim(); if(!key||monitorRoleMutationInFlight.has(key))return;

  const actNode=monitorActBrowserNode(worker,state);

  const role=String(actNode?.role||"").toUpperCase();

  const exemption=actNode?.exemption||null;

  if(!actNode||!role){setMonitorStatus("ACT 역할 상태 확인 대기",false);return;}

  monitorRoleMutationInFlight.add(key);

  try {

    if(exemption||role==="EXEMPT") {

      const r=await fetch(`${ORCHESTRATOR_ROLE_ADMIN_URL}/worker`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_key:key,actor:"USER_MONITOR"})}); const data=await r.json();

      if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);

    } else if(MONITOR_ROLE_ADMIN_ROLES.includes(role)) {

      await refreshMonitorRoleAdmin(); const roleRow=(monitorRoleAdminState?.roles||[]).find((x)=>String(x?.role_id||"")===role); if(!roleRow)throw new Error("ROLE_STATE_UNAVAILABLE");

      const r=await fetch(monitorRoleAdminPath("release"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(monitorRoleAdminPayload("release",roleRow))}); const data=await r.json();

      if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);

    }

    setMonitorStatus("일반 WORKER로 전환됨",true); await refreshMonitorRoleAdmin(); await refreshAiMonitor();

  } catch(error){setMonitorStatus(`OFF 실패 · ${monitorRoleAdminErrorText(error?.message||error)}`,false);}

  finally {monitorRoleMutationInFlight.delete(key); if(monitorLastAiState)renderWorkers(monitorLastAiState);}

}

function monitorRoleAdminShort(role) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorRoleAdminShort"].apply(this, arguments); }

function setMonitorRoleAdminStatus(text, bad=false) { const el=document.getElementById("monitorRoleAdminStatus"); if(!el)return; el.textContent=String(text||""); el.classList.toggle("error",Boolean(bad)); }

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

async function refreshMonitorRoleAdmin() {

  if(monitorRoleAdminBusy)return; monitorRoleAdminBusy=true;

  try{const r=await actFetch(ORCHESTRATOR_ROLE_ADMIN_URL,{cache:"no-store"});const data=await r.json();if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);const signature=JSON.stringify([data.roles,monitorRoleAdminCandidates(monitorLastAiState||{}).map(x=>x.conversation_key)]);monitorRoleAdminState=data;setMonitorRoleAdminStatus("");if(signature!==monitorRoleAdminSignature){monitorRoleAdminSignature=signature;renderMonitorRoleAdmin();}}

  catch(error){setMonitorRoleAdminStatus(monitorRoleAdminErrorText(error?.message||error),true);}

  finally{monitorRoleAdminBusy=false;}

}

async function runMonitorRoleAdminAction(action, roleRow, conversationKey="") {

  const role=String(roleRow?.role_id||""); const lock=action==="broadcast"?"broadcast":role; if(!lock||monitorRoleAdminInFlight.has(lock))return;

  if((action==="assign"||action==="replace")&&!String(conversationKey||"").trim()){setMonitorRoleAdminStatus("conversationKey 선택 필요",true);return;}

  monitorRoleAdminInFlight.add(lock); renderMonitorRoleAdmin(); setMonitorRoleAdminStatus(`${action}…`);

  try{const body=action==="broadcast"?{}:monitorRoleAdminPayload(action,roleRow,conversationKey);const r=await fetch(monitorRoleAdminPath(action),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const data=await r.json();if(!r.ok||!data?.ok)throw new Error(data?.error||`HTTP ${r.status}`);setMonitorRoleAdminStatus(action==="broadcast"?"상태 알림 전송됨":"적용됨");}

  catch(error){setMonitorRoleAdminStatus(monitorRoleAdminErrorText(error?.message||error),true);}

  finally{monitorRoleAdminInFlight.delete(lock);await refreshMonitorRoleAdmin();await refreshAiMonitor();renderMonitorRoleAdmin();}

}

const MONITOR_AGENT_GROUPS = [

  { key: "chatgpt", label: "ChatGPT" },

  { key: "external-llm", label: "External LLM" },

  { key: "local-llm", label: "Local LLM" },

];

function isMonitorVisibleWorker(worker, state) {

  const conversationKey = String(worker?.conversation_key || "").trim();

  if (conversationKey && monitorTrashedConversationKeys.has(conversationKey)) return false;

  const profileId = String(worker?.profile_id || "").toUpperCase();

  const role = String(worker?.role || "").toUpperCase();

  if (worker?.__kind === "LLM_NODE") return Boolean(worker?.node_id && profileId && role);

  if (!profileId || ["CURRENT", "INTERNAL", "LEGACY"].includes(profileId) || (!role && !worker?.exemption)) return false;

  if (new Set(["CONTROL", "TEST", "INTERNAL", "LEGACY"]).has(role)) return false;

  if (["GOOGLE", "NAVER"].includes(profileId)) return Boolean(endpointForMonitorWorker(worker, state));

  return !["offline", "unavailable", "disconnected"].includes(String(worker?.status || "").toLowerCase());

}

function classifyMonitorWorker(worker) { return globalThis.MonitorDomainAPIs["conversations"]["classifyMonitorWorker"].apply(this, arguments); }

function monitorWorkerReadyForUse(worker, groupKey = classifyMonitorWorker(worker)) {
  if (!worker) return false;

  const provider = String(worker?.provider || worker?.provider_type || "").trim().toLowerCase();
  const profileId = String(worker?.profile_id || "").trim().toUpperCase();
  const nodeType = String(worker?.llm_node_type || worker?.node_type || "").trim().toLowerCase();
  const isCodex = provider === "codex" || profileId === "CODEX" || nodeType.includes("codex");

  // A visible ChatGPT browser node is already a captured/usable node.
  if (worker?.__kind !== "LLM_NODE") return groupKey === "chatgpt";

  const status = String(worker?.status || "").trim().toLowerCase();
  const connection = String(worker?.connection_status || worker?.transport_status || "").trim().toLowerCase();
  const runtime = String(worker?.llm_runtime_state || worker?.runtime_state || worker?.runtime?.state || "").trim().toLowerCase();
  const work = String(worker?.work_status || "").trim().toLowerCase();
  const readyStates = ["ready", "loaded", "connected", "online", "healthy", "busy", "working", "running", "generating", "in_progress", "active"];

  // Confirmed unavailability wins over stale positive flags for every resource.
  const unavailableStates = ["offline", "unavailable", "unconfigured", "error"];
  if (unavailableStates.includes(status) || unavailableStates.includes(connection)) return false;
  if (worker?.loaded === true || worker?.ready === true || worker?.connected === true) return true;

  // Codex is lit only after its own runtime reports a real usable/busy state.
  if (isCodex) return readyStates.includes(runtime) || readyStates.includes(status) || readyStates.includes(work);

  // Local models must be actually started/loaded/connected. Merely being installed
  // or registered as "available" is intentionally not enough to light the UI.
  if (groupKey === "local-llm") {
    // The shared unavailable guard above already applies to local models.
    return readyStates.includes(runtime) || readyStates.includes(status) || readyStates.includes(connection);
  }

  // External LLM availability already represents a usable remote connection.
  return [...readyStates, "available"].includes(status)
    || [...readyStates, "available"].includes(connection)
    || [...readyStates, "available"].includes(runtime);
}

function monitorIsExplicitCodexResource(node) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorIsExplicitCodexResource"].apply(this, arguments); }

function monitorCodexResourceProfile(worker) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorCodexResourceProfile"].apply(this, arguments); }

function monitorIsActionableCodexResource(worker) {
  return worker?.__kind === "LLM_NODE"
    && monitorIsExplicitCodexResource(worker)
    && monitorCodexResourceProfile(worker) === "GOOGLE";
}

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

function monitorLlmWorkersFromState(state) {
  const nodes = (Array.isArray(state?.llm_nodes) ? state.llm_nodes : [])
    .filter((node) => !monitorIsExplicitCodexResource(node));

  return nodes.map((node) => {
    const kind = String(node?.kind || "external").toLowerCase() === "local" ? "local" : "external";
    const provider = String(node?.provider || "unknown").trim().toLowerCase();
    const model = String(node?.model || provider || "unknown").trim();
    const status = String(node?.status || "unavailable").trim().toLowerCase();
    const label = provider === "openrouter"
      ? "OpenRouter · " + model
      : provider === "gemini"
        ? "Gemini · " + model
        : provider === "groq"
          ? "Groq · " + model
          : model;
    const fallbackId = kind + ":" + provider + ":" + model;

    return {
      __kind: "LLM_NODE",
      __display_key: "LLM:" + String(node?.node_id || fallbackId),
      node_id: String(node?.node_id || ""),
      profile_id: kind === "local" ? "LOCAL" : "EXTERNAL",
      provider: kind === "local" ? "local_llm" : "external_llm",
      role: model,
      display_name: label,
      status,
      connection_status: status === "available"
        ? "connected"
        : (["offline", "unavailable", "unconfigured", "error"].includes(status) ? "offline" : status),
      work_status: status === "rate_limited" ? "waiting_resource" : (status === "error" ? "failed" : "idle"),
      llm_provider: provider,
      llm_model: model,
      llm_node_type: String(node?.node_type || "LLM_MODEL"),
      free_only: node?.free_only === true,
      role_claim: node?.role_claim === true,
      observed_at: node?.observed_at || null,
      llm_runtime_state: status === "unconfigured"
        ? "UNCONFIGURED"
        : String(node?.runtime_state || node?.runtime?.state || status || "UNAVAILABLE").toUpperCase(),
      llm_runtime: node?.runtime && typeof node.runtime === "object" ? node.runtime : {},
    };
  });
}

function monitorLocalModelIsLoaded(node) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorLocalModelIsLoaded"].apply(this, arguments); }

function monitorLocalOllamaModels(payload) {
  const nodes = Array.isArray(payload?.llm_nodes) ? payload.llm_nodes : [];
  return nodes
    .filter((node) => String(node?.kind || "").toLowerCase() === "local"
      && String(node?.provider || "").toLowerCase() === "ollama")
    .sort((a, b) => Number(monitorLocalModelIsLoaded(b)) - Number(monitorLocalModelIsLoaded(a)));
}

function monitorLlmRuntimePresentation(worker, ready) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorLlmRuntimePresentation"].apply(this, arguments); }

function monitorCodexWorkersFromState(state, observedWorkers = []) {
  const stateNodes = Array.isArray(state?.llm_nodes) ? state.llm_nodes : [];
  const observed = Array.isArray(observedWorkers) ? observedWorkers : [];
  const sharedCli = stateNodes.find((node) => String(node?.provider || "").toLowerCase() === "codex"
    && node?.codex_cli_shared === true) || null;
  const profiles = [
    { profileId: "GOOGLE", nodeId: "CODEX:GOOGLE", name: "G-CODEX" },
  ];

  return profiles.map(({ profileId, nodeId, name }) => {
    const stateNode = stateNodes.find((node) => {
      const profile = String(node?.codex_profile_id || node?.profile_id || "").toUpperCase();
      return profile === profileId && monitorIsExplicitCodexResource(node);
    }) || null;
    const browserNode = observed.find((worker) =>
      String(worker?.profile_id || "").toUpperCase() === profileId && monitorIsExplicitCodexResource(worker)
    ) || null;
    // G-CODEX readiness may be backed by the shared host CLI even before its app window appears.
    const source = stateNode || browserNode || sharedCli;
    const rawStatus = String(source?.status || source?.availability || source?.connection_status || "").trim().toLowerCase();
    const rawWork = String(source?.work_status || source?.runtime_state || source?.runtime?.state || "").trim().toLowerCase();
    const busyStates = new Set(["busy", "working", "running", "generating", "in_progress", "active"]);
    const readyStates = new Set(["available", "ready", "loaded", "connected", "online", "healthy"]);
    const busy = Boolean(source) && (busyStates.has(rawStatus) || busyStates.has(rawWork));
    const ready = Boolean(sharedCli) || (Boolean(source) && (busy || readyStates.has(rawStatus) || readyStates.has(rawWork) || source?.ready === true || source?.connected === true || source?.available === true));
    const status = busy ? "busy" : (ready ? "available" : "offline");

    return {
      __kind: "LLM_NODE",
      __display_key: nodeId,
      node_id: nodeId,
      profile_id: "CODEX",
      codex_profile_id: profileId,
      provider: "codex",
      role: name,
      display_name: name,
      name,
      status,
      connection_status: status === "offline" ? "offline" : "connected",
      work_status: busy ? "working" : "idle",
      llm_provider: "codex",
      llm_model: name,
      llm_node_type: "CODEX_ACCOUNT",
      free_only: false,
      role_claim: false,
      observed_at: source?.observed_at || null,
      llm_runtime_state: busy ? "BUSY" : (ready ? "READY" : "OFFLINE"),
    };
  });
}

function cleanMonitorWorkerName(worker) { return globalThis.MonitorDomainAPIs["conversations"]["cleanMonitorWorkerName"].apply(this, arguments); }

function stationForMonitorWorker(worker, state) { return globalThis.MonitorDomainAPIs["conversations"]["stationForMonitorWorker"].apply(this, arguments); }

function monitorStationMetadata(station) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorStationMetadata"].apply(this, arguments); }

const monitorWindowDesktopLocations = new Map();

const monitorNonChatStartedByHwnd = new Map();

const MONITOR_NODE_BINDINGS_KEY = "desktopWindowMonitorNodeBindingsV1";

const MONITOR_APPROVED_CHAT_TRANSITIONS_KEY = "desktopWindowMonitorApprovedChatTransitionsV1";

const monitorNodeBindings = new Map();

const monitorApprovedChatTransitions = new Set();

let monitorNodeBindingsReady = false;

let monitorApprovedChatTransitionsReady = false;

let monitorPersistedNodeBindingsSignature = "";

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

function monitorCanonicalNodeBindings(values = monitorNodeBindings.values()) {
  const unique = new Map();
  for (const value of values) {
    if (!value || typeof value !== "object" || !String(value.conversation_key || "").trim()) continue;
    const canonical = monitorCanonicalJsonValue(value);
    const signature = JSON.stringify(canonical);
    if (!unique.has(signature)) unique.set(signature, canonical);
  }
  return [...unique.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value);
}

function monitorNodeBindingsSignature(values = monitorNodeBindings.values()) {
  return JSON.stringify(monitorCanonicalNodeBindings(values));
}

function monitorPersistNodeBindings() {

  if (!monitorNodeBindingsReady) return;

  const values = monitorCanonicalNodeBindings();
  const signature = JSON.stringify(values);
  if (signature === monitorPersistedNodeBindingsSignature) return false;
  monitorPersistedNodeBindingsSignature = signature;
  chrome.storage.local.set({ [MONITOR_NODE_BINDINGS_KEY]: values }).catch(() => {
    if (monitorPersistedNodeBindingsSignature === signature) monitorPersistedNodeBindingsSignature = "";
  });
  return true;

}

function monitorChatTransitionKey(nodeIdentityKey, profileId, oldKey, newKey) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorChatTransitionKey"].apply(this, arguments); }

function monitorChatTransitionIsApproved(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); return Boolean(key&&monitorApprovedChatTransitions.has(key));

}

function monitorRememberApprovedChatTransition(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); if(!key)return; monitorApprovedChatTransitions.add(key);

  if(monitorApprovedChatTransitionsReady)chrome.storage.local.set({[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]:[...monitorApprovedChatTransitions]});

}

function monitorBrowserLineageKey(endpoint) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorBrowserLineageKey"].apply(this, arguments); }

function monitorTabBindingKey(endpoint) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorTabBindingKey"].apply(this, arguments); }

function monitorStableNodeForWindow(hwnd, endpoint = null) {

  const tabKey=monitorTabBindingKey(endpoint);

  if (tabKey) { const byTab=monitorNodeBindings.get(tabKey); if (byTab) return byTab; }

  const lineage = monitorBrowserLineageKey(endpoint);

  if (lineage && monitorNodeBindings.has(`lineage:${lineage}`)) return monitorNodeBindings.get(`lineage:${lineage}`) || null;

  const key = String(hwnd || "").trim();

  return key && monitorNodeBindings.has(`hwnd:${key}`) ? (monitorNodeBindings.get(`hwnd:${key}`) || null) : null;

}

function monitorStableNodeForEndpoint(endpoint = null) {

  const tabKey=monitorTabBindingKey(endpoint);

  if (tabKey) { const byTab=monitorNodeBindings.get(tabKey); if (byTab) return byTab; }

  const lineage = monitorBrowserLineageKey(endpoint);

  if (lineage) {

    const byLineage = monitorNodeBindings.get(`lineage:${lineage}`);

    if (byLineage) return byLineage;

  }

  const instanceId = String(endpoint?.window_instance_id || endpoint?.metadata?.window_instance_id || "").trim();

  if (instanceId) {

    for (const binding of monitorNodeBindings.values()) {

      if (String(binding?.window_instance_id || "") === instanceId) return binding;

    }

  }

  const transport = String(endpoint?.transport_instance_id || "").trim();

  const session = String(endpoint?.session_id || "").trim();

  const key = String(endpoint?.conversation_key || "").trim();

  if (transport && session && key) {

    const candidates = [...new Map([...monitorNodeBindings.values()].map((b) => [String(b?.hwnd || b?.node_label || Math.random()), b])).values()].filter((b) =>

      String(b?.transport_instance_id || "") === transport

      && String(b?.session_id || "") === session

      && String(b?.conversation_key || "") === key

    );

    if (candidates.length === 1) return candidates[0];

  }

  const hwnd = endpointOsWindowHandle(endpoint);

  return hwnd ? monitorStableNodeForWindow(hwnd, endpoint) : null;

}

function monitorStoreNodeBinding(binding, endpoint = null) {

  const safe = { conversation_key:String(binding?.conversation_key||"").trim(), profile_id:String(binding?.profile_id||endpoint?.profile_id||"").toUpperCase(), hwnd:String(binding?.hwnd||"").trim(), desktop_id:String(binding?.desktop_id||"").trim(), window_instance_id:String(binding?.window_instance_id||"").trim(), title:String(binding?.title||""),

    transport_instance_id: String(endpoint?.transport_instance_id || binding?.transport_instance_id || "").trim(),

    session_id: String(endpoint?.session_id || binding?.session_id || "").trim(),

    tab_id: Number(endpoint?.tab_id ?? binding?.tab_id ?? 0) || 0

  };

  const tabKey=monitorTabBindingKey(endpoint);

  const lineage = monitorBrowserLineageKey(endpoint);

  const hwnd = String(safe?.hwnd || "").trim();

  for (const [mapKey, existing] of monitorNodeBindings) {

    if (mapKey === tabKey || mapKey === `lineage:${lineage}` || mapKey === `hwnd:${hwnd}`) continue;

    if (safe.transport_instance_id && safe.session_id && safe.conversation_key

      && String(existing?.transport_instance_id || "") === safe.transport_instance_id

      && String(existing?.session_id || "") === safe.session_id

      && String(existing?.conversation_key || "") === safe.conversation_key

      && Number(existing?.tab_id||0)===Number(safe.tab_id||0)) monitorNodeBindings.delete(mapKey);

  }

  if(tabKey)monitorNodeBindings.set(tabKey,safe);

  if (lineage) monitorNodeBindings.set(`lineage:${lineage}`, safe);

  if (hwnd) monitorNodeBindings.set(`hwnd:${hwnd}`, safe);

  monitorPersistNodeBindings();

  return safe;

}

function monitorNodeChatChangeState(worker, state, physical) {

  const hwnd = String(physical?.hwnd || "").trim();

  const key = String(worker?.conversation_key || physical?.endpoint?.conversation_key || "").trim();

  if (!hwnd || !key) return null;

  const endpoint = physical?.endpoint || worker?.__endpoint || null;

  const instanceId = String(endpoint?.window_instance_id || endpoint?.metadata?.window_instance_id || physical?.location?.window_instance_id || "").trim();

  const tabKey=monitorTabBindingKey(endpoint);

  if(tabKey&&!monitorNodeBindings.has(tabKey)){

    /* transport/tab binding key missing: fall through to lineage/HWND binding lookup */

  }

  let binding = monitorStableNodeForWindow(hwnd, endpoint);

  const endpointTabId = Number(endpoint?.tab_id || 0);

  const bindingTabId = Number(binding?.tab_id || 0);

  // A different tab id means a stale/foreign binding was recovered through HWND/lineage fallback.

  // That is not evidence that this node changed chats; re-baseline the current node instead.

  if (binding && endpointTabId > 0 && bindingTabId > 0 && endpointTabId !== bindingTabId) binding = null;

  if (!binding) {

    binding = { hwnd, conversation_key:key, profile_id:String(worker?.profile_id || endpoint?.profile_id || "").toUpperCase(), desktop_id:String(physical?.location?.desktopId || ""), window_instance_id:instanceId, title:String(endpoint?.title || worker?.title || "") };

    if (physical?.location?.desktopId) { monitorStoreNodeBinding(binding, endpoint); }

    return { changed:false, binding };

  }

  if (binding.window_instance_id && instanceId && binding.window_instance_id !== instanceId) {

    binding = { ...binding, profile_id:String(worker?.profile_id || endpoint?.profile_id || "").toUpperCase(), desktop_id:String(physical?.location?.desktopId || binding.desktop_id || ""), window_instance_id:instanceId, title:String(endpoint?.title || worker?.title || binding.title || "") };

    // F5/reconnect may rotate volatile instance metadata. Preserve the node's prior chat

    // until the current browser lineage has been re-established and compared.

    monitorStoreNodeBinding(binding, endpoint);

  }

  if (String(binding.conversation_key || "") !== key) {

    const profileId=String(worker?.profile_id || endpoint?.profile_id || binding?.profile_id || "").toUpperCase();

    const nodeIdentityKey=String(monitorStableBrowserNodeKey(worker) || "").trim();

    const approvedTransition=monitorChatTransitionIsApproved(nodeIdentityKey,profileId,binding.conversation_key,key);

    if(approvedTransition){

      const healed={ ...binding, hwnd, conversation_key:key, profile_id:profileId, desktop_id:String(physical?.location?.desktopId || ""), window_instance_id:instanceId, title:String(endpoint?.title || worker?.title || "") };

      monitorStoreNodeBinding(healed,endpoint);

      return {changed:false,binding:healed};

    }

    return { changed:true, binding, new_conversation_key:key, endpoint };

  }

  binding = { ...binding, profile_id:String(worker?.profile_id || endpoint?.profile_id || binding.profile_id || "").toUpperCase(), desktop_id:String(physical?.location?.desktopId || binding.desktop_id || ""), window_instance_id:binding.window_instance_id || instanceId, title:String(endpoint?.title || worker?.title || binding.title || "") };

  monitorStoreNodeBinding(binding, endpoint);

  return { changed:false, binding };

}

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

function normalizeMonitorWindowTitle(value) { return String(value || "").trim().replace(/\s+-\s+(?:Google\s+)?Chrome$/i, "").trim(); }

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

function monitorStructureNodeIsPlacementExempt(nodeOrKey){
  const key=String(typeof nodeOrKey==="object"?nodeOrKey?.conversation_key:nodeOrKey||"");
  if(key&&Object.prototype.hasOwnProperty.call(monitorStructurePlacementExemptions,key)){
    return Boolean(monitorStructurePlacementExemptions[key]);
  }
  const node=typeof nodeOrKey==="object"&&nodeOrKey
    ?nodeOrKey
    :monitorStructureAvailableNodes().find(item=>String(item?.conversation_key||"")===key)||null;
  return Boolean(node?.exemption)||String(node?.role||"").toUpperCase()==="EXEMPT";
}

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

function rememberMonitorDesktopWindows(desktopId, windows) {

  const index = monitorDesktopState.desktopIds.indexOf(desktopId);

  if (index < 0) return;

  const now = Date.now();

  let changed = false;

  for (const item of Array.isArray(windows) ? windows : []) {
    const wallpaperDataUri = String(item?.wallpaperDataUri || "");
    if (wallpaperDataUri.startsWith("data:image/")) {
      monitorRememberWallpaperEntry(monitorWallpaperActuals, desktopId, wallpaperDataUri, MONITOR_WALLPAPER_ACTUAL_LIMIT);
      monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, wallpaperDataUri, MONITOR_WALLPAPER_CACHE_LIMIT);
    }

    const hwnd = String(item?.hwnd || "").trim();

    if (!/^\d+$/.test(hwnd) || hwnd === "0") continue;

    const previous = monitorWindowDesktopLocations.get(hwnd);

    const sameDesktop = previous?.desktopId === desktopId;

    const frozenDataUri = String(item?.frozenDataUri || previous?.frozenDataUri || "");
    const frozenAt = frozenDataUri ? Number(item?.frozenAt || previous?.frozenAt || now) : 0;
    const next = { hwnd, title: String(item?.title || ""), className: String(item?.className || ""), desktopId, desktop: index + 1, left: Number(item?.left) || 0, top: Number(item?.top) || 0, width: Number(item?.width) || 0, height: Number(item?.height) || 0, z: Number(item?.z) || 0, iconic: Boolean(item?.iconic), visible: Boolean(item?.visible), frozenDataUri, frozenAt, at: now, desktopEnteredAt: sameDesktop ? Number(previous?.desktopEnteredAt || previous?.at || now) : now };

    // Preserve the last confirmed conversation identity across transient title/identity lookup churn.

    // A successful native identity lookup below may replace this value with the current key.

    if (previous?.conversationKey && now - Number(previous?.identityAt || 0) < MONITOR_WINDOW_LOCATION_TTL_MS) {

      next.conversationKey = previous.conversationKey; next.identityAt = previous.identityAt;

      next.identityTitle = previous.identityTitle || "";

      next.nonChatSince = Number(monitorNonChatStartedByHwnd.get(hwnd) || previous.nonChatSince || 0);

    }

    if (!previous || previous.desktop !== next.desktop || previous.title !== next.title || previous.desktopId !== next.desktopId || Boolean(previous?.iconic) !== Boolean(next.iconic) || Boolean(previous?.visible) !== Boolean(next.visible)) changed = true;

    monitorWindowDesktopLocations.set(hwnd, next);

    if (!monitorIsOwnWindowTitle(next.title)) refreshMonitorWindowIdentity(hwnd);

  }

  for (const [hwnd, location] of monitorWindowDesktopLocations) {

    if (now - Number(location?.at || 0) > MONITOR_WINDOW_LOCATION_TTL_MS) { monitorWindowDesktopLocations.delete(hwnd); changed = true; }

  }

  if (changed && monitorLastAiState) renderWorkers(monitorLastAiState);

}

function monitorHwndHasOpenChatEndpoint(hwnd) {

  const key=String(hwnd||"").trim(), state=monitorLastAiState;

  if(!key||!state)return false;

  return (Array.isArray(state?.endpoints)?state.endpoints:[]).some((ep)=>{

    if(String(ep?.presence_state||"").toUpperCase()!=="OPEN")return false;

    if(!["GOOGLE","NAVER"].includes(String(ep?.profile_id||"").toUpperCase()))return false;

    const explicit=endpointOsWindowHandle(ep); if(explicit&&explicit===key)return true;

    const bound=monitorStableNodeForEndpoint(ep); return String(bound?.hwnd||"").trim()===key;

  });

}

async function refreshMonitorWindowIdentity(hwnd) {

  const current = monitorWindowDesktopLocations.get(String(hwnd)); if (!current) return;

  if (current.conversationKey && !Number(current.nonChatSince || 0)

      && String(current.identityTitle || "") === String(current.title || "")

      && Date.now() - Number(current.identityAt || 0) < MONITOR_WINDOW_IDENTITY_TTL_MS) return;

  if (monitorWindowIdentityInflight.has(String(hwnd))) return;

  monitorWindowIdentityInflight.add(String(hwnd));

  try {

    const result = await monitorNative({ type: "getChromeConversationIdentity", hwnd: String(hwnd) }).catch(() => null);

    const latest = monitorWindowDesktopLocations.get(String(hwnd)); if (!latest) return;

    const key = String(result?.conversationKey || "").trim(); const previousKey = String(latest.conversationKey || "");

    // Native lookup failure is transient; an explicit successful non-ChatGPT URL starts a grace timer.

    if (key) {

      latest.conversationKey = key;

      latest.identityAt = Date.now();

      latest.identityTitle = String(latest.title || "");

      latest.nonChatSince = 0;

      monitorNonChatStartedByHwnd.delete(String(hwnd));

    } else if (result?.ok === true && previousKey) {

      if (monitorHwndHasOpenChatEndpoint(hwnd)) {

        monitorNonChatStartedByHwnd.delete(String(hwnd));

        latest.nonChatSince = 0;

        latest.identityAt = Date.now();

        latest.identityTitle = String(latest.title || "");

      } else {

        const started = Number(monitorNonChatStartedByHwnd.get(String(hwnd)) || latest.nonChatSince || 0) || Date.now();

        monitorNonChatStartedByHwnd.set(String(hwnd), started);

        latest.nonChatSince = started;

        latest.identityAt = Date.now();

        latest.identityTitle = String(latest.title || "");

        const wait = Math.max(0, MONITOR_NON_CHAT_GRACE_MS - (Date.now() - started));

        setTimeout(() => { if (monitorLastAiState) renderWorkers(monitorLastAiState); }, wait + 40);

      }

    } else if (result?.ok === true) {

      monitorNonChatStartedByHwnd.delete(String(hwnd));

      latest.nonChatSince = 0;

      latest.identityAt = Date.now();

      latest.identityTitle = String(latest.title || "");

    } else if (previousKey) {

      latest.identityAt = Math.max(Number(latest.identityAt || 0), Date.now() - MONITOR_WINDOW_IDENTITY_TTL_MS + 250);

    }

    monitorWindowDesktopLocations.set(String(hwnd), latest);

    if ((key && key !== previousKey) && monitorLastAiState) renderWorkers(monitorLastAiState);

  } finally { monitorWindowIdentityInflight.delete(String(hwnd)); }

}

async function refreshMonitorIdentityIndex(state, force = false) {
  const now = Date.now();
  if (!force && now - monitorIdentityIndexRefreshAt < MONITOR_IDENTITY_INDEX_REFRESH_MS) return false;
  if (monitorIdentityIndexInflight) return monitorIdentityIndexInflight;

  const openEndpoints = (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((ep) =>
    String(ep?.presence_state || "").toUpperCase() === "OPEN"
    && ["GOOGLE", "NAVER"].includes(String(ep?.profile_id || "").toUpperCase())
  );
  const bctActiveNodes = (Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [])
    .filter((node) => node?.active === true && String(node?.instanceState || "").toUpperCase() === "OPEN");
  if ((!openEndpoints.length && !bctActiveNodes.length) || !monitorDesktopState.desktopIds.length) return false;

  const wanted = new Set([
    ...openEndpoints.map((ep) => String(ep?.conversation_key || "").trim()),
    ...bctActiveNodes.map((node) => String(node?.conversationKey || "").trim()),
  ].filter(Boolean));
  if (!wanted.size) return false;

  const renderSignature = (location) => [
    String(location?.conversationKey || ""),
    String(location?.desktopId || ""),
    Number(location?.desktop || 0),
    String(location?.title || ""),
    String(location?.className || ""),
    Number(location?.left || 0),
    Number(location?.top || 0),
    Number(location?.width || 0),
    Number(location?.height || 0),
    Number(location?.z || 0),
    Boolean(location?.iconic),
    Boolean(location?.visible),
  ].join("|");

  const job = (async () => {
    let projectionChanged = false;
    for (let i = 0; i < monitorDesktopState.desktopIds.length; i += 1) {
      const desktopId = monitorDesktopState.desktopIds[i];
      const snapshot = await monitorNativeWithTimeout({ type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: monitorDesktopState.hostWindowHwnd, includeMonitorWindows: true }, 2500).catch(() => null);
      const windows = Array.isArray(snapshot?.windows) ? snapshot.windows : [];
      await Promise.all(windows.filter((item) => String(item?.className || "") === "Chrome_WidgetWin_1").map(async (item) => {
        const hwnd = String(item?.hwnd || "").trim();
        if (!/^\d+$/.test(hwnd) || hwnd === "0") return;

        const previous = monitorWindowDesktopLocations.get(hwnd);
        const nextLocation = {
          ...(previous || {}), hwnd, title: String(item?.title || previous?.title || ""),
          className: "Chrome_WidgetWin_1", desktopId, desktop: i + 1,
          left: Number(item?.left ?? previous?.left) || 0, top: Number(item?.top ?? previous?.top) || 0,
          width: Number(item?.width ?? previous?.width) || 0, height: Number(item?.height ?? previous?.height) || 0,
          z: Number(item?.z ?? previous?.z) || 0, iconic: Boolean(item?.iconic), visible: Boolean(item?.visible), at: now,
          desktopEnteredAt: previous?.desktopEnteredAt || now
        };
        if (renderSignature(previous) !== renderSignature(nextLocation)) projectionChanged = true;
        monitorWindowDesktopLocations.set(hwnd, nextLocation);

        const identity = await monitorNativeWithTimeout({ type: "getChromeConversationIdentity", hwnd }, 2500).catch(() => null);
        const key = String(identity?.conversationKey || "").trim();
        if (!wanted.has(key)) {
          const latest = monitorWindowDesktopLocations.get(hwnd) || {};
          if (latest.conversationKey || latest.identityAt) {
            monitorWindowDesktopLocations.set(hwnd, {
              ...latest, identityAt: now, conversationKey: "", identityTitle: "", nonChatSince: Date.now(),
            });
            projectionChanged = true;
          }
          return;
        }

        const latest = monitorWindowDesktopLocations.get(hwnd) || {};
        const nextIdentity = {
          ...latest,
          identityAt: now,
          conversationKey: key,
          identityTitle: String(item?.title || latest?.title || ""),
          nonChatSince: 0
        };
        if (
          String(latest?.conversationKey || "") !== key
          || String(latest?.identityTitle || "") !== String(nextIdentity.identityTitle || "")
          || Number(latest?.nonChatSince || 0) !== 0
        ) projectionChanged = true;
        monitorWindowDesktopLocations.set(hwnd, nextIdentity);
      }));
    }

    monitorIdentityIndexRefreshAt = Date.now();
    refreshMonitorBctCurrentSessionWindowHwnd();
    if (projectionChanged && monitorLastAiState) renderWorkers(monitorLastAiState);
    return projectionChanged;
  })().finally(() => { monitorIdentityIndexInflight = null; });

  monitorIdentityIndexInflight = job;
  return job;
}


function monitorOpenEndpointsForConversation(state, conversationKey) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorOpenEndpointsForConversation"].apply(this, arguments); }

function monitorFreshNativeLocations(conversationKey, now = Date.now()) {

  const key = String(conversationKey || "").trim();

  if (!key) return [];

  return [...monitorWindowDesktopLocations.values()].filter((location) => {

    if (String(location?.conversationKey || "").trim() !== key) return false;

    if (!/^\d+$/.test(String(location?.hwnd || "")) || String(location?.hwnd) === "0") return false;

    const observedAt = Number(location?.at || 0), identityAt = Number(location?.identityAt || 0);

    return observedAt > 0 && now - observedAt <= MONITOR_WINDOW_LOCATION_TTL_MS

      && identityAt > 0 && now - identityAt <= MONITOR_WINDOW_LOCATION_TTL_MS;

  });

}

function monitorEndpointInstanceId(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointInstanceId"].apply(this, arguments); }

function monitorEndpointGeometry(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointGeometry"].apply(this, arguments); }
function monitorLocationForEndpoint(endpoint, now = Date.now()) {

  // Current native conversation identity is authoritative for physical placement.

  // Stored bindings are continuity fallback only when native identity is temporarily unavailable.

  const conversationKey = String(endpoint?.conversation_key || "").trim();

  const exactLocations = monitorFreshNativeLocations(conversationKey, now);

  const bound = monitorStableNodeForEndpoint(endpoint);

  if (!exactLocations.length && bound?.hwnd) {

    const exactBound = monitorWindowDesktopLocations.get(String(bound.hwnd));

    if (exactBound && now - Number(exactBound.at || 0) <= MONITOR_WINDOW_LOCATION_TTL_MS

        && !Number(exactBound.nonChatSince || 0)) return exactBound;

  }

  // Geometry is only a fallback because identical tiled windows can exist on different desktops.

  const duplicateIndex = Number(endpoint?.metadata?.duplicate_instance_index || 0);

  if (exactLocations.length > 1 && Number.isInteger(duplicateIndex) && duplicateIndex > 0 && duplicateIndex <= exactLocations.length) {

    const orderedExact = [...exactLocations].sort((a,b) => (Number(a.desktop)-Number(b.desktop)) || (Number(a.top)-Number(b.top)) || (Number(a.left)-Number(b.left)) || String(a.hwnd).localeCompare(String(b.hwnd)));

    return orderedExact[duplicateIndex - 1] || null;

  }

  // A single fresh native conversation match is authoritative even if ACT still carries an old HWND.

  if (exactLocations.length === 1) return exactLocations[0];

  const allLocations = [...monitorWindowDesktopLocations.values()].filter((location) => {

    if (!/^\d+$/.test(String(location?.hwnd || "")) || String(location?.hwnd) === "0") return false;

    const observedAt = Number(location?.at || 0);

    return observedAt > 0 && now - observedAt <= MONITOR_WINDOW_LOCATION_TTL_MS;

  });

  if (!allLocations.length) return null;

  const hwnd = endpointOsWindowHandle(endpoint);

  if (hwnd) {

    const exactHwnd = exactLocations.find((x)=>String(x.hwnd)===hwnd);

    if (exactHwnd) return exactHwnd;

    if (!exactLocations.length) return allLocations.find((x)=>String(x.hwnd)===hwnd) || null;

  }

  const candidates = exactLocations.length > 1 ? exactLocations : allLocations;

  const g = monitorEndpointGeometry(endpoint);

  if (![g.left,g.top,g.width,g.height].every(Number.isFinite)) return null;

  const ranked = candidates.map((x)=>({x, score:Math.abs(Number(x.left)-g.left)+Math.abs(Number(x.top)-g.top)+Math.abs(Number(x.width)-g.width)+Math.abs(Number(x.height)-g.height)})).sort((a,b)=>a.score-b.score);

  if (!ranked[0]) return null;

  if (ranked[0].score <= 12 && (ranked.length === 1 || ranked[0].score < ranked[1].score)) return ranked[0].x;

  return ranked.length===1 || ranked[0].score + 24 < ranked[1].score ? ranked[0].x : null;

}

function monitorExactConversationWindow(conversationKey, state, now = Date.now(), preferredEndpoint = null) {

  const key = String(conversationKey || "").trim();

  if (!key) return { endpoint: null, location: null, reason: "MISSING_CONVERSATION_KEY" };

  const endpoints = monitorOpenEndpointsForConversation(state, key);

  const endpoint = preferredEndpoint || (endpoints.length === 1 ? endpoints[0] : null);

  if (!endpoint) return { endpoint: null, location: null, reason: endpoints.length ? "AMBIGUOUS_ENDPOINT" : "MISSING_ENDPOINT" };

  const location = monitorLocationForEndpoint(endpoint, now);

  if (!location) return { endpoint, location: null, reason: "MISSING_OR_AMBIGUOUS_HWND" };

  const desktopId = String(location?.desktopId || "").trim();

  const desktopIndex = monitorDesktopState.desktopIds.indexOf(desktopId);

  if (desktopIndex < 0) return { endpoint, location: null, reason: "UNKNOWN_DESKTOP" };

  return { endpoint, location: { ...location, desktop: desktopIndex + 1 }, reason: "" };

}

// Physical placement never allocates or infers official node numbers; ACT owns numbering.
// Legacy Dn-x labels are read only.  New ACT labels are global Nx identities;
// the current Dn position is derived independently from the desktop id.
function monitorNodeIdentityParts(label, desktopId = "") {
  const value = String(label || "").trim().toUpperCase();
  const legacy = /^D(\d+)-(\d+)$/.exec(value);
  const display = /^N(\d+)\s*·\s*D(\d+)$/.exec(value);
  const global = /^N(\d+)$/.exec(value);
  const nodeNumber = Number(global?.[1] || display?.[1] || legacy?.[2] || 0) || null;
  let desktop = Number(display?.[2] || legacy?.[1] || 0) || null;
  const id = String(desktopId || "").trim();
  if (id) {
    const index = Array.isArray(monitorDesktopState?.desktopIds) ? monitorDesktopState.desktopIds.indexOf(id) : -1;
    if (index >= 0) desktop = index + 1;
  }
  return {
    nodeNumber,
    desktop,
    canonicalLabel: nodeNumber ? `N${nodeNumber}` : "",
    displayLabel: nodeNumber ? `N${nodeNumber}${desktop ? ` · D${desktop}` : ""}` : ""
  };
}

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

function monitorEndpointLocation(worker, state) { return monitorCanonicalPhysicalLocation(worker, state)?.location || null; }

function resolveStableMonitorLocation(worker, state) { return monitorCanonicalPhysicalLocation(worker, state)?.label || "UNMAPPED"; }

// Node numbering is ACT-authoritative. Monitor only projects ACT-assigned labels.

function monitorActBrowserNode(worker, state = monitorLastAiState) {

  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return null;

  const key=monitorStableBrowserNodeKey(worker);

  const actNodes=Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[];

  if(key){const direct=actNodes.find((node)=>String(node?.browser_node_id||"")===key);if(direct&&String(direct?.identity_authority||"")==="ACT_TAB_CHAT")return direct;}

  return null;

}

function monitorStableBrowserNodeKey(worker) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorStableBrowserNodeKey"].apply(this, arguments); }

function monitorStableNodeSlotRecord(worker,key,state=monitorLastAiState) {

  const endpoint=worker?.__endpoint||endpointForMonitorWorker(worker,state)||null;

  // Canonical node identity is the exact tab_id + conversation_key pair.

  const tabKey=monitorStableBrowserNodeKey({...worker,__endpoint:endpoint});

  if(tabKey){

    const row=monitorActBrowserNode({...worker,__endpoint:endpoint},state);

    if(!row)return null;

    const parts=monitorNodeIdentityParts(row?.node_label,row?.desktop_id);

    if(!parts.nodeNumber)return null;

    const desktop=parts.desktop,slot=parts.nodeNumber;

    return {desktopId:String(row?.desktop_id||""),desktop,slot,updatedAt:Date.parse(String(row?.updated_at||""))||0,nodeLabel:parts.displayLabel,authority:"ACT_TAB"};

  }

  const row=monitorActBrowserNode(worker,state); if(!row)return null;

  const parts=monitorNodeIdentityParts(row?.node_label,row?.desktop_id);

  if(!parts.nodeNumber)return null;

  const desktop=parts.desktop,slot=parts.nodeNumber;

  return {desktopId:String(row?.desktop_id||""),desktop,slot,updatedAt:Date.parse(String(row?.updated_at||""))||0,nodeLabel:parts.displayLabel,authority:"ACT"};

}

function monitorStableNodeSlot(worker,state,liveUsedSlots=null,acceptedCurrentKeys=null) {

  return monitorStableNodeSlotRecord(worker,monitorStableBrowserNodeKey(worker),state);

}

function monitorBrowserDisplaySlots(workers,state) { return monitorListDisplaySlots(workers,state); }

function monitorWindowGroupKeyForWorker(worker,state) {

  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return "";

  const projected=monitorActBrowserNode(worker,state);

  const hwnd=String(projected?.hwnd||"").trim();

  const desktopId=String(projected?.desktop_id||"").trim();

  if(String(projected?.location_authority||"")!=="ACT_NATIVE_OBSERVER"||!desktopId) return "";

  return /^\d+$/.test(hwnd)&&hwnd!=="0" ? `desktop:${desktopId}:hwnd:${hwnd}` : "";

}

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

// The desktop-label summary is reserved for minimized ChatGPT windows. Open
// ChatGPT windows render their BCT/RCC number directly on their thumbnail.
function monitorMinimizedNodeSlotsByDesktop(state = monitorLastAiState) {
  return monitorMinimizedNodeBadgeContract?.slotsByDesktop?.({
    locations: monitorWindowDesktopLocations,
    numbersForHwnd: (hwnd) => monitorBadgeNodeNumbersForHwnd(hwnd, state),
  }) || new Map();
}

function monitorMinimizedNodeTokensByDesktop(state = monitorLastAiState) {
  return monitorMinimizedNodeBadgeContract?.tokensByDesktop?.({
    locations: monitorWindowDesktopLocations,
    tokensForHwnd: (hwnd) => monitorBadgeNodeNumbersForHwnd(hwnd, state, { includeTabIds: true }),
  }) || new Map();
}

function profileForMonitorWorker(worker, state) { return globalThis.MonitorDomainAPIs["node-identity"]["profileForMonitorWorker"].apply(this, arguments); }

function endpointForMonitorWorker(worker, state) {

  if (worker?.__endpoint) return worker.__endpoint;

  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];

  const conversationKey = String(worker?.conversation_key || "").trim();

  if (conversationKey) {

    const byConversation = endpoints.filter((endpoint) =>

      String(endpoint?.conversation_key || "").trim() === conversationKey

      && String(endpoint?.presence_state || "").toUpperCase() === "OPEN"

    );

    return byConversation.length === 1 ? byConversation[0] : null;

  }

  const profileId = String(worker?.profile_id || "").toUpperCase();

  const role = String(worker?.role || "").toUpperCase();

  return endpoints.find((endpoint) =>

    String(endpoint?.profile_id || "").toUpperCase() === profileId

    && String(endpoint?.bound_role || "").toUpperCase() === role

    && String(endpoint?.binding_state || "").toUpperCase() === "BOUND"

  ) || null;

}

function monitorEndpointWindowKey(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointWindowKey"].apply(this, arguments); }

function monitorEndpointNativeChatExpired(endpoint, now = Date.now()) {

  const location = monitorLocationForEndpoint(endpoint, now);

  const since = Number(location?.nonChatSince || 0);

  return since > 0 && now - since >= MONITOR_NON_CHAT_GRACE_MS;

}

function monitorEndpointIsMinimized(endpoint, worker = null, state = null) {

  const resolvedLocation = worker && state ? monitorEndpointLocation(worker, state) : null;

  const resolvedHwnd = worker && state ? monitorResolvedWorkerHwnd(worker, state, resolvedLocation) : "";

  const hwnd = String(resolvedHwnd || endpointOsWindowHandle(endpoint) || "").trim();

  const live = hwnd ? monitorWindowDesktopLocations.get(hwnd) : null;

  if (live && typeof live.iconic === "boolean") return live.iconic;

  return String(endpoint?.metadata?.window_bounds?.state || "").toLowerCase() === "minimized";

}

function monitorWorkersForState(state) {
  const workers = Array.isArray(state?.workers) ? state.workers : [];
  const endpoints = Array.isArray(state?.endpoints) ? state.endpoints : [];

  const workerByConversationProfile = new Map();
  for (const worker of workers) {
    const key = String(worker?.conversation_key || "").trim();
    const profileId = String(worker?.profile_id || "").toUpperCase();
    if (key && profileId) workerByConversationProfile.set(`${key}\u0000${profileId}`, worker);
  }

  const members = Array.isArray(state?.organization?.members) ? state.organization.members : [];
  const liveMembers = members.filter((member) => member?.present === true && (member?.role || member?.exemption));
  const memberByConversation = new Map(
    members.map((member) => [String(member?.conversation_key || "").trim(), member]),
  );

  const activeRoleSlots = Array.isArray(state?.organization?.role_slots) ? state.organization.role_slots : [];
  const liveRoleByConversation = new Map(
    activeRoleSlots
      .filter((slot) => String(slot?.state || "").toUpperCase() === "ACTIVE"
        && ["ORCHESTRATOR", "COORDINATOR_1", "COORDINATOR_2"].includes(String(slot?.slot_id || "").toUpperCase()))
      .map((slot) => [String(slot.conversation_key || "").trim(), String(slot.slot_id || "").toUpperCase()]),
  );

  const liveBrowserProfileInstances = new Map(
    (Array.isArray(state?.profiles) ? state.profiles : [])
      .filter((profile) => ["GOOGLE", "NAVER"].includes(String(profile?.profile_id || "").toUpperCase())
        && String(profile?.status || "").toLowerCase() === "available")
      .map((profile) => [String(profile?.profile_id || "").toUpperCase(), String(profile?.transport_instance_id || "").trim()]),
  );

  const openBrowserEndpoints = endpoints.filter((endpoint) => {
    const profileId = String(endpoint?.profile_id || "").toUpperCase();
    const liveInstanceId = liveBrowserProfileInstances.get(profileId) || "";
    const endpointInstanceId = String(endpoint?.transport_instance_id || "").trim();
    return String(endpoint?.presence_state || "").toUpperCase() === "OPEN"
      && ["GOOGLE", "NAVER"].includes(profileId)
      && Boolean(liveInstanceId)
      && endpointInstanceId === liveInstanceId
      && Boolean(String(endpoint?.conversation_key || "").trim())
      && !monitorEndpointNativeChatExpired(endpoint);
  });

  const endpointsByWindow = new Map();
  for (const endpoint of openBrowserEndpoints) {
    const location = monitorLocationForEndpoint(endpoint);
    const hwnd = String(location?.hwnd || endpointOsWindowHandle(endpoint) || "").trim();
    const trustedWindowKey = monitorTrustedPhysicalWindowKey(endpoint, location);
    // Never infer TAB from transport identity or matching geometry alone. When the
    // physical HWND is not trusted, keep the endpoint separate as its own browser row.
    const windowKey = trustedWindowKey
      || `ENDPOINT:${String(endpoint?.profile_id || "")}:${String(endpoint?.conversation_key || "")}:${String(endpoint?.tab_id ?? "")}`;
    if (!endpointsByWindow.has(windowKey)) endpointsByWindow.set(windowKey, []);
    endpointsByWindow.get(windowKey).push({ ep: endpoint, location, hwnd });
  }

  const browserRows = [];
  for (const [windowKey, groupEntries] of endpointsByWindow) {
    groupEntries.sort((a, b) =>
      (Number(b.ep?.metadata?.tab_active === true) - Number(a.ep?.metadata?.tab_active === true))
      || (Number(a.ep?.tab_id || 0) - Number(b.ep?.tab_id || 0)));
    const hasNativeHwnd = groupEntries.some((entry) => /^\d+$/.test(String(entry.hwnd || "")));
    groupEntries.forEach((entry, index) => {
      const endpoint = entry.ep;
      const key = String(endpoint?.conversation_key || "").trim();
      const matched = workerByConversationProfile.get(
        `${key}\u0000${String(endpoint?.profile_id || "").toUpperCase()}`,
      ) || {};
      const member = memberByConversation.get(key) || {};
      const exempt = Boolean(member?.exemption);
      const previous = groupEntries[index - 1];
      const kind = hasNativeHwnd
        && index > 0
        && String(previous?.hwnd || "") === String(entry.hwnd || "")
        && entry.hwnd
        ? "TAB"
        : "WIN";
      const instanceKey = entry.hwnd ? `HWND:${entry.hwnd}` : monitorEndpointInstanceId(endpoint);
      browserRows.push({
        ...matched,
        profile_id: String(endpoint?.profile_id || matched?.profile_id || "").toUpperCase(),
        role: exempt
          ? "EXEMPT"
          : (liveRoleByConversation.get(key) || String(member?.role || "").toUpperCase() || "WORKER"),
        exemption: member?.exemption || null,
        organization_member: memberByConversation.has(key),
        conversation_key: key,
        title: endpoint?.title || matched?.title || "",
        status: "available",
        connection_status: "connected",
        __endpoint: endpoint,
        __browser_instance_id: monitorEndpointInstanceId(endpoint),
        __window_key: windowKey,
        __kind: kind,
        __display_key: `${kind}:${instanceKey}:${String(endpoint?.tab_id || index)}`,
      });
    });
  }

  const liveKeys = new Set(
    liveMembers.map((member) => String(member.conversation_key || "").trim()).filter(Boolean),
  );
  const nonBrowser = workers.filter((worker) =>
    !["GOOGLE", "NAVER"].includes(String(worker?.profile_id || "").toUpperCase())
    && !liveKeys.has(String(worker?.conversation_key || "").trim()));

  return [...nonBrowser, ...browserRows, ...monitorLlmWorkersFromState(state), ...monitorCodexWorkersFromState(state, browserRows)];
}

// ACT state payloads are immutable snapshots in this UI. Rendering used to rebuild
// the same projection for every storage/identity callback, multiplying callback bursts.
const monitorConversationProjectionController = globalThis.MonitorConversationProjectionController.create({build: state => monitorWorkersForState(state)});

function monitorWorkersProjectionForState(state) { return monitorConversationProjectionController.project(state); }

function endpointRegistryIsAuthoritative(worker, state) {

  const source = String(profileForMonitorWorker(worker, state)?.metadata?.presence_source || "").toLowerCase();

  return source === "endpoint_registry";

}

function endpointOsWindowHandle(endpoint) {

  const metadata = endpoint?.metadata && typeof endpoint.metadata === "object" ? endpoint.metadata : {};

  const raw = endpoint?.hwnd ?? endpoint?.os_hwnd ?? metadata.hwnd ?? metadata.os_hwnd ?? metadata.window_handle;

  const value = String(raw ?? "").trim();

  return /^\d+$/.test(value) && value !== "0" ? value : "";

}

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

function monitorResolvedWorkerHwnd(worker, state, resolvedLocation = null) {

  const canonical = monitorCanonicalPhysicalLocation(worker, state);

  const value = String(canonical?.hwnd || resolvedLocation?.hwnd || "").trim();

  return /^\d+$/.test(value) && value !== "0" ? value : "";

}

const MONITOR_PERSISTENT_ROLE_CLASSES = {

  ORCHESTRATOR: "monitor-role-orchestrator",

  COORDINATOR_1: "monitor-role-coordinator-1",

  COORDINATOR_2: "monitor-role-coordinator-2",

};

const monitorRoleByHwnd = new Map();

const MONITOR_SYSTEM_NODE_STORAGE_KEY = "desktopWindowMonitorSystemNodesV1";

const monitorSystemNodeKeys = new Set((()=>{ try { const v=JSON.parse(localStorage.getItem(MONITOR_SYSTEM_NODE_STORAGE_KEY)||"[]"); return Array.isArray(v)?v:[]; } catch (_) { return []; } })());

function monitorPersistSystemNodes(){ try { localStorage.setItem(MONITOR_SYSTEM_NODE_STORAGE_KEY, JSON.stringify([...monitorSystemNodeKeys])); } catch (_) {} }

function monitorMarkSystemNode(conversationKey){ const key=String(conversationKey||"").trim(); if(!key||monitorSystemNodeKeys.has(key))return; monitorSystemNodeKeys.add(key); monitorPersistSystemNodes(); }

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

function monitorDirectConversationGenerationState(conversationKey, now = Date.now()) {
  return monitorNodeGenerationAPI.directConversationGenerationState(conversationKey, now);
}

function monitorDirectEndpointUserAttention(endpoint) {
  return monitorNodeGenerationAPI.directUserAttention(endpoint);
}

function monitorUserAttentionVisualDetail(attentionRaw) {
  const kind=String(attentionRaw?.kind||"").trim().toUpperCase();
  if(kind==="RETRY_REQUIRED") return {warning:true,tone:"failure",label:String(attentionRaw?.label||"다시 시도 필요")};
  if(["NEW_CHAT_REQUIRED","RECOVERY_REQUIRED"].includes(kind)) return {warning:true,tone:"review",label:String(attentionRaw?.label||"사용자 조치 필요")};
  return null;
}

function monitorConversationUserAttentionDetail(conversationKey,state=monitorLastAiState) {
  const key=String(conversationKey||"").trim();
  if(!key)return null;
  const direct=monitorDirectGenerationByConversation.get(key)?.userAttention||null;
  const endpoints=Array.isArray(state?.endpoints)?state.endpoints:[];
  const endpoint=endpoints.find((item)=>String(item?.presence_state||"").toUpperCase()==="OPEN"&&String(item?.conversation_key||"").trim()===key)
    ||endpoints.find((item)=>String(item?.conversation_key||"").trim()===key)
    ||null;
  const raw=direct||endpoint?.telemetry?.user_attention||endpoint?.metadata?.user_attention||endpoint?.metadata?.telemetry?.user_attention||null;
  return monitorUserAttentionVisualDetail(raw);
}

function monitorHwndUserAttentionDetail(hwnd,state=monitorLastAiState) {
  const conversationKey=monitorVisualConversationForHwnd(String(hwnd||""),state);
  return monitorConversationUserAttentionDetail(conversationKey,state);
}

const MONITOR_SHARED_USER_ATTENTION_PREFIX="__DWUA1__:";
function monitorEncodeSharedUserAttention(attentionCue,userAttention){
  const cue=String(attentionCue||"");
  const kind=String(userAttention?.kind||"").trim().toUpperCase();
  if(!["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(kind))return cue;
  const label=String(userAttention?.label||"사용자 조치 필요");
  return `${MONITOR_SHARED_USER_ATTENTION_PREFIX}${kind}|${encodeURIComponent(label)}`;
}
function monitorDecodeSharedGenerationAttention(row){
  const raw=String(row?.attentionCue||"");
  const directKind=String(row?.userAttention?.kind||"").trim().toUpperCase();
  if(["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(directKind)){
    return {attentionCue:raw.startsWith(MONITOR_SHARED_USER_ATTENTION_PREFIX)?"":raw,userAttention:{kind:directKind,label:String(row?.userAttention?.label||"사용자 조치 필요")}};
  }
  if(!raw.startsWith(MONITOR_SHARED_USER_ATTENTION_PREFIX))return {attentionCue:raw,userAttention:null};
  const encoded=raw.slice(MONITOR_SHARED_USER_ATTENTION_PREFIX.length), splitAt=encoded.indexOf("|");
  const kind=String(splitAt>=0?encoded.slice(0,splitAt):encoded).trim().toUpperCase();
  if(!["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(kind))return {attentionCue:raw,userAttention:null};
  let label="사용자 조치 필요";
  if(splitAt>=0){
    const rawLabel=encoded.slice(splitAt+1);
    try{label=decodeURIComponent(rawLabel)||label;}catch(_){label=rawLabel||label;}
  }
  return {attentionCue:"",userAttention:{kind,label}};
}

const MONITOR_COMPLETION_STABLE_MS = 1800;

const monitorCompletionAlertTimers = new Map();

function monitorCancelScheduledCompletionAlert(conversationKey) {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const timer=monitorCompletionAlertTimers.get(key); if(timer)clearTimeout(timer);

  monitorCompletionAlertTimers.delete(key);

}

function monitorScheduleChatCompletionAlert(conversationKey, attentionCue="", completionCue="general") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  monitorCancelScheduledCompletionAlert(key);

  const timer=setTimeout(()=>{

    monitorCompletionAlertTimers.delete(key);

    if(monitorDirectConversationGenerationState(key)===true)return;

    const live=(Array.isArray(monitorLastAiState?.endpoints)?monitorLastAiState.endpoints:[]).filter((endpoint)=>String(endpoint?.conversation_key||"").trim()===key&&String(endpoint?.presence_state||"").toUpperCase()==="OPEN");

    if(live.some((endpoint)=>monitorEndpointGenerationIsActive(endpoint)))return;

    monitorGenerationSeen.set(key,false);

    monitorCreateChatCompletionAlert(key,attentionCue,completionCue);

  },MONITOR_COMPLETION_STABLE_MS);

  monitorCompletionAlertTimers.set(key,timer);

}

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

let monitorChatNavigationRefreshTimer = 0;
const monitorChatNavigationPendingByTab = new Map();

function monitorBrowserWindowIdForEndpoint(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorBrowserWindowIdForEndpoint"].apply(this, arguments); }

function refreshMonitorBctCurrentSessionWindowHwnd() {
  const resolution = monitorWindowHwndContract?.resolve?.({
    nodes: monitorBctWindowNodesCache || [], locations: monitorWindowDesktopLocations, now: Date.now(),
  });
  const bindings = monitorWindowHwndContract?.retainCurrentSessionBindings?.({
    bindings: resolution?.bindings || [], previousBindings: [...monitorBctCurrentSessionWindowHwnd.values()],
    nodes: monitorBctWindowNodesCache || [], locations: monitorWindowDesktopLocations, now: Date.now(),
  }) || (resolution?.bindings || []);
  const next = new Map();
  for (const binding of bindings) {
    next.set(String(binding.lineage || ""), binding);
  }
  monitorBctCurrentSessionWindowHwnd = next;
  return resolution || null;
}

async function refreshMonitorBctBrowserWindowGeometry() {
  const ids = [...new Set((Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [])
    .map((node) => Number(node?.windowId)).filter(Number.isInteger))];
  const observedAt = Date.now();
  const rows = await Promise.all(ids.map(async (windowId) => {
    try {
      const [browserWindow, activeTabs] = await Promise.all([
        chrome.windows.get(windowId, { populate: false }),
        chrome.tabs.query({ windowId, active: true }),
      ]);
      const activeTab = Array.isArray(activeTabs) ? activeTabs[0] : null;
      return {
        windowId, observedAt,
        left: Number(browserWindow?.left), top: Number(browserWindow?.top),
        width: Number(browserWindow?.width), height: Number(browserWindow?.height),
        state: String(browserWindow?.state || "normal"), focused: browserWindow?.focused === true,
        // A minimized Chrome HWND is represented by Windows as a tiny icon
        // rectangle, so its restore bounds cannot be joined by geometry.  The
        // active tab title is read-only Chrome state used only for a unique
        // display projection in that minimized case.
        activeTabTitle: String(activeTab?.title || ""),
      };
    } catch (_) { return null; }
  }));
  monitorBctBrowserWindows = new Map(rows.filter(Boolean).map((row) => [String(row.windowId), row]));
  return monitorBctBrowserWindows;
}

function refreshMonitorBctDisplayWindowHwnd() {
  const display = monitorWindowHwndContract?.resolveDisplay?.({
    nodes: monitorBctWindowNodesCache || [], locations: monitorWindowDesktopLocations,
    browserWindows: monitorBctBrowserWindows, now: Date.now(),
  });
  monitorBctDisplayWindowHwnd = new Map((display?.bindings || []).map((binding) => [String(binding.lineage || ""), binding]));
  return display || null;
}

function monitorBctCurrentSessionHwnd(windowIdValue, instanceIdValue = "", sessionIdValue = "") {
  const windowId = String(windowIdValue ?? "").trim();
  const instanceId = String(instanceIdValue ?? "").trim();
  const sessionId = String(sessionIdValue ?? "").trim();
  if (!/^\d+$/.test(windowId) || windowId === "0") return "";
  if (instanceId && sessionId) {
    return String(monitorBctCurrentSessionWindowHwnd.get(`${instanceId}:${sessionId}:${windowId}`)?.hwnd || "");
  }
  const matches = [...monitorBctCurrentSessionWindowHwnd.values()]
    .filter((binding) => String(binding?.windowId || "") === windowId)
    .map((binding) => String(binding?.hwnd || ""))
    .filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0");
  return new Set(matches).size === 1 ? matches[0] : "";
}

function monitorBctDisplaySessionHwnd(windowIdValue, instanceIdValue = "", sessionIdValue = "") {
  const exact = monitorBctCurrentSessionHwnd(windowIdValue, instanceIdValue, sessionIdValue);
  if (exact) return exact;
  const windowId = String(windowIdValue ?? "").trim();
  const instanceId = String(instanceIdValue ?? "").trim();
  const sessionId = String(sessionIdValue ?? "").trim();
  if (!/^\d+$/.test(windowId) || windowId === "0") return "";
  if (instanceId && sessionId) {
    return String(monitorBctDisplayWindowHwnd.get(`${instanceId}:${sessionId}:${windowId}`)?.hwnd || "");
  }
  const matches = [...monitorBctDisplayWindowHwnd.values()]
    .filter((binding) => String(binding?.windowId || "") === windowId)
    .map((binding) => String(binding?.hwnd || ""))
    .filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0");
  return new Set(matches).size === 1 ? matches[0] : "";
}

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

function monitorDisplayHwndForBrowserWindowId(windowIdValue, state = monitorLastAiState, instanceIdValue = "", sessionIdValue = "") {
  return monitorHwndForBrowserWindowId(windowIdValue, state, instanceIdValue, sessionIdValue)
    || monitorBctDisplaySessionHwnd(windowIdValue, instanceIdValue, sessionIdValue);
}

function applyMonitorChatNavigationIdentity(message, state = monitorLastAiState) {
  const active = message?.active === true || String(message?.reason || "") === "tab-activated";
  if (!active) return { ok:true, changed:false, inactive:true };

  const conversationKey = String(message?.conversationKey || "").trim();
  const windowId = Number(message?.windowId);
  const tabId = Number(message?.tabId);
  const nodes = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [];
  // A tab without a conversation UUID is still a real observed `N?` entry.
  // Prefer its exact Chrome window/tab pair, so selecting it never guesses a
  // different unregistered tab in the same browser window.
  const selectedNode = nodes.find((node) =>
    Number(node?.windowId) === windowId && Number(node?.tabId) === tabId &&
    (!conversationKey || String(node?.conversationKey || "").trim() === conversationKey)
  ) || (conversationKey
    ? nodes.find((node) => String(node?.conversationKey || "").trim() === conversationKey)
    : null);
  if (selectedNode) {
    monitorNodePanelSelection.set(monitorBctNodeSelectionKey(selectedNode));
    // Chrome chose this tab; Monitor only mirrors that selection. Do not turn
    // it into a Monitor-window/desktop highlight or activate anything.
    monitorBctNodeHighlightedHwnd = "";
    syncMonitorBctNodeTargetHighlight();
    syncMonitorMinimizedNodeBadges(state);
    syncMonitorAllDesktopThumbnailNodeBadges();
  }
  if (!conversationKey) return { ok:true, changed:Boolean(selectedNode), transitional:!selectedNode };

  const hwnd = monitorHwndForBrowserWindowId(windowId, state);
  if (!hwnd) return { ok:false, mappingMiss:true };

  const location = monitorWindowDesktopLocations.get(hwnd);
  if (!location) return { ok:false, mappingMiss:true };

  const previousKey = String(location?.conversationKey || "");
  location.conversationKey = conversationKey;
  location.identityAt = Date.now();
  location.identityTitle = String(location?.title || "");
  location.nonChatSince = 0;
  monitorNonChatStartedByHwnd.delete(hwnd);
  monitorWindowDesktopLocations.set(hwnd, location);

  const changed = previousKey !== conversationKey;
  if (changed && state) renderWorkers(state);
  return { ok:true, changed, hwnd };
}

const monitorBrowserVisualPendingWindowIds = new Set();
const monitorBrowserVisualTabsByWindow = new Map();
let monitorBrowserVisualRefreshTimer = 0;
let monitorBrowserVisualRefreshInFlight = false;
let monitorBrowserRosterRefreshPending = false;
const MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS = 120;

function applyMonitorBrowserVisualTabSnapshot(message) {
  const windowId = Number(message?.windowId);
  if (!Number.isInteger(windowId)) return false;

  // The background supplies the complete Chrome tab order. This is observation
  // only: it never selects, moves, closes, or otherwise changes a real tab.
  if (Array.isArray(message?.tabs)) {
    const tabs = new Map();
    for (const item of message.tabs) {
      const tabId = Number(item?.tabId);
      const tabIndex = Number(item?.tabIndex);
      if (!Number.isInteger(tabId) || tabId < 0 || !Number.isInteger(tabIndex) || tabIndex < 0) continue;
      tabs.set(tabId, { tabId, tabIndex });
    }
    monitorBrowserVisualTabsByWindow.set(windowId, tabs);
    return true;
  }

  const tabId = Number(message?.tabId);
  if (!Number.isInteger(tabId) || tabId < 0) return false;
  const tabs = monitorBrowserVisualTabsByWindow.get(windowId) || new Map();
  if (message?.tabRemoved === true) tabs.delete(tabId);
  else {
    const tabIndex = Number(message?.tabIndex);
    tabs.set(tabId, { tabId, tabIndex: Number.isInteger(tabIndex) && tabIndex >= 0 ? tabIndex : Number.MAX_SAFE_INTEGER });
  }
  monitorBrowserVisualTabsByWindow.set(windowId, tabs);
  return true;
}

function monitorBrowserVisualTabsForWindow(windowIdValue) {
  const windowId = Number(windowIdValue);
  const tabs = Number.isInteger(windowId) ? monitorBrowserVisualTabsByWindow.get(windowId) : null;
  return [...(tabs?.values?.() || [])].sort((left, right) =>
    Number(left?.tabIndex) - Number(right?.tabIndex) || Number(left?.tabId) - Number(right?.tabId));
}

function scheduleMonitorBrowserVisualRefresh(message) {
  const windowId = Number(message?.windowId);
  if (!Number.isInteger(windowId)) return;
  if (["window-created", "window-removed", "tab-created", "tab-removed", "tab-attached", "tab-detached", "tab-moved"].includes(String(message?.reason || ""))) {
    monitorBrowserRosterRefreshPending = true;
  }

  if (applyMonitorBrowserVisualTabSnapshot(message)) {
    // Preserve the existing pixels while their native refresh is queued; the
    // label order is known already and should not wait for Monitor focus.
    syncMonitorAllDesktopThumbnailNodeBadges();
  }
  monitorBrowserVisualPendingWindowIds.add(windowId);
  if (monitorBrowserVisualRefreshTimer || monitorBrowserVisualRefreshInFlight) return;
  monitorBrowserVisualRefreshTimer = setTimeout(() => {
    monitorBrowserVisualRefreshTimer = 0;
    void flushMonitorBrowserVisualRefresh();
  }, MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS);
}

async function flushMonitorBrowserVisualRefresh() {
  if (monitorBrowserVisualRefreshInFlight) return;
  monitorBrowserVisualRefreshInFlight = true;
  try {
    const windowIds = [...monitorBrowserVisualPendingWindowIds];
    monitorBrowserVisualPendingWindowIds.clear();
    if (!windowIds.length) return;
    const refreshRoster = monitorBrowserRosterRefreshPending;
    monitorBrowserRosterRefreshPending = false;

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
    if (!desktopIds.size) {
      if (refreshRoster) await refreshMonitorBctWindowNodes();
      return;
    }

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
    // A fresh desktop frame replaces its DOM layers. Re-project the same
    // browser snapshot after capture so a tab move cannot erase its node label.
    syncMonitorAllDesktopThumbnailNodeBadges();
    // Chrome creation/removal is an event, not a reason to poll or change focus.
    // Refresh exact RCC membership after the Native/Chrome visual reconciliation.
    if (refreshRoster) await refreshMonitorBctWindowNodes();
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

const monitorPopupTopologyPendingDesktopIds = new Set();
let monitorPopupTopologyRefreshTimer = 0;
let monitorPopupTopologyRefreshInFlight = false;
const MONITOR_POPUP_TOPOLOGY_REFRESH_DEBOUNCE_MS = 360;

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
      // RCC window_id/tab membership is a separate source from the legacy ACT
      // conversation state. Refresh it for this official Chrome navigation
      // event so node badges do not wait for the Monitor window to gain focus.
      await refreshMonitorBctWindowNodes();

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
      refreshMonitorBctCurrentSessionWindowHwnd();
      refreshMonitorBctDisplayWindowHwnd();
      syncMonitorAllDesktopThumbnailNodeBadges();
    } catch (error) {
      console.warn("DesktopWindow Monitor chat navigation refresh failed", {
        tabIds: pending.map((item) => Number(item?.tabId)).filter(Number.isInteger),
        error: error?.message || String(error)
      });
    }
  }, 120);
}

chrome.runtime.onMessage.addListener((message, sender) => {

  if (message?.type === "desktop-window-user-click") { monitorApplyDirectUserClick(message, sender); return; }
  if (message?.type === "monitor-popup-topology-changed") {
    if (!monitorDesktopState.hostDesktopId || monitorDesktopState.hostDesktopId !== monitorDesktopState.currentDesktopId) return;
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

  if(monitorLastAiState){

    const endpoints=Array.isArray(monitorLastAiState?.endpoints)?monitorLastAiState.endpoints:[];
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

    if (monitorLastAiState) renderWorkers(monitorLastAiState);

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

async function monitorPublishSharedRuntime(kind, conversationKey, payload = {}, at = Date.now()) {

  const key=String(conversationKey||"").trim(); if(!key)return null;

  try { return await monitorNative({type:"setSharedMonitorRuntime",kind,conversationKey:key,at:String(Number(at)||Date.now()),...payload}); } catch (_) { return null; }

}

async function monitorPublishSharedInstance(reason = "event") {

  const result = await monitorNative({type:"getSharedMonitorRuntime"}).catch(() => null);

  if (!result?.ok) return;

  const hostProfile=String(result.hostProfile||"").toUpperCase();

  if (!["GOOGLE","NAVER"].includes(hostProfile)) return;

  const hwnd=String(monitorDesktopState.hostWindowHwnd||"").trim();

  const instanceId = /^\d+$/.test(hwnd) && hwnd !== "0" ? hwnd : String(document.title||"MONITOR").trim();

  // Runtime presence is one current record per browser profile. Using the
  // transient HWND in the key left old rows behind after an extension reload.
  await monitorPublishSharedRuntime("alert",`${MONITOR_SHARED_INSTANCE_PREFIX}${hostProfile}`,{symbol:"",tone:"monitor-instance",label:JSON.stringify({profile:hostProfile,build_id:MONITOR_RUNTIME_BUILD_ID,manifest_version:chrome.runtime.getManifest().version,reload_token:String(monitorReloadToken||""),monitor_title:document.title,hwnd,reason:String(reason||"event"),thumbnail_initial:{stage:String(monitorInitialThumbStage||"unknown"),error:String(monitorInitialThumbError||"").slice(0,160),background_done:monitorInitialThumbBatchDone===true,windows_done:monitorInitialWindowBatchDone===true,desktop_ids:[...(monitorDesktopState?.desktopIds||[])].map(String)},thumbnail_background:monitorThumbnailBackgroundRuntimeDiagnostics(),thumbnail_native_trace:globalThis.MonitorNativeTrace?.summary?.("getDesktopVisualSnapshot")||null,thumbnail_projection:monitorThumbnailProjectionRuntimeDiagnostics(),seen_at_ms:Date.now()})});

}

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

function monitorPersistentRoleClass(role) {

  return MONITOR_PERSISTENT_ROLE_CLASSES[String(role || "").toUpperCase()] || "";

}

function monitorIsActivelyWorking(work) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorIsActivelyWorking"].apply(this, arguments); }

function monitorIsPostWorkWaiting(work, conversationKey) {

  const key = String(conversationKey || "").trim();

  return Boolean(key && monitorPostWorkAlerts.has(key));

}

function monitorCreateChatCompletionAlert(conversationKey, attentionCue="", completionCue="general") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const attention=String(attentionCue||"").toLowerCase();

  const cue=String(completionCue||"general").toLowerCase();

  // Chat generation finishing is a pause/notice, never evidence that project
  // work is close-safe. Only an authoritative terminal report emits complete.
  const detail=attention==="action"?{warning:true,tone:"action",label:"사용자 조치 필요"}:attention==="input"?{warning:true,tone:"input",label:"추가 입력 필요"}:attention==="question"?{warning:true,tone:"question",label:"사용자 확인/선택 대기"}:cue==="failure"?{warning:true,tone:"failure",label:"실패 / 오류"}:cue==="review"?{warning:true,tone:"review",label:"검토 필요"}:{activity:"pause",tone:cue==="success"?"success":"general",label:cue==="success"?"응답 완료 · 후속 확인 대기":"채팅 작업 완료"};

  monitorPostWorkAlerts.add(key); monitorChatAlertDetails.set(key,detail); monitorAcknowledgedPostWork.delete(key); monitorPostWorkPersist();

  const at=Date.now(); monitorSharedRuntimeAlertAt.set(key,at); void monitorPublishSharedRuntime("alert",key,{activity:detail.activity||"",warning:detail.warning===true,tone:detail.tone,label:detail.label},at);

}

function monitorChatAlertDetail(conversationKey) {

  const key=String(conversationKey||"").trim(); return key&&monitorPostWorkAlerts.has(key)?(monitorChatAlertDetails.get(key)||{activity:"pause",tone:"general",label:"채팅 작업 완료"}):null;

}

function monitorReportMatchesTask(report, task) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorReportMatchesTask"].apply(this, arguments); }
function monitorAuthoritativeConversationForTask(task, state, report) {

  const owner=String(task?.assigned_agent||task?.executor||"").trim().toUpperCase();

  if (!owner) return "";

  const matches=(Array.isArray(state?.workers)?state.workers:[]).filter((worker)=>monitorGhostWorkerId(worker)===owner&&String(worker?.conversation_key||"").trim());

  if (matches.length!==1) return "";

  const key=String(matches[0].conversation_key||"").trim();

  const sender=String(report?.sender_endpoint_id||"").trim();

  if (sender && sender!=="CURRENT_CHAT" && sender!==key) return "";

  return monitorOpenEndpointsForConversation(state,key).length ? key : "";

}

function monitorAuthoritativeAlertDetail(report, task = null) {

  const verdict=String(report?.final_verdict||report?.status||"").toUpperCase();

  const reportText=[report?.summary,report?.result,report?.detail,report?.message,report?.completion_report?.summary,report?.completion_report?.result,report?.completion_report?.detail].filter(Boolean).map(String).join(" ").toUpperCase();

  if (/\b(FAIL|FAILED|BLOCKED|ERROR|FATAL|BROKEN|UNRECOVERABLE)\b|실패|오류|중단|차단/.test(reportText)) return {warning:true,tone:"failure",label:"중요 오류 / 실패 / BLOCKED"};

  if (/\b(NEEDS_REVIEW|WARNING|WARN|CAUTION|PARTIAL|DEGRADED|ATTENTION)\b|검토 필요|주의|경고|부분 성공|확인 필요/.test(reportText)) return {warning:true,tone:"review",label:"주의 / 검토 필요"};

  const taskStatus=String(task?.status||"").toUpperCase();
  if (["SUCCEEDED","COMPLETED","COMPLETE","DONE"].includes(taskStatus) && /\b(PASS|PASSED|SUCCESS|SUCCEEDED|COMPLETED|COMPLETE|DONE|VERIFIED|OK)\b|성공|완료|검증 통과|정상/.test(reportText)) return {activity:"complete",tone:"success",label:"작업 완료 · 창을 닫아도 됨"};

  if (["FAIL","FAILED","BLOCKED"].includes(verdict)) return {symbol:"!",tone:"failure",label:"실패 / 오류 / BLOCKED"};

  if (verdict==="NEEDS_REVIEW") return {symbol:"!",tone:"review",label:"검토 필요"};

  if (["PASS","COMPLETED","COMPLETE","DONE","SUCCEEDED"].includes(verdict)) return {symbol:"!",tone:"success",label:"성공 / PASS"};

  return {activity:"pause",tone:"general",label:"완료 보고 대기"};

}

function monitorSyncAuthoritativeCompletionAlerts(state) {
  let renderChanged = false;
  const tasks=Array.isArray(state?.tasks)?state.tasks:[];
  const terminal=new Set(["SUCCEEDED","COMPLETED","COMPLETE","DONE","FAILED","BLOCKED","NEEDS_REVIEW"]);
  const authoritative=new Map();
  const pendingIds=new Set();

  for (const report of monitorPendingDurableReports) {
    const reportId=String(report?.report_id||"").trim(); if(reportId)pendingIds.add(reportId);
    const task=tasks.find((item)=>String(item?.id||"").trim()===String(report?.task_id||"").trim());
    if (!task || !terminal.has(String(task?.status||"").toUpperCase()) || !monitorReportMatchesTask(report,task)) continue;
    const key=monitorAuthoritativeConversationForTask(task,state,report); if(!key)continue;
    const previous=authoritative.get(key);
    if(!previous || monitorGhostTime(report?.created_at)>monitorGhostTime(previous?.report?.created_at)) authoritative.set(key,{report,detail:monitorAuthoritativeAlertDetail(report,task)});
  }

  for (const reportId of [...monitorAcknowledgedReportIds]) if(!pendingIds.has(reportId)) monitorAcknowledgedReportIds.delete(reportId);
  monitorAuthoritativeReportByConversation.clear();

  for (const [key,item] of authoritative) {
    const reportId=String(item.report?.report_id||"").trim();
    if(reportId)monitorAuthoritativeReportByConversation.set(key,reportId);
    if(reportId && monitorAcknowledgedReportIds.has(reportId)) continue;
    if(monitorConversationIsGenerating(key,state)) continue;
    const direct=monitorDirectGenerationByConversation.get(key);
    if(direct?.generating===false && Date.now()-Number(direct.at||0)<MONITOR_COMPLETION_STABLE_MS) continue;

    const previousDetail=monitorChatAlertDetails.get(key);
    const nextDetail=item.detail||{};
    if (
      !monitorPostWorkAlerts.has(key)
      || monitorAcknowledgedPostWork.has(key)
      || String(previousDetail?.symbol||"")!==String(nextDetail?.symbol||"")
      || String(previousDetail?.tone||"")!==String(nextDetail?.tone||"")
      || String(previousDetail?.label||"")!==String(nextDetail?.label||"")
    ) renderChanged=true;

    monitorPostWorkAlerts.add(key);
    monitorChatAlertDetails.set(key,nextDetail);
    monitorAcknowledgedPostWork.delete(key);
  }

  // Keep local completion/attention alerts until the user acknowledges them.
  // Missing ACT durable reports must not erase a valid ! or ? alert.
  monitorPostWorkPersist();
  return renderChanged;
}

function monitorSyncChatCompletionTransitions(state) {
  let renderChanged = false;
  for (const endpoint of Array.isArray(state?.endpoints)?state.endpoints:[]) {
    const key=String(endpoint?.conversation_key||"").trim(); if(!key||String(endpoint?.presence_state||"").toUpperCase()!=="OPEN")continue;
    const directState=monitorDirectConversationGenerationState(key);
    const generating=directState===true || monitorEndpointGenerationIsActive(endpoint);
    const previous=monitorGenerationSeen.get(key);

    if(generating){
      if (
        previous!==true
        || monitorPostWorkAlerts.has(key)
        || monitorChatAlertDetails.has(key)
        || monitorAcknowledgedPostWork.has(key)
      ) renderChanged=true;
      monitorCancelScheduledCompletionAlert(key);
      monitorGenerationSeen.set(key,true);
      monitorWorkedConversationKeys.add(key);
      monitorPostWorkAlerts.delete(key);
      monitorChatAlertDetails.delete(key);
      monitorAcknowledgedPostWork.delete(key);
      monitorPostWorkPersist();
      continue;
    }

    if(previous===true){
      renderChanged=true;
      monitorGenerationSeen.set(key,false);
      const direct=monitorDirectGenerationByConversation.get(key)||{};
      monitorScheduleChatCompletionAlert(key,direct.attentionCue||"",direct.completionCue||"general");
    } else if(previous===undefined) {
      // Initial idle observation is not proof of a newly completed response.
      monitorGenerationSeen.set(key,false);
    }
  }
  return renderChanged;
}


function monitorPostWorkPersist() {

  if (!monitorPostWorkStorageReady) return;

  if (monitorPostWorkPersistTimer) clearTimeout(monitorPostWorkPersistTimer);

  monitorPostWorkPersistTimer = setTimeout(() => {

    monitorPostWorkPersistTimer = 0;

    chrome.storage.local.set({ [MONITOR_POST_WORK_STORAGE_KEY]: { worked:[...monitorWorkedConversationKeys], acknowledged:[...monitorAcknowledgedPostWork], acknowledgedReports:[...monitorAcknowledgedReportIds], alerts:[...monitorPostWorkAlerts], details:Object.fromEntries(monitorChatAlertDetails), lastObservedAt:monitorPostWorkLastObservedAt } });

  }, 120);

}

function monitorAcknowledgePostWork(conversationKey, hwnd="") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const reportId=String(monitorAuthoritativeReportByConversation.get(key)||"").trim();

  if(reportId)monitorAcknowledgedReportIds.add(reportId);

  monitorAcknowledgedPostWork.add(key); monitorPostWorkAlerts.delete(key); monitorChatAlertDetails.delete(key);

  if(hwnd)monitorPausedByHwnd.delete(String(hwnd));

  monitorPostWorkPersist();

  const at=Date.now(); monitorSharedRuntimeAckAt.set(key,at); void monitorPublishSharedRuntime("ack",key,{},at);

}

function monitorAcknowledgePostWorkForHwnd(hwnd) {

  const target=String(hwnd||"").trim(); if(!target)return false;

  const location=monitorWindowDesktopLocations.get(target);

  const key=String(location?.conversationKey||"").trim(); if(!key)return false;

  monitorAcknowledgePostWork(key,target);

  for(const node of document.querySelectorAll(`[data-hwnd="${target}"]`))node.classList.remove("monitor-window-paused");

  for(const overlay of document.querySelectorAll(`.monitor-window-pause-overlay[data-hwnd="${target}"]`))overlay.remove();
  return true;

  if(monitorLastAiState)renderWorkers(monitorLastAiState);

  return true;

}

function monitorLiveRoleForConversation(conversationKey, state, hwnd = "") {

  const key = String(conversationKey || "").trim();

  const physicalHwnd=String(hwnd||"").trim();

  if (!key || String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return "";

  const nodes=(Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[]).filter((node)=>String(node?.current_conversation_key||"").trim()===key&&String(node?.identity_authority||"")==="ACT_TAB_CHAT"&&String(node?.location_authority||"")==="ACT_NATIVE_OBSERVER"&&(!physicalHwnd||String(node?.hwnd||"").trim()===physicalHwnd));

  const roles=[...new Set(nodes.map((node)=>String(node?.role||"").toUpperCase()).filter(Boolean))];

  return roles.length===1?roles[0]:"";

}

function monitorEndpointGenerationIsActive(endpoint) {
  return monitorNodeGenerationAPI.endpointIsGenerating(endpoint);
}

function monitorConversationIsGenerating(conversationKey, state) {
  return monitorNodeGenerationAPI.conversationIsGenerating(conversationKey, state);
}

function monitorOpenEndpointForHwnd(hwnd, state = monitorLastAiState) {

  const key=String(hwnd||"").trim();

  if(!key||!state)return null;

  const endpoints=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((endpoint)=>

    String(endpoint?.presence_state||"").toUpperCase()==="OPEN"

    && ["GOOGLE","NAVER"].includes(String(endpoint?.profile_id||"").toUpperCase())

  );

  const browserNodes=Array.isArray(state?.organization?.browser_nodes)?state.organization.browser_nodes:[];
  const browserWindowIds=[...new Set(browserNodes
    .filter((node)=>String(node?.hwnd||"").trim()===key)
    .map((node)=>String(node?.window_id??node?.browser_window_id??"").trim())
    .filter((value)=>/^\d+$/.test(value)&&value!=="0"))];
  if(browserWindowIds.length===1){
    const byBrowserWindow=endpoints.filter((endpoint)=>{
      const metadata=endpoint?.metadata&&typeof endpoint.metadata==="object"?endpoint.metadata:{};
      const windowId=String(endpoint?.window_id??endpoint?.browser_window_id??metadata.window_id??metadata.browser_window_id??"").trim();
      return windowId===browserWindowIds[0];
    });
    if(byBrowserWindow.length===1)return byBrowserWindow[0];
  }

  const nativeConversationKey=String(monitorWindowDesktopLocations.get(key)?.conversationKey||"").trim();

  if(nativeConversationKey){

    const exact=endpoints.filter((endpoint)=>String(endpoint?.conversation_key||"").trim()===nativeConversationKey);

    if(exact.length===1)return exact[0];

  }

  const byHwnd=endpoints.filter((endpoint)=>{

    const explicit=String(endpointOsWindowHandle(endpoint)||"").trim();

    if(explicit===key)return true;

    const location=monitorLocationForEndpoint(endpoint);

    return String(location?.hwnd||"").trim()===key;

  });

  return byHwnd.length===1?byHwnd[0]:null;

}

function monitorHwndIsGenerating(hwnd, state) {
  return monitorNodeGenerationAPI.hwndIsGenerating(hwnd, state);
}

function monitorVisualConversationForHwnd(hwnd, state) {

  const key = String(hwnd || "").trim();

  if (!key || !state) return "";

  const mapped = (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((endpoint) => {

    if (String(endpoint?.presence_state || "").toUpperCase() !== "OPEN") return false;

    if (!["GOOGLE","NAVER"].includes(String(endpoint?.profile_id || "").toUpperCase())) return false;

    const location = monitorLocationForEndpoint(endpoint);

    return String(location?.hwnd || "") === key;

  });

  const active = mapped.filter((endpoint) => endpoint?.metadata?.tab_active === true);

  if (active.length === 1) return String(active[0]?.conversation_key || "").trim();

  const nativeKey = String(monitorWindowDesktopLocations.get(key)?.conversationKey || "").trim();

  if (nativeKey && mapped.some((endpoint) => String(endpoint?.conversation_key || "").trim() === nativeKey)) return nativeKey;

  if (mapped.length === 1) return String(mapped[0]?.conversation_key || "").trim();

  return nativeKey;

}

function monitorConversationGroupVisual(conversationKey, state) {

  const key = String(conversationKey || "").trim();

  if (!key || !state) return null;

  const windowKeys = new Set();

  for (const endpoint of monitorOpenEndpointsForConversation(state, key)) {

    const location = monitorLocationForEndpoint(endpoint);

    const windowKey = String(location?.hwnd || endpointOsWindowHandle(endpoint) || monitorEndpointWindowKey(endpoint) || "").trim();

    if (windowKey) windowKeys.add(windowKey);

  }

  if (windowKeys.size < 2) return null;

  let hash = 0;

  for (const ch of key) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0;

  return { key, count: windowKeys.size, hue: Math.abs(hash) % 360 };

}

function applyMonitorConversationGroupVisual(node, conversationKey, state) {

  if (!node) return null;

  const group = monitorConversationGroupVisual(conversationKey, state);

  node.classList.toggle("monitor-conversation-duplicate", Boolean(group));

  if (!group) {

    node.style.removeProperty("--monitor-conversation-hue");

    delete node.dataset.conversationGroup;

    return null;

  }

  node.style.setProperty("--monitor-conversation-hue", String(group.hue));

  node.dataset.conversationGroup = group.key;

  return group;

}

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

let monitorHighlightedHwnd = "";

let monitorBctNodeHighlightedHwnd = "";

const monitorNodePanelSelection = globalThis.MonitorNodePanelSelection.create();

const monitorSelectedHwnds = new Set();

let monitorSharedSelectionRevision = "";

let monitorSharedSelectionSyncBusy = false;

let monitorSharedSelectionWriteSerial = Promise.resolve();

let monitorSharedSelectionWritePending = 0;

function compareMonitorSharedSelectionRevision(leftValue, rightValue) { return globalThis.MonitorDomainAPIs["shared-ui"]["compareMonitorSharedSelectionRevision"].apply(this, arguments); }

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

async function syncMonitorSharedSelection() {

  if (monitorSharedSelectionSyncBusy || monitorSharedSelectionWritePending > 0) return;

  monitorSharedSelectionSyncBusy = true;

  try { applyMonitorSharedSelection(await monitorNative({ type: "getSharedMonitorSelection" })); }

  catch (_) {}

  finally { monitorSharedSelectionSyncBusy = false; }

}

async function monitorSyncSharedState(reason = "event", publishInstance = false) {

  const jobs = [syncMonitorSharedSelection(), monitorSyncSharedRuntime()];

  if (publishInstance) jobs.push(monitorPublishSharedInstance(reason));

  await Promise.allSettled(jobs);

}

let monitorHoveredHwnd = "";

let monitorHoverPointer = { x: -1, y: -1 };

let monitorHoverRecheckTimer = 0;

function monitorPreviewAtPointer() {

  if (monitorHoverPointer.x < 0 || monitorHoverPointer.y < 0) return "";

  const element = document.elementFromPoint(monitorHoverPointer.x, monitorHoverPointer.y);

  const target = element?.closest?.(".monitor-desktop-thumb-window, .monitor-window-preview, .monitor-worker-row[data-hwnd]");

  return String(target?.dataset?.hwnd || "");

}

function recheckMonitorHover() {

  const pointerKey = monitorPreviewAtPointer();

  if (pointerKey || !monitorHoveredHwnd) { applyMonitorWindowHover(pointerKey); return; }

  applyMonitorWindowHover("");

}

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

function scheduleMonitorHoverRecheck() {

  clearTimeout(monitorHoverRecheckTimer);

  monitorHoverRecheckTimer = setTimeout(() => {

    monitorHoverRecheckTimer = 0;

    recheckMonitorHover();

  }, 20);

}

function syncMonitorBctNodeTargetHighlight() {
  const selectedHwnd = String(monitorBctNodeHighlightedHwnd || "");
  for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview, .monitor-thumbnail-node-window")) {
    preview.classList.toggle(
      "monitor-bct-node-target-highlighted",
      Boolean(selectedHwnd) && String(preview.dataset.hwnd || "") === selectedHwnd,
    );
  }
  if (!monitorWorkers) return;
  for (const row of monitorWorkers.querySelectorAll(".monitor-bct-node-row[data-window-id]")) {
    const selected = Boolean(monitorNodePanelSelection.get())
      && monitorBctNodeSelectionKey(row.dataset) === monitorNodePanelSelection.get();
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");
  }
}

function monitorBctNodeSelectionKey(value) { return monitorNodePanelSelection.key(value); }

function applyMonitorBctNodeHighlight(hwnd) {
  monitorBctNodeHighlightedHwnd = String(hwnd || "");
  applyMonitorWindowHighlight(hwnd, { bctNode: true });
  syncMonitorBctNodeTargetHighlight();
  // A selected node may be in a minimized Chrome window. Re-project the same
  // exact selection onto the desktop's minimized summary without changing any
  // Windows or Chrome state.
  syncMonitorMinimizedNodeBadges();
  syncMonitorAllDesktopThumbnailNodeBadges();
}

function applyMonitorWindowHighlight(hwnd, options = {}) {

  const nextHwnd = String(hwnd || "");

  const changed = nextHwnd !== monitorHighlightedHwnd;

  if (!options.bctNode && !options.preserve && !options.remote) {
    monitorBctNodeHighlightedHwnd = "";
    monitorNodePanelSelection.clear();
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

function monitorEndpointFreshnessState(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointFreshnessState"].apply(this, arguments); }

function resolveWorkerConnectionState(worker, state) {

  const endpoint = endpointForMonitorWorker(worker, state);

  if (endpoint) {

    return monitorEndpointFreshnessState(endpoint);

  }

  if (endpointRegistryIsAuthoritative(worker, state)) return "disconnected";

  const explicit = String(worker?.connection_status || worker?.transport_status || "").trim().toLowerCase();

  if (["connected", "online"].includes(explicit)) return "connected";

  if (["disconnected", "offline", "unavailable"].includes(explicit)) return "disconnected";

  const workerStatus = String(worker?.status || "").trim().toLowerCase();

  const profileStatus = String(profileForMonitorWorker(worker, state)?.status || "").trim().toLowerCase();

  if (["offline", "unavailable"].includes(workerStatus)) return "disconnected";

  if (["offline", "unavailable"].includes(profileStatus)) return "disconnected";

  if (["available", "connected", "online"].includes(workerStatus)) return "connected";

  if (["available", "connected", "online"].includes(profileStatus)) return "connected";

  return "unknown";

}

function resolveWorkerWorkState(worker, state) {

  const endpoint = endpointForMonitorWorker(worker, state);

  if (monitorEndpointGenerationIsActive(endpoint)) return "running";

  if (worker?.__kind === "WIN") return "idle";

  const station = stationForMonitorWorker(worker, state);

  const stationStatus = String(station?.status || "").trim().toLowerCase();

  if (stationStatus) return stationStatus;

  const taskId = station?.current_task_id || worker?.current_task_id;

  const task = taskId && (Array.isArray(state?.tasks) ? state.tasks : []).find((item) => item?.id === taskId);

  if (task?.status) return String(task.status).trim().toLowerCase();

  const explicit = String(worker?.work_status || "").trim().toLowerCase();

  if (explicit) return explicit;

  const workerStatus = String(worker?.status || "").trim().toLowerCase();

  if (workerStatus && !["available", "connected", "online", "offline", "unavailable"].includes(workerStatus)) return workerStatus;

  return "idle";

}

// SVG icon semantics used by the node list and desktop-thumbnail overlay.
// Kept distinct from the legacy text symbol helper above so persisted old
// alert records cannot accidentally control the new visual meaning.
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

const MONITOR_ROLE_ORDER = ["SUPERVISOR-A", "SUPERVISOR-B", "RELAY", "SOURCE", "WS2", "WORKER-A", "WORKER-B", "IMPLEMENTER", "MONITOR-IMPLEMENTER"];

function monitorSortLocationParts(worker, state) {

  const canonical = monitorCanonicalPhysicalLocation(worker, state);

  if (canonical?.desktop) return { desktop: canonical.desktop, slot: canonical.slot };

  const station = stationForMonitorWorker(worker, state), metadata = monitorStationMetadata(station);

  const desktop = Number(station?.desktop_id ?? station?.desktop_index ?? metadata.desktop_id ?? metadata.desktop_index);

  const slot = Number(station?.slot_index ?? metadata.slot_index);

  return { desktop: Number.isInteger(desktop) && desktop > 0 ? desktop : null, slot: Number.isInteger(slot) && slot > 0 ? slot : null };

}

function monitorWorkerSortKey(worker, state) {

  const { desktop, slot } = monitorSortLocationParts(worker, state);

  const desktopSort = desktop ?? Number.MAX_SAFE_INTEGER;

  const slotSort = desktop ? (slot ?? Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;

  const role = String(worker?.role || "").toUpperCase();

  const roleIndex = MONITOR_ROLE_ORDER.includes(role) ? MONITOR_ROLE_ORDER.indexOf(role) : MONITOR_ROLE_ORDER.length;

  return [desktopSort, slotSort, roleIndex, cleanMonitorWorkerName(worker).toUpperCase()];

}

function compareMonitorWorkers(a, b, state) {

  const ak = monitorWorkerSortKey(a, state), bk = monitorWorkerSortKey(b, state);

  for (let i = 0; i < ak.length; i += 1) {

    if (ak[i] < bk[i]) return -1;

    if (ak[i] > bk[i]) return 1;

  }

  return 0;

}

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

const monitorGhostCache = new Map();

const monitorHiddenGhosts = new Set();

let monitorGhostStorageReady = false;

const monitorRecoveryPickerState = globalThis.MonitorRecoveryPickerState.create();

let monitorRebootSnapshot = { captured_at_ms:0, items:[] };
const monitorRecoveryInventoryController = globalThis.MonitorRecoveryInventory.create({toEpoch: value => monitorGhostTime(value)});

let monitorRebootSnapshotReady = false;

let monitorRebootRestoreActive = false;

const monitorRebootRestorePendingKeys = new Set();

function monitorGhostBoundText(value, max = MONITOR_GHOST_TEXT_MAX) { return String(value || "").slice(0, max); }

function monitorGhostTime(value) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostTime"].apply(this, arguments); }

function monitorGhostWorkerId(worker) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostWorkerId"].apply(this, arguments); }

function monitorGhostTaskForWorker(worker, state) {

  const tasks = Array.isArray(state?.tasks) ? state.tasks : []; const station = stationForMonitorWorker(worker, state);

  const currentId = String(station?.current_task_id || worker?.current_task_id || "");

  if (currentId) { const exact = tasks.find((task) => String(task?.id || "") === currentId); if (exact) return exact; }

  const owner = monitorGhostWorkerId(worker);

  return tasks.filter((task) => String(task?.assigned_agent || "").trim().toUpperCase() === owner).sort((a,b) => Math.max(monitorGhostTime(b?.completed_at),monitorGhostTime(b?.updated_at),monitorGhostTime(b?.created_at)) - Math.max(monitorGhostTime(a?.completed_at),monitorGhostTime(a?.updated_at),monitorGhostTime(a?.created_at)))[0] || null;

}

function monitorGhostMeaningfulTitle(value, previous = "") {

  const text = monitorGhostBoundText(value, 500).trim();

  if (!text) return previous || "";

  if (/^(?:waiting|available|idle|paused|pending|queued|대기|유휴)$/i.test(text)) return previous || "";

  return text;

}

function monitorContextTitleRecord(key) { return key ? (monitorContextTitles.get(String(key)) || {}) : {}; }

function monitorTitlesEquivalent(observed, requested) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorTitlesEquivalent"].apply(this, arguments); }

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

function monitorPublishSharedRebootSnapshot(snapshot=monitorRebootSnapshot){
  if (!MONITOR_FEATURE_RECOVERY_ENABLED) return;

  if(!snapshot||!Array.isArray(snapshot.items)||!snapshot.items.length)return;

  void monitorNative({type:"setSharedMonitorRuntime",kind:"alert",conversationKey:MONITOR_SHARED_REBOOT_SNAPSHOT_KEY,at:String(Number(snapshot.captured_at_ms)||Date.now()),symbol:"",tone:"reboot-snapshot",label:JSON.stringify(snapshot)}).catch(()=>null);

}

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


function monitorPublishSharedContextTitle(key, rec) {

  key=String(key||"").trim(); if(!key||!rec||typeof rec!=="object")return;

  const at=Number(rec.title_updated_ms||0); if(!(at>0))return;

  void monitorNative({type:"setSharedMonitorRuntime",kind:"alert",conversationKey:`${MONITOR_SHARED_CONTEXT_TITLE_PREFIX}${key}`,at:String(at),symbol:"T",tone:"context-title",label:JSON.stringify(rec)}).catch(()=>null);

}

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

function monitorContextTitleInput(worker,state,endpoint=null){

  const key=String(worker?.conversation_key||endpoint?.conversation_key||"").trim(); const ghost=key?monitorGhostCache.get(key):null;

  const task=monitorGhostTaskForWorker(worker,state); const history=(Array.isArray(ghost?.history)?ghost.history:[]).slice(-5).map(x=>String(x?.text||"")).filter(Boolean);

  const project=String(task?.project_name||worker?.project_name||endpoint?.metadata?.project_name||ghost?.project_name||"").trim();

  return {conversation_key:key,browser_title:String(endpoint?.title||worker?.title||ghost?.title||""),task_title:String(task?.title||ghost?.task_title||""),project_name:project,history,conversation_tail:Array.isArray(ghost?.conversation_tail)?ghost.conversation_tail.slice(-5):[],created_at_ms:Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0)};

}

function monitorContextTitleSignature(input) { return globalThis.MonitorDomainAPIs["shared-ui"]["monitorContextTitleSignature"].apply(this, arguments); }

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

function setMonitorManualContextTitle(key,title){

  key=String(key||"").trim(); title=String(title||"").trim(); if(!key)return;

  const rec=monitorContextTitleRecord(key); monitorContextTitles.set(key,{...rec,manual_title:title,manual_locked:Boolean(title),title_source:title?"MANUAL":"AI",title_updated_ms:Date.now()}); persistMonitorContextTitles(); if(monitorLastAiState)renderWorkers(monitorLastAiState);

}

function resetMonitorContextTitleToBrowser(key){

  key=String(key||"").trim(); if(!key)return; const rec=monitorContextTitleRecord(key);

  monitorContextTitles.set(key,{...rec,manual_title:"",context_title:"",context_summary:"",project_name:"",manual_locked:false,title_source:"BROWSER",title_updated_ms:Date.now(),signature:""}); persistMonitorContextTitles(); if(monitorLastAiState)renderWorkers(monitorLastAiState);

}

function monitorLifecycleTooltip(key,endpoint,ghost){

  const rec=monitorContextTitleRecord(key), created=Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0), closed=Number(ghost?.closed_at_ms||monitorGhostTime(endpoint?.closed_at)||0);

  return `프로젝트 ${rec.project_name||"미지정"} · 생성 ${created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"} · 소멸 ${closed?new Date(closed).toLocaleString("ko-KR"):"-"} · 원본 제목 ${endpoint?.title||ghost?.title||""}`;

}

async function requestMonitorConversationRename(key,title,endpoint,manualLock=true){

  key=String(key||"").trim(); title=String(title||"").trim();

  if(!key||!title){

    return false;

  }

  try{

    const rec=monitorContextTitleRecord(key);

    const requestedAt=Date.now();

    monitorContextTitles.set(key,{...rec,rename_pending_title:title,rename_pending_at_ms:requestedAt,rename_error:"",title_updated_ms:requestedAt,title_source:"RENAME_PENDING"});

    persistMonitorContextTitles();

    const stateResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store",signal:AbortSignal.timeout(60000)});

    const freshState=stateResponse.ok?await stateResponse.json():null;

    const exact=(Array.isArray(freshState?.endpoints)?freshState.endpoints:[]).filter((item)=>String(item?.conversation_key||"").trim()===key&&String(item?.presence_state||"").toUpperCase()==="OPEN");

    if(exact.length!==1)throw new Error(exact.length?"RENAME_ENDPOINT_AMBIGUOUS":"RENAME_ENDPOINT_UNAVAILABLE");

    endpoint=exact[0];

    const body={conversation_key:key,title,transport_instance_id:String(endpoint?.transport_instance_id||""),session_id:String(endpoint?.session_id||""),tab_id:Number(endpoint?.tab_id||0),profile_id:String(endpoint?.profile_id||"").toUpperCase()};

    const r=await actFetch(ORCHESTRATOR_CONVERSATION_RENAME_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});

    const responseText=await r.text(); let data={}; try{data=responseText?JSON.parse(responseText):{};}catch(_){data={error:responseText||`HTTP_${r.status}`};}

    if(!r.ok||!data?.ok)throw new Error(String(data?.error||"RENAME_FAILED"));

    if(!data?.verified&&data?.accepted&&data?.pending_observation){

      const current=monitorContextTitleRecord(key);

      monitorContextTitles.set(key,{...current,rename_pending_title:title,rename_pending_at_ms:requestedAt,rename_error:"",manual_locked:Boolean(manualLock),rename_manual_lock:Boolean(manualLock),title_source:"RENAME_PENDING",title_updated_ms:Date.now()});

      persistMonitorContextTitles(); return "pending";

    }

    if(!data?.verified)throw new Error(String(data?.error||"RENAME_NOT_VERIFIED"));

    const current=monitorContextTitleRecord(key);

    const verifiedTitle=String(data.observed_title||data.title||title).trim();

    monitorContextTitles.set(key,{...current,verified_title:verifiedTitle,manual_title:"",context_title:"",rename_pending_title:"",rename_pending_at_ms:0,rename_error:"",manual_locked:Boolean(manualLock),title_source:manualLock?"MANUAL_VERIFIED":"AI_VERIFIED",title_updated_ms:Date.now()});

    if(monitorLastAiState&&Array.isArray(monitorLastAiState.endpoints)){

      for(const item of monitorLastAiState.endpoints){

        if(String(item?.conversation_key||"").trim()===key&&String(item?.presence_state||"").toUpperCase()==="OPEN") item.title=verifiedTitle;

      }

    }

    persistMonitorContextTitles(); return true;

  }catch(error){

    const current=monitorContextTitleRecord(key), failedAt=Date.now(); monitorContextTitles.set(key,{...current,rename_pending_title:"",rename_pending_at_ms:0,rename_error:String(error?.message||error||"RENAME_FAILED"),title_updated_ms:failedAt,title_source:"RENAME_FAILED"}); persistMonitorContextTitles(); return false;

  }

}

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

function monitorContextTitlePart(value) {

  let text = monitorGhostMeaningfulTitle(value, "");

  if (!text) return "";

  text = String(text).replace(/\s*\[[A-Z_]+\].*$/i, "").replace(/\s+·\s+.*$/, "").trim();

  return normalizeMonitorWindowTitle(text).slice(0, 28).trim();

}

function monitorWorkerMeaningfulTitle(worker, state, endpoint = null) {

  const key = String(worker?.conversation_key || "").trim(); const cached = key ? monitorGhostCache.get(key) : null;

  const task = monitorGhostTaskForWorker(worker, state);

  const recent = monitorContextTitlePart(task?.title);

  const parts = []; if (recent) parts.push(recent);

  const history = Array.isArray(cached?.history) ? [...cached.history].reverse() : [];

  for (const item of history) { const part=monitorContextTitlePart(item?.text); if(part && !parts.includes(part)) parts.push(part); if(parts.length>=3) break; }

  if (!parts.length) { const fallback=monitorContextTitlePart(endpoint?.title) || monitorContextTitlePart(worker?.title) || monitorContextTitlePart(cached?.meaningful_title); if(fallback) parts.push(fallback); }

  const rolled = parts.join(" · ");

  return normalizeMonitorWindowTitle(rolled || cached?.meaningful_title || "").slice(0, 64).trim();

}

function monitorWorkerContextTitle(worker, state, endpoint = null) {

  const current=monitorWorkerMeaningfulTitle(worker,state,endpoint);

  const key=String(worker?.conversation_key||"").trim(), cached=key?monitorGhostCache.get(key):null;

  const previous=(Array.isArray(cached?.history)?cached.history:[]).map((item)=>String(item?.text||"").split(" [")[0].split(" · ")[0].trim()).filter(Boolean).reverse();

  const parts=[]; if(current)parts.push(current); for(const title of previous){if(!parts.includes(title))parts.push(title);if(parts.length>=3)break;}

  return normalizeMonitorWindowTitle(parts.join(" · ").slice(0,72));

}

function monitorGhostAgeing(ghost, now = Date.now()) {

  const u = ghost?.usage || {}; let score = 0;

  // Conversation handoff readiness heuristic, not browser performance and not actual model context %.

  // rendered_chars is an incremental cumulative estimate; turns is a low-cost secondary signal.

  if (u.rendered_chars != null) score += Math.min(70, Math.sqrt(Math.max(0, u.rendered_chars) / 100000) * 70);

  if (u.turns != null) score += Math.min(30, Math.sqrt(Math.max(0, u.turns) / 120) * 30);

  return Math.max(0, Math.min(100, Math.round(score)));

}

function monitorGhostArchiveAgeing(ghost) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostArchiveAgeing"].apply(this, arguments); }
function monitorGhostProtected(ghost) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostProtected"].apply(this, arguments); }

let monitorGhostPersistTimer = 0;

function monitorGhostPersist(immediate = false) {

  if (!monitorGhostStorageReady) return;

  const write = () => { monitorGhostPersistTimer = 0; const cache=[...monitorGhostCache.values()].sort((a,b)=>Number(b?.last_activity_ms||0)-Number(a?.last_activity_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX); chrome.storage.local.set({ [MONITOR_GHOST_CACHE_KEY]:cache, [MONITOR_GHOST_HIDDEN_KEY]:[...monitorHiddenGhosts].slice(0,MONITOR_GHOST_CACHE_MAX) }); };

  if (immediate) { if (monitorGhostPersistTimer) clearTimeout(monitorGhostPersistTimer); write(); return; }

  if (!monitorGhostPersistTimer) monitorGhostPersistTimer = setTimeout(write, 5000);

}

function monitorClosedConversationRecoveryItems(state = null) {
  const result = monitorRecoveryInventoryController.project({
    ghosts: monitorGhostCache.values(),
    snapshot: monitorRebootSnapshot,
    trashedKeys: monitorTrashedConversationKeys,
    endpoints: Array.isArray(state?.endpoints) ? state.endpoints : []
  });
  if (result.updatedSnapshot) {
    monitorRebootSnapshot = result.updatedSnapshot;
    chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]: monitorRebootSnapshot});
    monitorPublishSharedRebootSnapshot();
  }
  return result.items;
}

function monitorClosedConversationPreviousLocation(ghost) {

  const d=Number(ghost?.desktop), s=Number(ghost?.slot);

  return Number.isInteger(d)&&d>0&&Number.isInteger(s)&&s>0 ? `D${d}-${s}` : "알 수 없음";

}

function monitorClosedConversationContextTitle(ghost) {

  const key=String(ghost?.conversation_key||"").trim(); const rec=monitorContextTitleRecord(key);

  const titles=[]; const add=(value)=>{const text=monitorContextTitlePart(value);if(text&&!titles.includes(text))titles.push(text);};

  if(rec?.manual_locked) add(rec?.manual_title);

  add(rec?.context_title);

  const recoveryCandidate=monitorContextTitlePart(ghost?.meaningful_title||ghost?.task_title||"");

  if(key && !rec?.manual_locked && !String(rec?.context_title||"").trim() && recoveryCandidate && !/^D\d+-\d+$/i.test(recoveryCandidate) && recoveryCandidate!=="알 수 없음") {

    const promoted={...rec,context_title:recoveryCandidate,title_source:"RECOVERY",title_updated_ms:Date.now(),manual_locked:false};

    monitorContextTitles.set(key,promoted); monitorPublishSharedContextTitle(key,promoted);

  }

  add(recoveryCandidate); add(ghost?.task_title);

  for(const item of [...(Array.isArray(ghost?.history)?ghost.history:[])].reverse()) add(item?.text);

  add(ghost?.title); return monitorGhostBoundText(titles.slice(0,3).join(" · ")||key.slice(0,8),96);

}

function renderMonitorClosedConversationRecoveryPanel(state) {

  const panel=document.createElement("div"); panel.className="monitor-closed-conversation-panel monitor-trash-recovery-panel";

  const items=monitorClosedConversationRecoveryItems(state);

  const makeHeader=(label,count,onClear,extras=[])=>{const head=document.createElement("div");head.className="monitor-trash-pane-header";const title=document.createElement("strong");title.textContent=`${label} (${count})`;const actions=document.createElement("span");actions.className="monitor-trash-pane-actions";for(const button of extras)if(button)actions.append(button);const clear=document.createElement("button");clear.type="button";clear.className="monitor-trash-clear-all";clear.textContent="다 비움";clear.disabled=!count;clear.addEventListener("click",(e)=>{e.stopPropagation();if(confirm(`${label} 항목을 모두 비울까요?`))onClear();});actions.append(clear);head.append(title,actions);return head;};

  const recoveryWorkers=monitorWorkersForState(state||{});

  const recoveryWorkerByKey=new Map(recoveryWorkers.map((worker)=>[String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim(),worker]).filter(([key])=>key));

  const recoveryEndpoints=Array.isArray(state?.endpoints)?state.endpoints:[];

  const recoveryNodeStatus=(key,record=null)=>{

    key=String(key||"").trim();

    const endpoint=recoveryEndpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key)||null;

    const open=String(endpoint?.presence_state||"").toUpperCase()==="OPEN";

    const worker=recoveryWorkerByKey.get(key)||null;

    const work=String(worker?resolveWorkerWorkState(worker,state):(record?.work_status||record?.task_status||"")).trim().toLowerCase();

    if(["running","working","busy","executing","in_progress"].includes(work))return {label:"처리 중",tone:"processing"};

    if(["waiting_resource","waiting","paused","queued","pending"].includes(work))return {label:"대기 중",tone:"waiting"};

    if(["needs_review","failed","failure","blocked","recovery","recovery_pending","degraded"].includes(work))return {label:"확인 필요",tone:"attention"};

    if(["succeeded","completed","complete","done"].includes(work))return {label:"완료",tone:"complete"};

    if(open)return {label:"활동 중",tone:"active"};

    return {label:"닫힘",tone:"closed"};

  };

  const appendRecoveryStatus=(row,key,record=null)=>{const status=recoveryNodeStatus(key,record);const badge=document.createElement("span");badge.className=`monitor-trash-node-status monitor-trash-node-status-${status.tone}`;badge.textContent=status.label;badge.title=`현재 상태: ${status.label}`;row.append(badge);};

  const noteRecords=[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const notePane=document.createElement("section");notePane.className="monitor-trash-pane monitor-trash-note-pane";notePane.append(makeHeader("삭제된 메모",noteRecords.length,clearMonitorTrashedNotes));const noteScroll=document.createElement("div");noteScroll.className="monitor-trash-pane-scroll";

  if(!noteRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";noteScroll.append(empty);}else for(const note of noteRecords){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-note-row";const info=document.createElement("div");info.className="monitor-closed-conversation-info monitor-trash-note-info";const noteTitle=document.createElement("strong");noteTitle.textContent=note.title||monitorNotesFeature.titleFromText(note.body)||"메모";const lines=String(note.body||"").split(/\r?\n/);const firstLineIndex=lines.findIndex((line)=>line.trim());const notePreview=document.createElement("span");notePreview.textContent=(firstLineIndex>=0?lines.slice(firstLineIndex+1).join(" "):"").replace(/\s+/g," ").trim()||"내용 없음";info.append(noteTitle,notePreview);const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashedNote(note.id);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedNote(note.id);});row.append(info,restore,del);noteScroll.append(row);}notePane.append(noteScroll);panel.append(notePane);

  const renderTrashRows=(source,container)=>{const records=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")===source).sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));if(!records.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";container.append(empty);return;}for(const ghost of records){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-record-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost),at=Number(ghost?.trashed_at_ms||0),scope=String(ghost?.network_name||"미소속"),roles=Array.isArray(ghost?.role_tags)&&ghost.role_tags.length?` · ${ghost.role_tags.join(", ")}`:"";info.textContent=`${String(ghost?.node_label||"")} ${context} · ${scope}${roles} · ${location} · ${at?new Date(at).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"?"}`.trim();const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashRecord(ghost.conversation_key);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorTrashRecord(ghost.conversation_key),140);});row.append(info);if(source==="list")appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);container.append(row);}};

  const thumbRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")==="thumbnail");

  const desktopRecords=[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const thumbPane=document.createElement("section");thumbPane.className="monitor-trash-pane monitor-trash-thumbnail-pane";thumbPane.append(makeHeader("삭제된 데스크",thumbRecords.length+desktopRecords.length,clearMonitorThumbnailRecovery));const thumbScroll=document.createElement("div");thumbScroll.className="monitor-trash-pane-scroll";

  if(desktopRecords.length){

    const desktopGrid=document.createElement("div");desktopGrid.className="monitor-trash-desktop-grid";

    for(const item of desktopRecords){

      const card=document.createElement("div");card.className="monitor-trash-desktop-card";

      const visual=document.createElement("div");visual.className="monitor-trash-desktop-card-visual";

      const desktopNumber=Math.max(1,Number(item.desktop_number??item.desktopNumber??(Number(item.index||0)+1))||1);

      const badge=document.createElement("span");badge.className="monitor-desktop-number-badge monitor-trash-desktop-number";badge.textContent=`D${desktopNumber}`;

      const thumbnail=String(item.thumbnail||item.thumbnailDataUri||"");

      if(thumbnail){const image=document.createElement("img");image.className="monitor-trash-desktop-card-image";image.src=thumbnail;image.alt="";visual.append(image);}

      else{const placeholder=document.createElement("span");placeholder.className="monitor-trash-desktop-placeholder";placeholder.textContent="미리보기 없음";visual.append(placeholder);}

      visual.append(badge);

      const actions=document.createElement("div");actions.className="monitor-trash-desktop-card-actions";

      const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorTrashedDesktop(item.id,restore);});

      const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedDesktop(item.id);});

      actions.append(restore,del);card.append(visual,actions);desktopGrid.append(card);

    }

    thumbScroll.append(desktopGrid);

  }

  renderTrashRows("thumbnail",thumbScroll);thumbPane.append(thumbScroll);

  let listRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")!=="thumbnail").sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const combined=[...listRecords.map((x)=>({kind:"trash",item:x,at:Number(x?.trashed_at_ms||0)})),...items.map((x)=>({kind:"closed",item:x,at:Number(x?.closed_at_ms||x?.captured_at_ms||0)}))].sort((a,b)=>b.at-a.at);

  const kept=combined.slice(0,20), dropped=combined.slice(20), keptKeys=new Set(kept.map((x)=>String(x.item?.conversation_key||"")));

  if(dropped.length){const dropKeys=new Set(dropped.map((x)=>String(x.item?.conversation_key||"")).filter(Boolean));for(const key of dropKeys){monitorTrashRecords.delete(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);monitorTrashedConversationKeys.add(key);}monitorRebootSnapshot={...monitorRebootSnapshot,items:(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!dropKeys.has(String(x?.conversation_key||"")))};chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot});monitorPublishSharedRebootSnapshot();monitorGhostPersist(true);persistMonitorTrashedNodes();}

  listRecords=listRecords.filter((x)=>keptKeys.has(String(x?.conversation_key||"")));

  const visibleItems=kept.filter((x)=>x.kind==="closed").map((x)=>x.item);

  const convoCount=listRecords.length+visibleItems.length;

  const snapItems=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!monitorTrashedConversationKeys.has(String(x?.conversation_key||"")));

  const full=document.createElement("button");full.type="button";full.className="monitor-detached-restore monitor-recovery-full";full.textContent=`전체 복원${convoCount?` (${convoCount})`:""}`;full.disabled=!convoCount||monitorRebootRestoreActive;full.title="삭제된 노드 복구 목록 전체 복원";full.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorAllRecovery(full,listRecords,visibleItems);});

  const reboot=document.createElement("button");reboot.type="button";reboot.className="monitor-detached-restore monitor-recovery-full";reboot.textContent=`재부팅 복원${snapItems.length?` (${snapItems.length})`:""}`;reboot.disabled=!snapItems.length||monitorRebootRestoreActive;reboot.title="재부팅 전 저장된 대화만 복원";reboot.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorRebootSnapshot(reboot);});

  const convoPane=document.createElement("section");convoPane.className="monitor-trash-pane monitor-trash-conversation-pane";convoPane.append(makeHeader("삭제된 노드",convoCount,clearMonitorConversationRecovery,[full,reboot]));const convoScroll=document.createElement("div");convoScroll.className="monitor-trash-pane-scroll";

  if(listRecords.length)renderTrashRows("list",convoScroll);

  if(!visibleItems.length&&!listRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";convoScroll.append(empty);}

  for(const ghost of visibleItems){const row=document.createElement("div");row.className="monitor-closed-conversation-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost);const created=Number(ghost?.first_seen_ms||0),closed=Number(ghost?.closed_at_ms||ghost?.captured_at_ms||0),rec=monitorContextTitleRecord(String(ghost?.conversation_key||""));const displayContext=(rec.manual_locked&&rec.manual_title)||rec.context_title||ghost.meaningful_title||context;const source=ghost.recovery_source||"일반 종료";const fmtDateTime=(ms)=>ms?new Date(ms).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).replace(/\. /g,".").replace(/\.$/,""):"?";const fmtTime=(ms)=>ms?new Date(ms).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false}):"?";const sameDay=created&&closed&&new Date(created).toDateString()===new Date(closed).toDateString();info.textContent=`${location} · ${displayContext} · ${fmtDateTime(created)} - ${sameDay?fmtTime(closed):fmtDateTime(closed)}`;info.title=`이전 위치 ${location} · ${source}`;const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";const restoring=monitorDetachedRestorePending.has(String(ghost?.conversation_key||""));restore.textContent=restoring?"복구 중…":"복구";restore.disabled=restoring;restore.addEventListener("click",(event)=>{event.stopPropagation();void restoreMonitorDetachedTask(ghost,restore);});row.addEventListener("contextmenu",(event)=>{event.preventDefault();event.stopPropagation();const existing=row.querySelector(".monitor-recovery-details");if(existing){existing.remove();return;}panel.querySelectorAll(".monitor-recovery-details").forEach((node)=>node.remove());const detail=document.createElement("div");detail.className="monitor-recovery-details";const key=String(ghost?.conversation_key||"");for(const [label,value] of [["이전 위치",location],["제목",displayContext],["복구 출처",source],["생성",created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"],["소멸",closed?new Date(closed).toLocaleString("ko-KR"):"알 수 없음"],["프로필",ghost.profile_id||"-"],["conversationKey",key||"-"]]){const line=document.createElement("div");line.className="monitor-recovery-detail-line";const k=document.createElement("b");k.textContent=label;const v=document.createElement("span");v.textContent=String(value);line.append(k,v);detail.append(line);}row.append(detail);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(event)=>{event.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorRecoveryRecord(ghost.conversation_key),140);});row.append(info);appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);convoScroll.append(row);}

  const contextRows = new Map([...convoScroll.querySelectorAll('.monitor-closed-conversation-row[data-recovery-key]')]
    .map(row => [row.dataset.recoveryKey, row]));
  for (const ghost of visibleItems) {
    const row = contextRows.get(String(ghost?.conversation_key || ''));
    if (row) row.append(createMonitorContextContinueButton(ghost));
  }
  const recoveryRowsByKey=new Map([...convoScroll.querySelectorAll(".monitor-closed-conversation-row[data-recovery-key]")].map((row)=>[String(row.dataset.recoveryKey||""),row]));for(const entry of kept){const key=String(entry?.item?.conversation_key||"");const row=recoveryRowsByKey.get(key);if(row)convoScroll.append(row);}convoPane.append(convoScroll);panel.append(convoPane,thumbPane);return panel;

}

function configureMonitorProviderLaunchButton(button, provider) {
  return globalThis.MonitorProviderLaunchFeature.bind({
    button, provider,
    ports: {
      launch: request => monitorNativeLaunchIsolated(request),
      fail: message => setMonitorStatus(message, false)
    }
  });
}

function rememberMonitorWorkerPlacement(worker, state, location) {

  const key = String(worker?.conversation_key || "").trim();

  if (!key || !location?.desktop) return;

  const desktopIndex = Number(location.desktop) - 1;

  const desktopId = monitorDesktopState.desktopIds[desktopIndex] || "";

  if (!desktopId) return;

  monitorLastPlacementByConversation.set(key, { desktopId, desktop: Number(location.desktop), profileId: String(worker?.profile_id || "").trim().toUpperCase(), at: Date.now() });

}

async function syncMonitorPhysicalWorkplaces(state, force = false) {

  // Monitor is presentation/input UI and must never write physical workplace state.

  return;

}

const MONITOR_WORKER_ORDER_KEY = "desktopWindowMonitorWorkerOrderV1";

const monitorWorkerOrderByDesktop = new Map();

let monitorWorkerOrderReady = false;

function monitorPersistWorkerOrder() {

  if (!monitorWorkerOrderReady) return;

  const data={}; for(const [desktopId,keys] of monitorWorkerOrderByDesktop) data[desktopId]=[...new Set((Array.isArray(keys)?keys:[]).filter(Boolean))].slice(0,80);

  chrome.storage.local.set({[MONITOR_WORKER_ORDER_KEY]:data});

}

function monitorSetWorkerOrder(desktopId, keys) {

  const id=String(desktopId||"").trim(); if(!id)return;

  monitorWorkerOrderByDesktop.set(id,[...new Set((Array.isArray(keys)?keys:[]).map(String).filter(Boolean))]);

  monitorPersistWorkerOrder();

}

function monitorRemoveWorkerOrderKey(key) {

  const k=String(key||"").trim(); if(!k)return;

  for(const [id,keys] of monitorWorkerOrderByDesktop){const next=(keys||[]).filter(x=>String(x)!==k); if(next.length!==(keys||[]).length)monitorWorkerOrderByDesktop.set(id,next);}

}

function monitorMoveWorkerOrderKey(key, sourceDesktopId, targetDesktopId) {

  const k=String(key||"").trim(), target=String(targetDesktopId||"").trim(); if(!k||!target)return;

  monitorRemoveWorkerOrderKey(k); const next=[...(monitorWorkerOrderByDesktop.get(target)||[])]; next.push(k); monitorWorkerOrderByDesktop.set(target,[...new Set(next)]); monitorPersistWorkerOrder();

}

function monitorReorderWorkerKey(desktopId, key, targetKey, after=false) {

  const id=String(desktopId||"").trim(), k=String(key||"").trim(), t=String(targetKey||"").trim(); if(!id||!k||!t||k===t)return false;

  const current=[...(monitorWorkerOrderByDesktop.get(id)||[])].filter(x=>x!==k); let index=current.indexOf(t); if(index<0)return false; if(after)index+=1; current.splice(index,0,k); monitorSetWorkerOrder(id,current); return true;

}

function monitorListDisplaySlots(members, state) {

  const result=new Map();

  for(const worker of (Array.isArray(members)?members:[])){

    const stable=monitorStableNodeSlot(worker,state);

    if(stable)result.set(worker?.__display_key,`N${stable.slot} · D${stable.desktop}`);

  }

  return result;

}

function initializeMonitorWorkerOrderStorage() { chrome.storage.local.get([MONITOR_WORKER_ORDER_KEY],(data)=>{const raw=data?.[MONITOR_WORKER_ORDER_KEY]||{};for(const [id,keys] of Object.entries(raw))monitorWorkerOrderByDesktop.set(id,Array.isArray(keys)?keys.map(String):[]);monitorWorkerOrderReady=true;if(monitorLastAiState)renderWorkers(monitorLastAiState);}); }

let monitorWorkerPointerInteractionActive = false;

let monitorDeferredWorkerRenderState = null;

let monitorWorkerPointerReleaseTimer = 0;

const MONITOR_WORKER_CLICK_SETTLE_MS = 550;
const MONITOR_WORKER_RENDER_MIN_INTERVAL_MS = 120;
let monitorWorkerRenderTimer = 0;
let monitorWorkerRenderPendingState = null;
let monitorWorkerRenderInFlight = false;
let monitorWorkerRenderLastAt = 0;

function flushDeferredMonitorWorkerRender() {

  if (monitorWorkerPointerInteractionActive || !monitorDeferredWorkerRenderState) return;

  const deferred = monitorDeferredWorkerRenderState;

  monitorDeferredWorkerRenderState = null;

  renderWorkers(deferred);

}

function settleMonitorWorkerPointerInteraction(delay = MONITOR_WORKER_CLICK_SETTLE_MS) {

  clearTimeout(monitorWorkerPointerReleaseTimer);

  monitorWorkerPointerReleaseTimer = setTimeout(() => {

    monitorWorkerPointerInteractionActive = false;

    flushDeferredMonitorWorkerRender();

  }, delay);

}

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

function monitorLocalLlmReadyState() {
  return String(monitorLocalLlmControlState?.state || "off").toLowerCase();
}

function monitorLocalLlmIsUsable(control = monitorLocalLlmControlState) {
  if (!control || String(control.state || "off").toLowerCase() !== "ready") return false;
  return monitorLocalOllamaModels(control).some(monitorLocalModelIsLoaded);
}

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

function monitorLocalLlmActivityText(control = monitorLocalLlmControlState) {
  const activity = control?.activity;
  if (!activity || typeof activity !== "object") return "대기";
  const raw = String(activity.status || "").toUpperCase();
  const labels = {
    QUEUED: "대기",
    DISCOVERING: "분석 중",
    PREPARING: "정리 중",
    RUNNING: "작업 중",
    SYNTHESIZING: "결과 정리 중",
    WAITING_APPROVAL: "승인 대기",
    APPLYING: "적용 중",
    COMPLETE: "완료",
    COMPLETED: "완료",
    SUCCEEDED: "완료",
    DONE: "완료",
    FAILED: "실패",
    REJECTED: "실패",
  };
  let label = labels[raw] || raw || "대기";
  const role = String(activity.role || "").toUpperCase();
  if (raw === "RUNNING") {
    if (role === "CODER") label = "CODER · 구현안 분석 중";
    else if (role === "CRITIC") label = "CRITIC · 오류/회귀 검토 중";
    else if (role === "JUDGE") label = "JUDGE · 대안 판정 중";
  } else if (raw === "SYNTHESIZING" && role === "JUDGE") {
    label = "JUDGE · 결과 정리 중";
  }
  const started = Number(activity.created || activity.updated || 0);
  if (!started) return label;
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - started));
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return label + " · " + mm + ":" + ss;
}

const monitorLocalLlmCommandState = {
  inFlight: false,
  generation: 0,
  pendingEnabled: null,
};

function monitorUpdateLocalLlmToggleButtons() {
  for (const button of document.querySelectorAll(".monitor-local-llm-toggle")) {
    monitorUpdateLocalLlmToggleButton(button);
  }
}

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

function renderWorkers(state) {
  monitorRenderDiagnostics.renderRequests += 1;
  if (!MONITOR_NODE_RENDER_ENABLED) return;

  monitorWorkerRenderPendingState = state;

  if (monitorWorkerPointerInteractionActive) {
    monitorDeferredWorkerRenderState = state;
    return;
  }

  if (monitorWorkerRenderTimer || monitorWorkerRenderInFlight) return;
  const elapsed = performance.now() - monitorWorkerRenderLastAt;
  const delay = Math.max(0, MONITOR_WORKER_RENDER_MIN_INTERVAL_MS - elapsed);
  monitorWorkerRenderTimer = setTimeout(() => {
    monitorWorkerRenderTimer = 0;
    const pendingState = monitorWorkerRenderPendingState;
    monitorWorkerRenderPendingState = null;
    if (!pendingState) return;
    monitorWorkerRenderInFlight = true;
    try {
      performMonitorWorkerRender(pendingState);
    } finally {
      monitorWorkerRenderInFlight = false;
      monitorWorkerRenderLastAt = performance.now();
      if (monitorWorkerRenderPendingState) renderWorkers(monitorWorkerRenderPendingState);
    }
  }, delay);
}

function performMonitorWorkerRender(state) {
  monitorRenderDiagnostics.renderRuns += 1;

  if (monitorWorkerPointerInteractionActive) {

    monitorDeferredWorkerRenderState = state;

    return;

  }

  monitorDeferredWorkerRenderState = null;

  let workers = [];

  let visible = [];

  try {

    workers = monitorWorkersProjectionForState(state);

    visible = workers.filter((worker) => isMonitorVisibleWorker(worker, state));

  } catch (error) {

    console.warn("DesktopWindow Monitor worker projection delayed", error);

    setMonitorStatus("ACT 실행 중 · 노드 계산 지연", false);

    return;

  }

  let browserDisplaySlots = new Map();

  let chatgptListDisplaySlots = new Map();

  try { browserDisplaySlots = monitorBrowserDisplaySlots(visible, state); }

  catch (error) { console.warn("DesktopWindow Monitor display-slot fallback", error); }

  try { chatgptListDisplaySlots = monitorListDisplaySlots(visible.filter((worker)=>classifyMonitorWorker(worker)==="chatgpt"), state); }

  catch (error) { console.warn("DesktopWindow Monitor list-slot fallback", error); }

    try { syncMonitorMinimizedNodeBadges(state); }
  catch (error) { console.warn("DesktopWindow Monitor minimized snapshot delayed", error); }
  if (MONITOR_NODE_RENDER_PROJECTION_ONLY) return;
  const nextWorkerDom = document.createDocumentFragment();

  monitorRoleByHwnd.clear();

  monitorWorkingByHwnd.clear();

  monitorPausedByHwnd.clear();

  for (const group of MONITOR_AGENT_GROUPS) {

    const groupDisplaySlots = group.key === "chatgpt" ? chatgptListDisplaySlots : browserDisplaySlots;

    const rawMembers = visible.filter((worker) => classifyMonitorWorker(worker) === group.key).sort((a, b) => {
      if (group.key === "local-llm") {
        const localLoaded = (worker) => {
          const runtime = worker?.llm_runtime && typeof worker.llm_runtime === "object" ? worker.llm_runtime : {};
          const state = String(worker?.llm_runtime_state || worker?.runtime_state || runtime.state || "").toUpperCase();
          return runtime.loaded === true || runtime.busy === true || ["LOADED", "BUSY"].includes(state);
        };
        const loadedDelta = Number(localLoaded(b)) - Number(localLoaded(a));
        if (loadedDelta) return loadedDelta;
      }

      const al=groupDisplaySlots.get(a?.__display_key)||"", bl=groupDisplaySlots.get(b?.__display_key)||"";

      const ap=monitorNodeIdentityParts(al), bp=monitorNodeIdentityParts(bl);

      if(ap.desktop&&bp.desktop){if(ap.desktop!==bp.desktop)return ap.desktop-bp.desktop;if(ap.nodeNumber!==bp.nodeNumber)return ap.nodeNumber-bp.nodeNumber;}

      return compareMonitorWorkers(a,b,state);

    });

    const members = group.key === "chatgpt" ? monitorGroupChatgptMembersForDisplay(rawMembers,state) : rawMembers;

    const section = document.createElement("section");

    section.className = "monitor-worker-group";

    section.dataset.group = group.key;

    const header = document.createElement("div");

    header.className = "monitor-worker-group-title";

      const headerLabel = document.createElement("span");

    headerLabel.className = "monitor-worker-group-label";

      headerLabel.textContent = group.label;

    header.append(headerLabel);
    const groupReady = group.key === "chatgpt"
      ? members.some((worker) => worker?.__kind !== "LLM_NODE")
      : members.some((worker) => monitorWorkerReadyForUse(worker, group.key));
    header.classList.toggle("is-ready", groupReady);

    if (group.key === "chatgpt") {

      const googleLaunch = document.createElement("button");

      googleLaunch.type = "button";

      googleLaunch.className = "monitor-provider-launch monitor-google-launch";

      googleLaunch.textContent = "G+";

      googleLaunch.title = "Google ChatGPT 새 창 열기";

      configureMonitorProviderLaunchButton(googleLaunch, "GOOGLE");

      const roleModes=document.createElement("span"); roleModes.className="monitor-role-mode-buttons";

      for(const [mode,label] of [["ORCHESTRATOR","O"],["COORDINATOR_1","C1"],["COORDINATOR_2","C2"],["EXEMPT","열외"]]) {

        const b=document.createElement("button"); b.type="button"; b.className=`monitor-role-mode monitor-role-mode-${mode.toLowerCase().replaceAll("_","-")}`; b.dataset.roleMode=mode; b.textContent=label; b.classList.toggle("selected",monitorRoleAssignMode===mode); b.title=`${label} 선택 후 ChatGPT 바 클릭`; b.addEventListener("pointerdown",(event)=>{ if(event.button!==0)return; event.preventDefault(); monitorSetRoleAssignMode(mode); }); b.addEventListener("click",(event)=>{ if(event.detail===0) monitorSetRoleAssignMode(mode); }); roleModes.append(b);

      }

      const launch = document.createElement("button");

      launch.type = "button";

      launch.className = "monitor-provider-launch";

      launch.textContent = "N+";

      configureMonitorProviderLaunchButton(launch, "NAVER");

      const actions=document.createElement("span"); actions.className="monitor-worker-group-actions"; actions.append(roleModes,googleLaunch,launch); header.append(actions);

    }

    if (group.key === "local-llm") {
      const summary = document.createElement("small");
      summary.className = "monitor-local-llm-summary";
      summary.textContent = monitorLocalLlmSummary();
      header.append(summary);
      const activity = document.createElement("span");
      activity.className = "monitor-local-llm-activity";
      activity.textContent = monitorLocalLlmActivityText();
      activity.title = "최근 Local LLM 작업 상태";
      header.append(activity);
      const actions = document.createElement("span");
      actions.className = "monitor-worker-group-actions";
      const openUi = document.createElement("button");
      openUi.type = "button";
      openUi.className = "monitor-local-llm-open-ui";
      openUi.textContent = "UI 열기";
      openUi.title = "7865 Local Agent UI를 새 창으로 엽니다.";
      openUi.addEventListener("click", () => {
        chrome.windows.create({ url: LOCAL_LLM_UI_URL, type: "popup", width: 1200, height: 820, focused: true });
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "monitor-local-llm-toggle";
      toggle.textContent = "켜기";
      toggle.addEventListener("click", async () => {
        if (monitorLocalLlmCommandState.inFlight) return;
        await monitorSetLocalLlmEnabled(monitorLocalLlmReadyState() !== "ready");
      });
      actions.append(openUi, toggle);
      header.append(actions);
      // The header is detached while it is built, so a document-wide refresh
      // cannot see its button yet.
      monitorUpdateLocalLlmToggleButton(toggle);
      void monitorEnsureLocalLlmControlStatus(false, false);
    }

    const rows = document.createElement("div");

    rows.className = "monitor-worker-group-rows";

    if (members.length === 0) {

      const empty = document.createElement("div");

      empty.className = "monitor-worker-empty";

      empty.textContent = "−";

      rows.append(empty);

    }

    for (const worker of members) {

      const row = document.createElement("div");

      row.className = "monitor-worker-row";
      const workerReady = monitorWorkerReadyForUse(worker, group.key);
      row.classList.toggle("is-ready", workerReady);
      row.classList.toggle("is-not-ready", !workerReady);

      const windowGroupMembers = Array.isArray(worker?.__window_group_members) ? worker.__window_group_members : [worker];

      const windowGroupConversationKeys = [...new Set(windowGroupMembers.map((item)=>String(item?.conversation_key||"").trim()).filter(Boolean))];

      const conversationKey = String(worker?.conversation_key || "").trim();

      if(windowGroupConversationKeys.length>1){ row.dataset.conversationKeys=JSON.stringify(windowGroupConversationKeys); row.classList.add("monitor-window-node-group"); }

      const ageIdentity = monitorAgeIdentityForWorkerGroup(windowGroupMembers, state);

      const ageConversationKey = ageIdentity.conversationKey || conversationKey;

      const nodeLocationState = monitorCanonicalPhysicalLocation(worker, state);

      const groupConversationKey = conversationKey;

      if (conversationKey && monitorSystemNodeKeys.has(conversationKey)) row.classList.add("monitor-system-node");

      if (conversationKey) row.dataset.conversationKey = conversationKey;

      if (ageConversationKey) {

        const ageing = Math.max(0, Math.min(100, Number(ageIdentity.ageing)||0));

        row.style.setProperty("--monitor-row-age", `${ageing}%`);

      }

      const conversationGroup = applyMonitorConversationGroupVisual(row, groupConversationKey, state);

      const currentAssignMode = String(monitorRoleAssignMode || "").toUpperCase();

      const projectedActNode = monitorActBrowserNode(worker, state);

      const currentWorkerRole = String(projectedActNode?.role || "").toUpperCase();

      const managedExemption = projectedActNode?.exemption || null;

      const managedRole = (managedExemption || currentWorkerRole === "EXEMPT") ? "EXEMPT" : currentWorkerRole;

      const persistentRoleClass = monitorPersistentRoleClass(currentWorkerRole);

      if (persistentRoleClass) row.classList.add(persistentRoleClass);

      if (projectedActNode?.organization_member === true && managedRole) {

        row.classList.add("monitor-act-managed", `monitor-act-role-${managedRole.toLowerCase().replaceAll("_", "-")}`);

      }

      const isCurrentRoleOccupant = Boolean(currentAssignMode && (currentWorkerRole === currentAssignMode || (currentAssignMode === "EXEMPT" && (managedExemption || currentWorkerRole === "EXEMPT"))));

      if (isCurrentRoleOccupant) row.classList.add("monitor-role-current-occupant");

      const identity = document.createElement("div");

      identity.className = "monitor-worker-identity";

      if (nodeLocationState?.status === "CHECKING") row.classList.add("monitor-node-checking");

      if (nodeLocationState?.status === "RECOVERY_REQUIRED") row.classList.add("monitor-node-recovery-required");

      const location = groupDisplaySlots.get(worker?.__display_key) || nodeLocationState?.label || resolveStableMonitorLocation(worker, state);

      const nodeReference = worker?.__kind === "LLM_NODE" ? "" : String(location || "").replace(/_$/, "");

      const nodeEndpoint = endpointForMonitorWorker(worker, state);

      const groupedNodeLabels = windowGroupMembers.map((item)=>String(groupDisplaySlots.get(item?.__display_key) || monitorCanonicalPhysicalLocation(item,state)?.label || "").trim()).filter((label)=>/^D\d+-\d+$/.test(label));

      const groupedSuffixes = [...new Set(groupedNodeLabels.map((label)=>Number(label.split("-")[1])).filter((value)=>Number.isInteger(value)&&value>0))].sort((a,b)=>a-b);

      const nodeVisualReference = groupedSuffixes.length>1 && groupedNodeLabels.length ? `${groupedNodeLabels[0].split("-")[0]}-${groupedSuffixes.join("/")}` : nodeReference;

      if (nodeReference) row.dataset.nodeRef = nodeReference;

      if (nodeReference) {

        const locationLabel = document.createElement("span");

        locationLabel.className = "monitor-worker-location";

        locationLabel.textContent = nodeVisualReference;

        locationLabel.title = nodeVisualReference===nodeReference?nodeReference:`${nodeVisualReference} · ${nodeReference}`;

        identity.append(locationLabel);

      }

      const endpoint = nodeEndpoint;

      const minimized = monitorEndpointIsMinimized(endpoint, worker, state);

      const profileId = String(ageIdentity.profileId || worker?.profile_id || "").toUpperCase();

      if (profileId === "GOOGLE" || profileId === "NAVER") {

        row.classList.add(profileId === "GOOGLE" ? "monitor-profile-google" : "monitor-profile-naver");

      } else {

        const name = document.createElement("span");

        name.className = "monitor-worker-name";

        name.textContent = cleanMonitorWorkerName(worker);

        identity.append(name);

      }

      const endpointTitle = monitorContextTitleDisplay(worker, state, endpoint);
      row.dataset.contextTitleLive = String(endpoint?.presence_state||"").toUpperCase()==="OPEN" ? String(endpoint?.title||"").trim() : "";
      row.dataset.contextTitleFallback = monitorWorkerContextTitle(worker,state,endpoint);

      if (endpointTitle) {

        const chatTitle = document.createElement("span");

        chatTitle.className = "monitor-worker-chat-title";

        chatTitle.textContent = endpointTitle;

        identity.append(chatTitle);

      }

      if (group.key === "chatgpt" && conversationKey) {

        const ghost=monitorGhostCache.get(conversationKey)||{};

        const rec=monitorContextTitleRecord(conversationKey);

        row.title = [row.title, monitorLifecycleTooltip(conversationKey,endpoint,ghost), rec.context_summary?`맥락 ${rec.context_summary}`:""].filter(Boolean).join("\n");

        attachMonitorContextTitleMenu(row,worker,state,endpoint);

        if(monitorContextTitlesReady && !rec.manual_locked) void refreshMonitorContextTitle(worker,state,endpoint,false);

      }

      if (conversationGroup) {

        row.title = `같은 대화 중복 · ${conversationGroup.count}개 창`;

      }

      const status = document.createElement("div");

      status.className = "monitor-worker-status";

      if (worker?.__kind === "LLM_NODE") {

        row.classList.add("monitor-llm-node-row");

        const llmStatus = String(worker?.status || "unavailable").toLowerCase();

        const runtimeState = String(worker?.llm_runtime_state || llmStatus).toUpperCase();

        row.classList.add("monitor-llm-state-" + runtimeState.toLowerCase().replaceAll("_", "-"));
        // READY means callable standby only for a local model.  It is not yet
        // resident in VRAM, unlike LOADING/LOADED/BUSY.
        row.classList.toggle("monitor-llm-local-ready", group.key === "local-llm"
          && runtimeState === "READY");

        row.title = `${String(worker?.name || worker?.label || "LLM")} · ${runtimeState}`;

        const detail = document.createElement("span");
        detail.className = "monitor-llm-runtime-detail";
        const presentation = monitorLlmRuntimePresentation(worker, workerReady);
        detail.textContent = presentation.label;
        status.append(detail);
        row.title = `${String(worker?.display_name || worker?.name || worker?.label || "LLM")} · ${presentation.label}${presentation.vramText}`;

      }

      if (nodeLocationState?.status === "CHAT_CHANGED") {

        row.classList.add("monitor-node-chat-changed");

        const changeControls=document.createElement("span"); changeControls.className="monitor-node-chat-change-controls";

        const restore=document.createElement("button"); restore.type="button"; restore.className="monitor-node-action monitor-node-restore"; restore.textContent="복구"; restore.title="이 노드가 원래 사용하던 챗으로 되돌리기"; restore.addEventListener("click",event=>{event.stopPropagation();void restoreMonitorNodeChatChange(worker,nodeLocationState,restore);});

        const approve=document.createElement("button"); approve.type="button"; approve.className="monitor-node-action monitor-node-approve"; approve.textContent="승인"; approve.title="현재 브라우저의 새 챗을 이 노드에 정식 매칭"; approve.addEventListener("click",event=>{event.stopPropagation();void approveMonitorNodeChatChange(worker,nodeLocationState,approve);});

        changeControls.append(restore,approve); status.append(changeControls);

      } else if (worker?.__kind !== "LLM_NODE" && nodeLocationState?.status === "RECOVERY_REQUIRED") {

        const recovery = document.createElement("span");

        recovery.className = "monitor-node-chat-change-controls";

        const checkButton = document.createElement("button");

        checkButton.type = "button";

        checkButton.className = "monitor-node-action monitor-node-approve";

        checkButton.textContent = "승인";

        checkButton.title = "현재 탭과 채팅키 결합을 이 노드의 현재 상태로 승인";

        checkButton.addEventListener("click", async (event) => {

          event.stopPropagation();

          checkButton.disabled = true;

          try { await refreshMonitorIdentityIndex(state, true); await refreshAiMonitor(); }

          finally { checkButton.disabled = false; }

        });

        recovery.append(checkButton);

        if (nodeLocationState.status === "RECOVERY_REQUIRED") {

          const restoreButton = document.createElement("button");

          restoreButton.type = "button";

          restoreButton.className = "monitor-node-action monitor-node-restore";

          restoreButton.textContent = "복구";

          restoreButton.title = "마지막으로 확인된 이 노드의 ChatGPT 대화를 복구";

          restoreButton.addEventListener("click", (event) => { event.stopPropagation(); void restoreMonitorDetachedTask(worker, restoreButton); });

          recovery.prepend(restoreButton);

        }

        status.append(recovery);

      }

      if (group.key === "chatgpt" && conversationKey) status.append(createMonitorContextContinueButton({ ...worker, conversation_key: conversationKey }));
      if(group.key==="chatgpt"&&conversationKey&&monitorRoleAssignMode){ row.classList.add("monitor-role-targetable"); row.addEventListener("click",(event)=>{if(event.target?.closest?.(".monitor-worker-off"))return;if(event.detail>1)return;void monitorApplyRoleMode(worker,state);}); }

      const connection = resolveWorkerConnectionState(worker, state);

      row.classList.add(`connection-${connection}`);

      row.setAttribute("data-connection", connection);

      if (worker?.__kind === "WIN" && monitorEndpointIsMinimized(endpoint, worker, state)) row.classList.add("monitor-worker-minimized");

      if (worker?.__kind === "TAB" && monitorEndpointIsMinimized(endpoint, worker, state)) row.classList.add("monitor-worker-parent-minimized");

      const resolvedLocation = monitorEndpointLocation(worker, state);

      rememberMonitorWorkerPlacement(worker, state, resolvedLocation);

      const hwnd = monitorResolvedWorkerHwnd(worker, state, resolvedLocation);
      if (monitorIsActionableCodexResource(worker)) {
        const codexProfileId = monitorCodexResourceProfile(worker);
        const runtimeState = String(worker?.llm_runtime_state || worker?.status || "OFFLINE").toUpperCase();
        row.classList.add("monitor-worker-resource-actionable");
        row.dataset.resourceAction = "codex";
        row.dataset.codexProfileId = codexProfileId;
        row.title = `${String(worker?.name || worker?.display_name || "CODEX")} · ${runtimeState} · 더블클릭: 열기`;
        row.addEventListener("dblclick", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          await activateMonitorCodexResource(worker, row);
        });
      }

      if (hwnd) {

        row.dataset.hwnd = hwnd;

        if (monitorHoveredHwnd === hwnd && !monitorSelectedHwnds.has(hwnd)) row.classList.add("monitor-worker-row-hovered");

        const rowDesktopId = String(resolvedLocation?.desktopId || "");

        if (rowDesktopId) row.dataset.desktopId = rowDesktopId;

        row.addEventListener("pointerdown", (event) => { if (monitorStructureOpen) return; beginMonitorWorkerRowPointerDrag(event); });

        if (group.key === "chatgpt" && conversationKey && conversationGroup?.count === 1) {

          const structureNode = monitorStructureNodeFromWorker(worker, state);

          row.draggable = Boolean(monitorStructureOpen && structureNode);

          if (row.draggable) row.classList.add("monitor-structure-draggable");

          row.addEventListener("dragstart", (event) => {
            if (!monitorStructureOpen || !structureNode) { event.preventDefault(); return; }
            monitorStructureUseNodeDragGhost(event);
            const text=JSON.stringify(structureNode); event.dataTransfer.effectAllowed="copy";
            event.dataTransfer.setData("application/x-dwm-structure-node",text); event.dataTransfer.setData("text/plain",text);
          });

        }

        row.addEventListener("click", (event) => { if (Date.now() < monitorWorkerRowSuppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);

        // Role styling is derived only from the current ACT authoritative role binding.

        row.classList.add("monitor-worker-locatable");

        row.removeAttribute("title");

        row.addEventListener("click", (event) => applyMonitorWindowHighlight(hwnd, (monitorSelectedHwnds.has(hwnd) || event.ctrlKey) ? { toggle: true } : {}));

        row.addEventListener("dblclick", async (event) => {

          event.preventDefault();

          event.stopPropagation();

          applyMonitorWindowHighlight(hwnd);

          row.classList.add("monitor-worker-switch-pending");

          try {

            const freshState = await monitorNative({ type: "getVirtualDesktops" });

            if (!freshState?.ok) throw new Error(freshState?.error || "데스크톱 상태 확인 실패");

            const desktopIds = Array.isArray(freshState.desktopIds) ? freshState.desktopIds : [];

            let index = -1;

            for (let i = 0; i < desktopIds.length; i += 1) {

              const scan = await monitorNative({ type: "getDesktopWindowHandles", desktopId: desktopIds[i], includeMonitorWindows: "true" });

              if (scan?.ok && Array.isArray(scan.hwnds) && scan.hwnds.map(String).includes(String(hwnd))) { index = i; break; }

            }

            if (index < 0) throw new Error("이 창의 실제 데스크톱 위치를 확인하지 못함");

            renderVirtualDesktops(freshState);

            const result = await monitorNative({ type: "switchVirtualDesktop", index });

            if (!result?.ok) throw new Error(result?.error || "데스크톱 전환 실패");

            renderVirtualDesktops(result);

            selectVirtualDesktopPreview(index);

            applyMonitorWindowHighlight(hwnd);

          } catch (error) { setMonitorStatus(`데스크톱 전환 실패 · ${error?.message || error}`, false); }

          finally { setTimeout(() => row.classList.remove("monitor-worker-switch-pending"), 350); }

        });

      }

      if (monitorHighlightedHwnd && hwnd === monitorHighlightedHwnd) row.classList.add("monitor-worker-selected");

      const workState = document.createElement("span");

      const work = resolveWorkerWorkState(worker, state);

      const liveEndpoint = Boolean(hwnd) && worker?.__kind === "WIN" && connection === "connected" ? monitorOpenEndpointForHwnd(hwnd, state) : null;
      const visualConversationKey = String(liveEndpoint?.conversation_key || conversationKey || ((hwnd && monitorWindowDesktopLocations.get(String(hwnd))?.conversationKey) || "")).trim();

      const liveWorking = Boolean(hwnd) && worker?.__kind === "WIN" && connection === "connected" && monitorHwndIsGenerating(hwnd, state);
      if (liveWorking) monitorWorkingByHwnd.add(hwnd);
      row.classList.toggle("monitor-worker-working", liveWorking);

      if (visualConversationKey && liveWorking) { monitorWorkedConversationKeys.add(visualConversationKey); monitorAcknowledgedPostWork.delete(visualConversationKey); }

      const postWorkWaiting = Boolean(visualConversationKey) && monitorIsPostWorkWaiting(work, visualConversationKey) && !liveWorking;

      const alertDetail = postWorkWaiting ? monitorChatAlertDetail(visualConversationKey) : null;

      if (hwnd && postWorkWaiting && connection === "connected") monitorPausedByHwnd.add(hwnd);

      const visualWork = liveWorking ? "running" : (monitorIsActivelyWorking(work) ? "" : work); const attentionEndpoint = endpointForMonitorWorker(worker, state); const directAttention = monitorDirectEndpointUserAttention(attentionEndpoint); const attentionRaw = directAttention || attentionEndpoint?.telemetry?.user_attention || attentionEndpoint?.metadata?.user_attention || attentionEndpoint?.metadata?.telemetry?.user_attention || null; const userAttentionDetail = monitorUserAttentionVisualDetail(attentionRaw); const visual = monitorWorkIconState(visualWork, connection, userAttentionDetail || alertDetail);

      workState.className = "monitor-work-state";

      if (visual.tone) workState.classList.add(`monitor-alert-tone-${visual.tone}`);

      globalThis.MonitorStatusIcon?.render?.(workState, visual);

      workState.title = userAttentionDetail ? userAttentionDetail.label : `${visual.label} · ${work}`;

      workState.setAttribute("aria-label", workState.title);

      if (alertDetail && visualConversationKey) workState.addEventListener("click", (event) => {

        event.preventDefault();

        event.stopPropagation();

        monitorAcknowledgePostWork(visualConversationKey, hwnd || "");

        if (hwnd) monitorPausedByHwnd.delete(String(hwnd));

        if (monitorLastAiState) renderWorkers(monitorLastAiState);

      });

      const currentActRole=String(projectedActNode?.role||"").toUpperCase();

      const currentActExemption=projectedActNode?.exemption||null;
      row.classList.toggle("monitor-worker-exempt",Boolean(currentActExemption||currentActRole==="EXEMPT"));

      if(conversationKey&&projectedActNode&&(currentActExemption||currentActRole==="EXEMPT"||MONITOR_ROLE_ADMIN_ROLES.includes(currentActRole))){

        const off=document.createElement("button"); off.type="button"; off.className=`monitor-worker-off monitor-worker-off-${currentActExemption||currentActRole==="EXEMPT"?"exempt":currentActRole.toLowerCase().replaceAll("_","-")}`; off.textContent="OFF"; off.title=currentActExemption||currentActRole==="EXEMPT"?"열외 해제 → 일반 WORKER":`${monitorRoleAdminShort(currentActRole)} 해제 → 일반 WORKER`; off.addEventListener("click",(event)=>{event.preventDefault();event.stopPropagation();void monitorTurnWorkerOff(worker,state);}); status.append(off);

      }

      status.append(workState);

      row.append(identity, status);

      rows.append(row);

    }

    section.append(header, rows);

    nextWorkerDom.append(section);

  }

  for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const hwnd = preview.dataset.hwnd || "";

    applyPersistentMonitorRoleClass(preview, hwnd);

    syncMonitorPauseOverlay(preview, hwnd);

  }

  monitorWorkers.replaceChildren(nextWorkerDom);

  // The BCT list owns this panel whenever it is enabled. A concurrent ACT
  // refresh must not replace it after Chrome has selected a real tab, because
  // that would erase the exact row selection just mirrored from Chrome.
  if (MONITOR_BCT_NODE_SUMMARY_ENABLED && Array.isArray(monitorBctWindowNodesCache)) {
    renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
    syncMonitorBctNodeTargetHighlight();
  }

  if(monitorClosedRecoveryMenu){monitorClosedRecoveryMenu.hidden=!monitorRecoveryPickerState.isOpen();if(monitorRecoveryPickerState.isOpen())monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(state));}

}

function positionMonitorTrashRecoveryMenu(){

  if(!monitorClosedRecoveryMenu||!monitorNodeTrash)return; const r=monitorNodeTrash.getBoundingClientRect();

  const width=Math.min(760,Math.max(420,window.innerWidth-24)); const left=Math.max(12,Math.min(window.innerWidth-width-12,r.right-width));

  const bottom=Math.max(12,window.innerHeight-r.top+8); const available=Math.max(180,r.top-18);

  monitorClosedRecoveryMenu.style.width=`${width}px`; monitorClosedRecoveryMenu.style.left=`${left}px`; monitorClosedRecoveryMenu.style.right="auto"; monitorClosedRecoveryMenu.style.top="auto"; monitorClosedRecoveryMenu.style.bottom=`${bottom}px`; monitorClosedRecoveryMenu.style.height=`${available}px`; monitorClosedRecoveryMenu.style.setProperty("max-height",`${available}px`,"important");

}

if (monitorNodeTrash && monitorClosedRecoveryMenu) {

  monitorNodeTrash.style.cursor="pointer";

  monitorNodeTrash.addEventListener("click",(event)=>{if(monitorNodeTrash.classList.contains("monitor-node-trash-drop-target")||monitorNodeTrash.classList.contains("monitor-node-trash-drop-success"))return;event.stopPropagation();monitorRecoveryPickerState.toggle();monitorClosedRecoveryMenu.hidden=!monitorRecoveryPickerState.isOpen();if(monitorRecoveryPickerState.isOpen()){positionMonitorTrashRecoveryMenu();if(monitorLastAiState)monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));}});

  monitorClosedRecoveryMenu.addEventListener("pointerdown",()=>{clearTimeout(monitorWorkerPointerReleaseTimer);monitorWorkerPointerInteractionActive=true;},true);

  monitorClosedRecoveryMenu.addEventListener("click",()=>settleMonitorWorkerPointerInteraction(),true);

  window.addEventListener("resize",()=>{if(monitorRecoveryPickerState.isOpen())positionMonitorTrashRecoveryMenu();});

  document.addEventListener("pointerdown",(event)=>{if(!monitorRecoveryPickerState.isOpen())return;if(event.target.closest?.("#monitorNodeTrash,#monitorClosedRecoveryMenu"))return;monitorRecoveryPickerState.close();monitorClosedRecoveryMenu.hidden=true;},true);

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

function stopMonitorBctNativePreview() {
  const token = monitorBctNativePreviewToken;
  monitorBctNativePreviewToken = "";
  if (token) void monitorNative({ type:"monitorDragPreviewStop", token }).catch(() => {});
}

let monitorBctNodeReorderPending = false;
let monitorBctCurrentSessionWindowHwnd = new Map();
let monitorBctDisplayWindowHwnd = new Map();
let monitorBctBrowserWindows = new Map();
let monitorNodePanelRefreshController = null;
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
const MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS = Object.freeze([0, 450, 1400]);

function scheduleMonitorMinimizedBadgeConvergence(hwnd) {
  const key = String(hwnd || "").trim();
  if (!key || !Array.isArray(monitorBctWindowNodesCache)) return;
  if (monitorMinimizedBadgeConvergenceTimer) return;
  monitorMinimizedBadgeConvergenceTimer = setTimeout(async () => {
    monitorMinimizedBadgeConvergenceTimer = 0;
    // A BCT-initiated minimize can arrive before the Native identity snapshot.
    // Reconcile once; this is deliberately bounded, not a background poll.
    await refreshMonitorBctBrowserWindowGeometry();
    await refreshMonitorIdentityIndex(monitorLastAiState, true).catch(() => false);
    refreshMonitorBctCurrentSessionWindowHwnd();
    refreshMonitorBctDisplayWindowHwnd();
    syncMonitorMinimizedNodeBadges(monitorLastAiState);
  }, 250);
}
if (monitorWorkers) monitorWorkers.dataset.columns = "3";

function resetMonitorBctProjectionConvergence() {
  monitorBctProjectionGeneration += 1;
  monitorBctThumbnailProjectionAttemptKeys = new Set();
  monitorBctProjectionConvergenceKey = "";
  monitorBctProjectionConvergenceAttempt = 0;
  if (monitorBctProjectionConvergenceTimer) {
    clearTimeout(monitorBctProjectionConvergenceTimer);
    monitorBctProjectionConvergenceTimer = 0;
  }
}

async function refreshMonitorBctThumbnailProjectionForDesktop(desktopId) {
  if (!Array.isArray(monitorBctWindowNodesCache) || !monitorBctWindowNodesCache.length) return false;

  // Native thumbnail capture and the RCC/Chrome snapshot arrive independently.
  // Resolve once while this desktop's HWND geometry is fresh so the semantic
  // N-label is attached to the real browser rectangle rather than to a node card.
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  if (!monitorBctProjectionHasUnresolvedLineage()) return true;

  const chromeLocations = [...monitorWindowDesktopLocations.values()].filter((location) =>
    String(location?.desktopId || "") === String(desktopId || "") &&
    String(location?.className || "") === "Chrome_WidgetWin_1" &&
    Number(location?.width) > 0 && Number(location?.height) > 0
  );
  if (!chromeLocations.length) return false;

  const locationKey = chromeLocations.map((location) =>
    `${location.hwnd}:${location.left}:${location.top}:${location.width}:${location.height}:${location.iconic ? 1 : 0}`
  ).sort().join(",");
  const attemptKey = `${monitorBctProjectionGeneration}:${desktopId}:${locationKey}`;
  if (monitorBctThumbnailProjectionAttemptKeys.has(attemptKey)) return false;
  monitorBctThumbnailProjectionAttemptKeys.add(attemptKey);
  if (monitorBctThumbnailProjectionAttemptKeys.size > 24) {
    monitorBctThumbnailProjectionAttemptKeys = new Set([attemptKey]);
  }

  await refreshMonitorBctBrowserWindowGeometry();
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  return !monitorBctProjectionHasUnresolvedLineage();
}

function monitorBctProjectionHasUnresolvedLineage() {
  return Array.isArray(monitorBctWindowNodesCache) && monitorBctWindowNodesCache.some((node) =>
    !monitorBctDisplaySessionHwnd(node.windowId, node.instanceId, node.sessionId)
  );
}

function scheduleMonitorBctProjectionConvergence(reason = "state-ready") {
  if (!Array.isArray(monitorBctWindowNodesCache) || !monitorBctWindowNodesCache.length ||
      !Array.isArray(monitorDesktopState?.desktopIds) || !monitorDesktopState.desktopIds.length ||
      !monitorBctProjectionHasUnresolvedLineage()) return;
  const key = [
    monitorBctProjectionGeneration,
    monitorDesktopState.desktopIds.join(","),
    ...monitorBctWindowNodesCache.map((node) =>
      `${node.instanceId}:${node.sessionId}:${node.windowId}:${node.conversationKey}:${node.active ? 1 : 0}:${node.instanceState}`
    ),
  ].join("|");
  if (key !== monitorBctProjectionConvergenceKey) {
    monitorBctProjectionConvergenceKey = key;
    monitorBctProjectionConvergenceAttempt = 0;
  }
  if (monitorBctProjectionConvergenceTimer || monitorBctProjectionConvergenceInflight ||
      monitorBctProjectionConvergenceAttempt >= MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS.length) return;
  const delay = MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS[monitorBctProjectionConvergenceAttempt];
  monitorBctProjectionConvergenceTimer = setTimeout(async () => {
    monitorBctProjectionConvergenceTimer = 0;
    monitorBctProjectionConvergenceAttempt += 1;
    monitorBctProjectionConvergenceInflight = true;
    try {
      await refreshMonitorBctBrowserWindowGeometry();
      await refreshMonitorIdentityIndex(monitorLastAiState, true).catch(() => false);
      refreshMonitorBctCurrentSessionWindowHwnd();
      refreshMonitorBctDisplayWindowHwnd();
      renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
      syncMonitorAllDesktopThumbnailNodeBadges();
    } finally {
      monitorBctProjectionConvergenceInflight = false;
    }
    if (monitorBctProjectionHasUnresolvedLineage()) scheduleMonitorBctProjectionConvergence(reason);
  }, delay);
}

function monitorBctRenameErrorText(error) { return globalThis.MonitorDomainAPIs["conversations"]["monitorBctRenameErrorText"].apply(this, arguments); }
let monitorBctRenameEditor = null;

function closeMonitorBctRenameEditor() {
  if (!monitorBctRenameEditor || monitorBctRenameEditor.busy) return;
  monitorBctRenameEditor.overlay.remove();
  monitorBctRenameEditor = null;
}

function openMonitorTrashRecovery() {
  if (!monitorNodeTrash || !monitorClosedRecoveryMenu) return;
  if (!monitorRecoveryPickerState.isOpen()) monitorNodeTrash.click();
}

function monitorBctRoleTagsFromText(value) { return globalThis.MonitorDomainAPIs["conversations"]["monitorBctRoleTagsFromText"].apply(this, arguments); }

function monitorBctNodeRoleSummary(node) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorBctNodeRoleSummary"].apply(this, arguments); }

function monitorBctNodeLocationText(node, desktopPosition) {
  return desktopPosition >= 0 ? `D${desktopPosition + 1}` : "위치 확인 중";
}
function openMonitorBctRenameEditor(node, row) {
  if (!monitorBctShell?.updateConversationScope || !node?.conversationKey) {
    setMonitorStatus("이 대화의 영속 신원을 확인할 수 없어 정보를 바꾸지 않았습니다.", false, 5000);
    return;
  }
  const canRenameTitle = Boolean(
    monitorBctShell?.renameConversation
    && node?.sessionId
    && node?.windowId !== undefined
    && node?.tabId !== undefined
  );
  closeMonitorBctRenameEditor();
  const overlay = document.createElement("div");
  overlay.className = "monitor-bct-rename-overlay";
  const dialog = document.createElement("form");
  dialog.className = "monitor-bct-rename-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "대화 정보와 이름 변경");
  const head = document.createElement("div");
  head.className = "monitor-bct-rename-head";
  const heading = document.createElement("strong");
  heading.textContent = `${node.nodeLabel || "N?"} · 대화 정보`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "monitor-bct-rename-close";
  close.setAttribute("aria-label", "취소");
  close.textContent = "×";
  head.append(heading, close);
  let currentTitle = String(node.title || "").trim();
  const facts = document.createElement("div");
  facts.className = "monitor-bct-node-facts";
  const fact = (label, value) => {
    const line = document.createElement("div");
    const key = document.createElement("b");
    const text = document.createElement("span");
    key.textContent = label;
    text.textContent = value || "-";
    line.append(key, text);
    facts.append(line);
  };
  fact("대화 UUID", String(node.conversationKey || ""));
  fact("현재 위치", row?.querySelector?.(".monitor-bct-node-location")?.textContent || "확인 중");
  fact("연결", `창 ${node.windowId} · 탭 ${node.tabId}`);
  fact("실제 추론 수준", String(node.reasoningLevel || "확인 불가"));

  const makeField = (labelText, value, maximum, placeholder = "") => {
    const label = document.createElement("label");
    label.className = "monitor-bct-info-field";
    const caption = document.createElement("span");
    caption.textContent = labelText;
    const control = document.createElement("input");
    control.className = "monitor-bct-rename-input";
    control.type = "text";
    control.maxLength = maximum;
    control.value = value;
    control.placeholder = placeholder;
    control.autocomplete = "off";
    label.append(caption, control);
    return { label, control };
  };
  const titleField = makeField("ChatGPT 대화창 이름", currentTitle, 100);
  const titleHint = document.createElement("div");
  titleHint.className = "monitor-bct-info-hint";
  titleHint.textContent = canRenameTitle
    ? "이름 변경은 확인된 현재 ChatGPT 탭에만 적용됩니다."
    : "현재 정확한 탭 신원을 확인하지 못해 이름 변경만 잠시 사용할 수 없습니다. 대화망과 역할은 변경할 수 있습니다.";
  titleField.control.disabled = !canRenameTitle;
  const scopeField = makeField(
    "대화망 / 작업 범위",
    String(node.scopeName || "").trim(),
    120,
    "비우면 미소속",
  );
  const rolesField = makeField(
    "역할 태그",
    Array.isArray(node.roleTags) ? node.roleTags.join(", ") : "",
    400,
    "예: Manager, 구현, CI",
  );
  const roleHint = document.createElement("div");
  roleHint.className = "monitor-bct-info-hint";
  roleHint.textContent = "Manager는 안내용 역할 태그입니다. 0명 또는 여러 명이어도 기능과 권한은 제한되지 않습니다.";
  const error = document.createElement("div");
  error.className = "monitor-bct-rename-error";
  error.setAttribute("aria-live", "polite");
  const actions = document.createElement("div");
  actions.className = "monitor-bct-rename-actions";
  const recovery = document.createElement("button");
  recovery.type = "button";
  recovery.className = "monitor-bct-open-recovery";
  recovery.textContent = "복구 보관함";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "취소";
  const confirm = document.createElement("button");
  confirm.type = "submit";
  confirm.className = "is-primary";
  confirm.textContent = "확인";
  actions.append(recovery, cancel, confirm);
  dialog.append(head, facts, titleField.label, titleHint, scopeField.label, rolesField.label, roleHint, error, actions);
  overlay.append(dialog);
  document.body.append(overlay);
  monitorBctRenameEditor = {
    overlay, dialog, input: titleField.control, scopeInput: scopeField.control,
    rolesInput: rolesField.control, error, recovery, cancel, close, confirm, busy: false,
    canRenameTitle,
  };

  const cancelEditor = () => closeMonitorBctRenameEditor();
  close.addEventListener("click", cancelEditor);
  cancel.addEventListener("click", cancelEditor);
  recovery.addEventListener("click", () => {
    if (monitorBctRenameEditor?.busy) return;
    overlay.remove();
    monitorBctRenameEditor = null;
    openMonitorTrashRecovery();
  });
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) cancelEditor();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelEditor();
    }
  });
  dialog.addEventListener("submit", async (event) => {
    event.preventDefault();
    const editor = monitorBctRenameEditor;
    if (!editor || editor.busy) return;
    const title = editor.canRenameTitle ? editor.input.value.trim() : currentTitle;
    const scopeName = editor.scopeInput.value.trim();
    const roleTags = monitorBctRoleTagsFromText(editor.rolesInput.value);
    if (editor.canRenameTitle && !title) {
      editor.error.textContent = "이름을 입력하세요.";
      editor.input.focus();
      return;
    }
    const titleChanged = editor.canRenameTitle && title !== currentTitle;
    const metadataChanged = scopeName !== String(node.scopeName || "").trim()
      || JSON.stringify(roleTags) !== JSON.stringify(Array.isArray(node.roleTags) ? node.roleTags : []);
    if (!titleChanged && !metadataChanged) return closeMonitorBctRenameEditor();
    editor.busy = true;
    editor.input.disabled = true;
    editor.scopeInput.disabled = true;
    editor.rolesInput.disabled = true;
    editor.recovery.disabled = true;
    editor.cancel.disabled = true;
    editor.close.disabled = true;
    editor.confirm.disabled = true;
    editor.confirm.textContent = "변경 중…";
    editor.error.textContent = "";
    let titleApplied = false;
    try {
      if (titleChanged) {
        await monitorBctShell.renameConversation(node, title);
        row.querySelector(".monitor-bct-node-title").textContent = title;
        currentTitle = title;
        titleApplied = true;
      }
      await monitorBctShell.updateConversationScope(node, {
        displayName: title || String(node.title || node.nodeLabel || "").trim(),
        scopeName,
        roleTags,
      });
      editor.overlay.remove();
      monitorBctRenameEditor = null;
      setMonitorStatus(`대화 정보${titleChanged ? "와 실제 ChatGPT 이름" : ""}을 저장했습니다.`, true, 3500);
      globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 600);
    } catch (renameError) {
      editor.busy = false;
      editor.input.disabled = !editor.canRenameTitle;
      editor.scopeInput.disabled = false;
      editor.rolesInput.disabled = false;
      editor.recovery.disabled = false;
      editor.cancel.disabled = false;
      editor.close.disabled = false;
      editor.confirm.disabled = false;
      editor.confirm.textContent = "확인";
      editor.error.textContent = titleApplied
        ? `ChatGPT 이름은 변경됐지만 대화망 정보 저장에 실패했습니다 · ${renameError?.message || renameError}`
        : monitorBctRenameErrorText(renameError);
      (titleApplied || !editor.canRenameTitle ? editor.scopeInput : editor.input).focus();
    }
  });
  const initialControl = canRenameTitle ? titleField.control : scopeField.control;
  initialControl.focus();
  initialControl.select();
}

let monitorBctNodeInteractionService = null;
const monitorBctCollapsedScopes = new Set();
let monitorBctSuppressedClickKey = "";
let monitorBctSuppressScopeClickUntil = 0;

function installMonitorBctManagerLongPress(row, node) {
  let timer = 0;
  let startX = 0;
  let startY = 0;
  const cancel = () => {
    if (timer) clearTimeout(timer);
    timer = 0;
    row.classList.remove("monitor-bct-manager-hold");
  };
  row.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button,input")) return;
    startX = event.clientX;
    startY = event.clientY;
    row.classList.add("monitor-bct-manager-hold");
    timer = setTimeout(() => {
      timer = 0;
      row.classList.remove("monitor-bct-manager-hold");
      const key = monitorBctNodeSelectionKey(node);
      monitorBctSuppressedClickKey = key;
      globalThis.setTimeout(() => {
        if (monitorBctSuppressedClickKey === key) monitorBctSuppressedClickKey = "";
      }, 900);
      if (!node.scopeName) {
        setMonitorStatus("먼저 우클릭 정보창에서 이 대화의 작업 범위를 지정하세요.", false, 3500);
        return;
      }
      const tags = Array.isArray(node.roleTags) ? [...node.roleTags] : [];
      const hadManager = tags.includes("Manager");
      const nextTags = hadManager ? tags.filter((tag) => tag !== "Manager") : [...tags, "Manager"];
      row.classList.toggle("is-manager", !hadManager);
      void monitorBctShell.updateConversationScope(node, {
        displayName: node.title,
        scopeName: node.scopeName,
        roleTags: nextTags,
      }).then(() => {
        setMonitorStatus(
          `${node.nodeLabel || "N?"}의 Manager 안내 태그를 ${hadManager ? "해제했습니다" : "붙였습니다"}.`,
          true,
          2800,
        );
        globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 250);
      }).catch((error) => {
        row.classList.toggle("is-manager", hadManager);
        setMonitorStatus(`Manager 태그 저장 실패 · ${error?.message || error}`, false, 4000);
      });
    }, 600);
  });
  row.addEventListener("pointermove", (event) => {
    if (timer && Math.hypot(event.clientX - startX, event.clientY - startY) > 7) cancel();
  });
  row.addEventListener("pointerup", cancel);
  row.addEventListener("pointercancel", cancel);
  row.addEventListener("dragstart", cancel);
}

function getMonitorBctNodeInteractionService() {
  if (monitorBctNodeInteractionService) return monitorBctNodeInteractionService;
  if (!globalThis.MonitorBctNodeInteraction?.create) throw new Error("BCT 노드 이동 모듈을 불러오지 못함");
  monitorBctNodeInteractionService = globalThis.MonitorBctNodeInteraction.create({
    nativeRequest: monitorNative,
    renderVirtualDesktops,
    selectVirtualDesktopPreview,
    highlight: applyMonitorBctNodeHighlight,
    focusBrowserTab: async (target) => chrome.runtime.sendMessage({
      type: "monitor-focus-exact-chat-tab",
      tabId: target?.tabId,
      windowId: target?.windowId,
      conversationKey: target?.conversationKey,
    }),
  });
  return monitorBctNodeInteractionService;
}

async function resolveMonitorBctNodeHwnd(node) {
  let hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (hwnd) return String(hwnd);
  await refreshMonitorIdentityIndex(monitorLastAiState, true);
  refreshMonitorBctCurrentSessionWindowHwnd();
  hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (!hwnd) throw new Error("현재 세션에서 이 노드와 웹브라우저 창을 정확히 대조하지 못함");
  return String(hwnd);
}

async function resolveMonitorBctNodeDisplayHwnd(node) {
  let hwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (hwnd) return String(hwnd);
  await refreshMonitorBctBrowserWindowGeometry();
  await refreshMonitorIdentityIndex(monitorLastAiState, true);
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  hwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (!hwnd) throw new Error("현재 세션에서 이 노드의 표시 위치를 고유하게 대조하지 못함");
  return String(hwnd);
}

function compareMonitorBctNodeDisplayOrder(left, right) { return globalThis.MonitorDomainAPIs["node-identity"]["compareMonitorBctNodeDisplayOrder"].apply(this, arguments); }

function monitorUniqueBctConversationNodes(nodes) {
  const uniqueNodes = new Map();
  for (const candidate of Array.isArray(nodes) ? nodes : []) {
    const conversationKey = String(candidate?.conversationKey || "").trim().toLowerCase();
    const identity = conversationKey
      ? `conversation:${conversationKey}`
      : `tab:${monitorBctNodeSelectionKey(candidate)}`;
    const previous = uniqueNodes.get(identity);
    const candidateRank = (candidate?.instanceState === "OPEN" && !candidate?.displayStale ? 4 : 0)
      + (candidate?.active === true ? 2 : 0);
    const previousRank = (previous?.instanceState === "OPEN" && !previous?.displayStale ? 4 : 0)
      + (previous?.active === true ? 2 : 0);
    if (!previous || candidateRank > previousRank ||
        (candidateRank === previousRank && (candidate?.tabIndex ?? Number.MAX_SAFE_INTEGER) <
          (previous?.tabIndex ?? Number.MAX_SAFE_INTEGER))) uniqueNodes.set(identity, candidate);
  }
  return [...uniqueNodes.values()];
}

function renderMonitorBctWindowNodes(nodes) {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorWorkers) return;
  // A background refresh may replace the captured row while the mouse is down.
  // Cancel before detaching it, so no ghost or draggable visual state survives.
  if (monitorBctPointerDrag) cancelMonitorBctNodePointerDrag({ pointerId: monitorBctPointerDrag.pointerId });
  nodes = monitorUniqueBctConversationNodes(nodes);
  const fragment = document.createDocumentFragment();
  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "monitor-bct-node-empty";
    empty.textContent = "현재 RCC에서 확인된 ChatGPT 창이 없습니다.";
    fragment.append(empty);
  }
  const groups = new Map();
  for (const node of nodes) {
    const key = node.scopeId || "__unassigned__";
    if (!groups.has(key)) groups.set(key, {
      key,
      name: node.scopeName || "미소속 대화",
      nodes: [],
    });
    groups.get(key).nodes.push(node);
  }
  // Keep a real destination for returning a node even when no conversation is
  // currently unassigned. The heading is not a drop target; the list below is.
  if (!groups.has("__unassigned__")) groups.set("__unassigned__", {
    key: "__unassigned__",
    name: "미소속 대화",
    nodes: [],
  });
  const orderedGroups = [...groups.values()].sort((left, right) =>
    Number(left.key === "__unassigned__") - Number(right.key === "__unassigned__") ||
    left.name.localeCompare(right.name, "ko"));
  for (const group of orderedGroups) {
    const physicalOrder = new Map(group.nodes.map((node) => {
      const hwnd = monitorDisplayHwndForBrowserWindowId(
        node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
      const location = hwnd ? monitorWindowDesktopLocations.get(hwnd) : null;
      const desktopPosition = location
        ? monitorDesktopState.desktopIds.indexOf(String(location.desktopId || ""))
        : -1;
      return [monitorBctNodeSelectionKey(node), [
        desktopPosition >= 0 ? desktopPosition : Number.MAX_SAFE_INTEGER,
        location ? Number(location.top || 0) : Number.MAX_SAFE_INTEGER,
        location ? Number(location.left || 0) : Number.MAX_SAFE_INTEGER,
        location ? Number(location.z || 0) : Number.MAX_SAFE_INTEGER,
        Number(node.windowId || Number.MAX_SAFE_INTEGER),
        node.tabIndex ?? Number.MAX_SAFE_INTEGER,
        Number(node.tabId || Number.MAX_SAFE_INTEGER),
      ]];
    }));
    group.nodes.sort((left, right) => {
      const leftManual = Number(left.displayOrder || 0);
      const rightManual = Number(right.displayOrder || 0);
      if (leftManual > 0 || rightManual > 0) {
        if (leftManual <= 0) return 1;
        if (rightManual <= 0) return -1;
        if (leftManual !== rightManual) return leftManual - rightManual;
      }
      const leftPhysical = physicalOrder.get(monitorBctNodeSelectionKey(left)) || [];
      const rightPhysical = physicalOrder.get(monitorBctNodeSelectionKey(right)) || [];
      for (let index = 0; index < Math.max(leftPhysical.length, rightPhysical.length); index += 1) {
        const difference = Number(leftPhysical[index] || 0) - Number(rightPhysical[index] || 0);
        if (difference) return difference;
      }
      return compareMonitorBctNodeDisplayOrder(left, right);
    });
    const groupSection = document.createElement("section");
    groupSection.className = "monitor-bct-scope-group";
    groupSection.dataset.scopeId = group.key;
    const groupHeader = document.createElement("button");
    groupHeader.type = "button";
    groupHeader.className = "monitor-bct-scope-heading";
    groupHeader.dataset.scopeId = group.key;
    groupHeader.setAttribute("aria-expanded", monitorBctCollapsedScopes.has(group.key) ? "false" : "true");
    const groupCaret = document.createElement("span");
    groupCaret.className = "monitor-bct-scope-caret";
    groupCaret.setAttribute("aria-hidden", "true");
    const groupText = document.createElement("span");
    groupText.textContent = `${group.name} · ${group.nodes.length}`;
    groupHeader.append(groupCaret, groupText);
    groupHeader.addEventListener("click", (event) => {
      if (monitorBctPointerDrag?.active || Date.now() < monitorBctSuppressScopeClickUntil) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (monitorBctCollapsedScopes.has(group.key)) monitorBctCollapsedScopes.delete(group.key);
      else monitorBctCollapsedScopes.add(group.key);
      renderMonitorBctWindowNodes(nodes);
    });
    const groupList = document.createElement("div");
    groupList.className = "monitor-bct-node-list";
    groupList.dataset.scopeId = group.key;
    groupList.dataset.scopeName = group.key === "__unassigned__" ? "" : group.name;
    groupSection.append(groupHeader, groupList);
    fragment.append(groupSection);
    if (monitorBctCollapsedScopes.has(group.key)) {
      groupList.hidden = true;
      continue;
    }
    if (!group.nodes.length) {
      const emptyDrop = document.createElement("div");
      emptyDrop.className = "monitor-bct-node-empty monitor-bct-node-drop-empty";
      emptyDrop.textContent = "여기에 놓으면 미소속";
      groupList.append(emptyDrop);
    }
    for (const [index, node] of group.nodes.entries()) {
    const row = document.createElement("article");
    row.className = "monitor-bct-node-row";
    row.dataset.tabId = String(node.tabId);
    row.dataset.windowId = String(node.windowId);
    row.dataset.instanceId = String(node.instanceId || "");
    row.dataset.sessionId = String(node.sessionId || "");
    row.dataset.nodeIndex = String(index + 1);
    row.dataset.nodeLabel = node.nodeLabel || "";
    row.dataset.conversationKey = node.conversationKey;
    row.dataset.scopeId = node.scopeId || "";
    row.setAttribute("role", "button");
    row.setAttribute("aria-selected", String(node.active === true));
    if (node.displayStale || node.instanceState !== "OPEN") row.classList.add("monitor-bct-node-stale");
    row.tabIndex = 0;
    row.draggable = false;
    const mappedHwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
    const nativeLocation = mappedHwnd ? monitorWindowDesktopLocations.get(mappedHwnd) : null;
    const desktopPosition = nativeLocation
      ? monitorDesktopState.desktopIds.indexOf(String(nativeLocation.desktopId || ""))
      : -1;
    row.title = node.conversationKey
      ? "클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동하고 정확한 대화 선택 · 우클릭: 정보와 이름 변경 · 600ms 길게 누르기: Manager 안내 태그 지정/해제"
      : "클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동";
    const number = document.createElement("span");
    number.className = "monitor-bct-node-number";
    number.textContent = node.nodeLabel || "N?";
    number.title = node.nodeLabel
      ? "BCT 대화망에 등록된 표시 전용 번호"
      : "관측됨 · 대화망 등록 전이라 표시 번호가 없습니다";

    const body = document.createElement("span");
    body.className = "monitor-bct-node-body";
    const title = document.createElement("strong");
    title.className = "monitor-bct-node-title";
    title.textContent = node.title;
    body.append(title);
    const location = document.createElement("small");
    location.className = "monitor-bct-node-location";
    location.textContent = monitorBctNodeLocationText(node, desktopPosition);
    location.title = location.textContent;
    body.append(location);
    const presence = document.createElement("span");
    const stale = node.displayStale === true || node.instanceState !== "OPEN";
    presence.className = `monitor-bct-node-presence${!stale && node.generating === true ? " is-busy" : ""}`;
    presence.setAttribute("aria-label", stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음");
    presence.title = stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음";
    globalThis.MonitorStatusIcon?.render?.(presence, { activity: !stale && node.generating === true ? "play" : "pause" });
    row.append(number, body, presence);
    row.classList.toggle("is-manager", Array.isArray(node.roleTags) && node.roleTags.includes("Manager"));
    installMonitorBctManagerLongPress(row, node);
    row.addEventListener("dragstart", (event) => event.preventDefault());
    row.addEventListener("pointerdown", (event) => beginMonitorBctNodePointerDrag(event, row, node));
    row.addEventListener("click", (event) => {
      if (monitorBctSuppressedClickKey === monitorBctNodeSelectionKey(node)) {
        monitorBctSuppressedClickKey = "";
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      void resolveMonitorBctNodeDisplayHwnd(node).then((hwnd) => {
        monitorNodePanelSelection.set(monitorBctNodeSelectionKey(node));
        getMonitorBctNodeInteractionService().select(hwnd);
        setMonitorStatus(`${node.nodeLabel || "N?"} 연결 웹브라우저 창을 표시했습니다.`, true, 1800);
      }).catch((error) => {
        setMonitorStatus(`연결 창 표시 실패 · ${error?.message || error}`, false, 3500);
      });
    });
    row.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("monitor-bct-node-switch-pending");
      void resolveMonitorBctNodeHwnd(node).then((hwnd) => (
        monitorNodePanelSelection.set(monitorBctNodeSelectionKey(node)),
        getMonitorBctNodeInteractionService().activate(hwnd, {
          tabId: node.tabId,
          windowId: node.windowId,
          conversationKey: node.conversationKey,
        })
      )).then((result) => {
        setMonitorStatus(`${node.nodeLabel || "N?"} 창이 있는 D${result.index + 1}(으)로 이동해 정확한 ChatGPT 탭을 선택했습니다.`, true, 3200);
      }).catch((error) => {
        setMonitorStatus(`노드 창 이동 실패 · ${error?.message || error}`, false, 4500);
      }).finally(() => {
        globalThis.setTimeout(() => row.classList.remove("monitor-bct-node-switch-pending"), 350);
      });
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      row.click();
    });
    if (node.conversationKey) {
      row.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        openMonitorBctRenameEditor(node, row);
      });
    }
    groupList.append(row);
    }
  }
  monitorWorkers.replaceChildren(fragment);
  syncMonitorBctNodeTargetHighlight();
  if (monitorBctNodeSummary) {
    const stale = nodes.some((node) => node.displayStale === true);
    monitorBctNodeSummary.textContent = stale
      ? `${nodes.length}개 · RCC 일시 지연 · 마지막 검증 목록`
      : `${nodes.length}개 · BCT/RCC 실시간 상태`;
  }
}

function beginMonitorBctNodePointerDrag(event, row, node) {
  if (event.button !== 0 || !node?.conversationKey || monitorBctPointerDrag || monitorBctNodeReorderPending) return;
  monitorBctPointerDrag = {
    pointerId: event.pointerId,
    row,
    node,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    drop: null,
  };
  // Document capture receives pointerup even beyond the row or the list.
  document.addEventListener("pointermove", updateMonitorBctNodePointerDrag, true);
  document.addEventListener("pointerup", endMonitorBctNodePointerDrag, true);
  document.addEventListener("pointercancel", cancelMonitorBctNodePointerDrag, true);
  window.addEventListener("blur", cancelMonitorBctNodePointerDrag);
  row.addEventListener("lostpointercapture", cancelMonitorBctNodePointerDrag);
  try { row.setPointerCapture(event.pointerId); } catch (_) {}
}

function monitorBctStopDragInput(drag) {
  if (monitorBctPointerDrag !== drag) return;
  monitorBctPointerDrag = null;
  document.removeEventListener("pointermove", updateMonitorBctNodePointerDrag, true);
  document.removeEventListener("pointerup", endMonitorBctNodePointerDrag, true);
  document.removeEventListener("pointercancel", cancelMonitorBctNodePointerDrag, true);
  window.removeEventListener("blur", cancelMonitorBctNodePointerDrag);
  drag.row?.removeEventListener("lostpointercapture", cancelMonitorBctNodePointerDrag);
  drag.row?.classList.remove("is-dragging");
  try { if (drag.row?.hasPointerCapture?.(drag.pointerId)) drag.row.releasePointerCapture(drag.pointerId); } catch (_) {}
}

function monitorBctPointInsideScopeHeading(clientX, clientY) {
  return [...(monitorWorkers?.querySelectorAll?.(".monitor-bct-scope-heading") || [])].some((heading) => {
    const rect = heading.getBoundingClientRect();
    return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
  });
}

function monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey) {
  const rows = [...list.querySelectorAll(".monitor-bct-node-row")]
    .filter((row) => (!row.parentElement || row.parentElement === list) &&
      String(row.dataset.conversationKey || "") !== draggedKey && !row.hidden)
    .map((row) => ({ row, rect: row.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width > 0 && rect.height > 0);
  if (!rows.length) return null;
  const direct = hit?.closest?.(".monitor-bct-node-row");
  if (direct && (!direct.parentElement || direct.parentElement === list) &&
      hit?.closest?.(".monitor-bct-node-list") === list &&
      String(direct.dataset.conversationKey || "") !== draggedKey) {
    const rect = direct.getBoundingClientRect();
    return { row: direct, position: clientX < rect.left + rect.width / 2 ? "before" : "after" };
  }

  const line = rows.reduce((best, candidate) => {
    const centerY = candidate.rect.top + candidate.rect.height / 2;
    const distance = Math.abs(clientY - centerY);
    return !best || distance < best.distance ? { distance, centerY } : best;
  }, null);
  const sameLine = rows
    .filter(({ rect }) => Math.abs((rect.top + rect.height / 2) - line.centerY) <= 3)
    .sort((left, right) => left.rect.left - right.rect.left);
  const first = sameLine[0];
  for (const candidate of sameLine) {
    if (clientX < candidate.rect.left + candidate.rect.width / 2) {
      return { row: candidate.row, position: "before" };
    }
  }
  const last = sameLine[sameLine.length - 1] || first;
  return last ? { row: last.row, position: "after" } : null;
}

// Keep the hit-zone and the visual insertion line governed by the SAME resolver.
const MONITOR_BCT_DROP_EDGE_X_PX = 22;
const MONITOR_BCT_DROP_EDGE_Y_PX = 10;
function monitorBctNodeDropListAt(clientX, clientY, hit) {
  const direct = hit?.closest?.(".monitor-bct-node-list");
  const candidates = [...(monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list") || [])]
    .filter((list) => !list.hidden && monitorWorkers.contains(list))
    .map((list) => {
      const rect = list.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 ||
          clientX < rect.left - MONITOR_BCT_DROP_EDGE_X_PX ||
          clientX > rect.right + MONITOR_BCT_DROP_EDGE_X_PX ||
          clientY < rect.top - MONITOR_BCT_DROP_EDGE_Y_PX ||
          clientY > rect.bottom + MONITOR_BCT_DROP_EDGE_Y_PX) return null;
      const dx = Math.max(rect.left - clientX, 0, clientX - rect.right);
      const dy = Math.max(rect.top - clientY, 0, clientY - rect.bottom);
      return { list, distance: dx * dx + dy * dy };
    }).filter(Boolean);
  if (direct && candidates.some((candidate) => candidate.list === direct)) return direct;
  candidates.sort((a, b) => a.distance - b.distance);
  return candidates[0]?.list || null;
}

function monitorBctNodeDropAt(clientX, clientY, draggedKey) {
  if (monitorBctPointInsideScopeHeading(clientX, clientY)) return null;
  const hit = document.elementFromPoint(clientX, clientY);
  const list = monitorBctNodeDropListAt(clientX, clientY, hit);
  if (!list) return null;
  const scopeId = String(list.dataset.scopeId || "__unassigned__");
  const scopeName = String(list.dataset.scopeName || "").trim();
  const insertion = monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey);
  list.classList.add("monitor-bct-node-list-target");
  if (insertion) {
    const { row, position } = insertion;
    row.classList.add(position === "before" ? "monitor-bct-drop-before" : "monitor-bct-drop-after");
    row.dataset.dropPosition = position;
    return {
      scopeId,
      scopeName,
      targetConversationKey: String(row.dataset.conversationKey || ""),
      position,
    };
  }
  // An empty list (notably a newly empty 미소속 대화 list) still accepts the
  // node. There is no row to insert beside, so the destination appends it.
  return { scopeId, scopeName, targetConversationKey: "", position: "append" };
}

function updateMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  if (!drag.active && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 7) return;
  if (!drag.active) {
    drag.active = true;
    monitorBctSuppressScopeClickUntil = Date.now() + 1000;
    monitorBctDraggedNodeKey = drag.node.conversationKey;
    monitorBctSuppressedClickKey = monitorBctNodeSelectionKey(drag.node);
    drag.row.classList.add("is-dragging");
    document.documentElement.classList.add("monitor-bct-node-drag-active");
    monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list")
      .forEach((list) => list.classList.add("monitor-bct-node-list-available"));
    monitorBctDragGhost?.remove?.();
    monitorBctDragGhost = createMonitorNodeDragGhost(drag.row, event);
    monitorBctDragGhost.classList.add("monitor-bct-node-drag-ghost");
    monitorBctDragGhost.textContent = `${drag.node.nodeLabel || "N?"}  ${drag.node.title || "ChatGPT"}`;
    const previewToken = `${Date.now()}-${event.pointerId}-${++monitorBctNativePreviewSequence}`;
    monitorBctNativePreviewToken = previewToken;
    void monitorNative({
      type:"monitorDragPreviewStart",
      token:previewToken,
      label:monitorBctDragGhost.textContent,
      sourceHwnd:String(monitorDesktopState?.hostWindowHwnd || ""),
    }).catch(() => {}); // An older installed Host keeps the DOM-only preview.
  }
  event.preventDefault();
  moveMonitorNodeDragGhost(monitorBctDragGhost, event.clientX, event.clientY);
  clearMonitorBctNodeDropFeedback();
  drag.drop = monitorBctNodeDropAt(event.clientX, event.clientY, drag.node.conversationKey);
}

function endMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  // Re-evaluate at pointerup. The last preview is never authority if the
  // pointer moved out of the hit-zone without another pointermove event.
  clearMonitorBctNodeDropFeedback();
  const drop = drag.active
    ? monitorBctNodeDropAt(event.clientX, event.clientY, drag.node.conversationKey)
    : null;
  monitorBctStopDragInput(drag);
  if (!drag.active) return;
  event.preventDefault();
  if (!drop) {
    finishMonitorBctNodeDrag();
    return;
  }
  void commitMonitorBctNodeDrop(
    drop.scopeId,
    drop.targetConversationKey,
    drop.position,
    drop.scopeName,
  );
}

function cancelMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;
  monitorBctStopDragInput(drag);
  if (drag.active) finishMonitorBctNodeDrag();
}

function clearMonitorBctNodeDropFeedback() {
  monitorWorkers?.querySelectorAll?.(
    ".monitor-bct-drop-before,.monitor-bct-drop-after,.monitor-bct-node-list-target",
  ).forEach((element) => {
    element.classList.remove(
      "monitor-bct-drop-before",
      "monitor-bct-drop-after",
      "monitor-bct-node-list-target",
    );
    if (element.dataset) delete element.dataset.dropPosition;
  });
}

function finishMonitorBctNodeDrag() {
  stopMonitorBctNativePreview();
  const suppressedKey = monitorBctSuppressedClickKey;
  monitorBctSuppressScopeClickUntil = Date.now() + 350;
  monitorBctDraggedNodeKey = "";
  clearMonitorBctNodeDropFeedback();
  monitorWorkers?.querySelectorAll?.(".monitor-bct-node-row.is-dragging")
    .forEach((row) => row.classList.remove("is-dragging"));
  monitorBctDragGhost?.remove?.();
  monitorBctDragGhost = null;
  document.documentElement.classList.remove("monitor-bct-node-drag-active");
  monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list-available")
    .forEach((list) => list.classList.remove("monitor-bct-node-list-available"));
  globalThis.setTimeout(() => {
    if (monitorBctSuppressedClickKey === suppressedKey) monitorBctSuppressedClickKey = "";
  }, 400);
}

async function commitMonitorBctNodeDrop(destinationGroupKey, targetConversationKey, position, destinationScopeName = "") {
  if (monitorBctNodeReorderPending) {
    finishMonitorBctNodeDrag();
    return;
  }
  const draggedKey = monitorBctDraggedNodeKey;
  const snapshot = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache.slice() : [];
  const semanticSnapshot = monitorUniqueBctConversationNodes(snapshot);
  const dragged = semanticSnapshot.find((node) => node.conversationKey === draggedKey);
  const destinationScopeId = destinationGroupKey === "__unassigned__" ? "" : destinationGroupKey;
  const destinationSample = semanticSnapshot.find((node) => (node.scopeId || "") === destinationScopeId);
  const movedAcrossScopes = (dragged?.scopeId || "") !== destinationScopeId;
  const resolvedDestinationScopeName = destinationScopeId
    ? String(destinationScopeName || destinationSample?.scopeName || "").trim()
    : "";
  if (!dragged || (movedAcrossScopes
    ? !monitorBctShell?.updateConversationScope || (destinationScopeId && !resolvedDestinationScopeName)
    : !monitorBctShell?.reorderConversations)) {
    finishMonitorBctNodeDrag();
    return;
  }

  const destination = semanticSnapshot
    .filter((node) => node.conversationKey !== draggedKey && (node.scopeId || "") === destinationScopeId)
    .sort(compareMonitorBctNodeDisplayOrder);
  let insertion = destination.length;
  if (targetConversationKey) {
    const targetIndex = destination.findIndex((node) => node.conversationKey === targetConversationKey);
    if (targetIndex >= 0) insertion = targetIndex + (position === "after" ? 1 : 0);
  }
  destination.splice(insertion, 0, dragged);
  const nextOrders = new Map(destination.map((node, index) => [node.conversationKey, index + 1]));

  if (movedAcrossScopes) {
    // Move the card immediately.  The write still goes through the same Core
    // metadata contract as the context menu; only a failed write rolls back.
    const optimisticSnapshot = snapshot.map((node) => {
      if (node.conversationKey !== draggedKey) return node;
      return Object.freeze({
        ...node,
        scopeId: destinationScopeId,
        scopeName: resolvedDestinationScopeName,
        displayOrder: nextOrders.get(draggedKey) || 1,
      });
    });
    monitorBctNodeReorderPending = true;
    monitorBctWindowNodesCache = optimisticSnapshot;
    finishMonitorBctNodeDrag();
    renderMonitorBctWindowNodes(optimisticSnapshot);
    try {
      await monitorBctShell.updateConversationScope(dragged, {
        displayName: String(dragged.title || dragged.nodeLabel || dragged.conversationKey || "ChatGPT").trim(),
        scopeName: resolvedDestinationScopeName,
        roleTags: Array.isArray(dragged.roleTags) ? dragged.roleTags : [],
      });
      await refreshMonitorBctWindowNodes();
      setMonitorStatus(
        destinationScopeId ? "노드를 대화망으로 이동했습니다." : "노드를 미소속 대화로 이동했습니다.",
        true,
        2200,
      );
    } catch (error) {
      if (monitorBctWindowNodesCache === optimisticSnapshot) {
        monitorBctWindowNodesCache = snapshot;
        renderMonitorBctWindowNodes(snapshot);
      }
      setMonitorStatus(`대화망 이동 실패 · ${error?.message || error}`, false, 4200);
    } finally {
      monitorBctNodeReorderPending = false;
    }
    return;
  }

  const optimisticSnapshot = snapshot.map((node) => {
    if (!nextOrders.has(node.conversationKey)) return node;
    return Object.freeze({
      ...node,
      scopeId: destinationScopeId,
      scopeName: destinationScopeId ? String(destinationSample?.scopeName || "") : "",
      displayOrder: nextOrders.get(node.conversationKey),
    });
  });
  monitorBctNodeReorderPending = true;
  monitorBctWindowNodesCache = optimisticSnapshot;
  finishMonitorBctNodeDrag();
  renderMonitorBctWindowNodes(optimisticSnapshot);
  try {
    await monitorBctShell.reorderConversations(destination, {
      scopeId: destinationScopeId,
      movedConversationKey: "",
    });
    setMonitorStatus("노드 표시 순서를 저장했습니다.", true, 2200);
  } catch (error) {
    // A newer RCC refresh replaces this exact snapshot. Never overwrite it.
    if (monitorBctWindowNodesCache === optimisticSnapshot) {
      monitorBctWindowNodesCache = snapshot;
      renderMonitorBctWindowNodes(snapshot);
    }
    setMonitorStatus(`노드 순서 저장 실패 · ${error?.message || error}`, false, 4200);
  } finally {
    monitorBctNodeReorderPending = false;
  }
}

function scheduleMonitorBctNodeStartupRevalidation() {
  if (!MONITOR_ACTIVE_STARTUP_ENABLED || monitorBctStartupRevalidationTimer ||
      monitorBctStartupRevalidationAttempts >= MONITOR_BCT_STARTUP_REVALIDATION_DELAYS_MS.length) return;
  const delay = MONITOR_BCT_STARTUP_REVALIDATION_DELAYS_MS[monitorBctStartupRevalidationAttempts];
  monitorBctStartupRevalidationAttempts += 1;
  monitorBctStartupRevalidationTimer = setTimeout(() => {
    monitorBctStartupRevalidationTimer = 0;
    // Read-only retry: a cached RCC row must not leave the initial Monitor
    // view looking disabled until the user happens to focus this window.
    void refreshMonitorBctWindowNodes();
  }, delay);
}

async function refreshMonitorBctWindowNodes() {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorBctShell) return;
  if (!monitorNodePanelRefreshController) {
    monitorNodePanelRefreshController = globalThis.MonitorNodePanelRefresh.create({
      onBusy: busy => {
        if (monitorBctNodesRefresh) monitorBctNodesRefresh.disabled = busy;
        if (busy && monitorBctNodeSummary) monitorBctNodeSummary.textContent = "확인 중…";
      },
      enqueue: callback => queueMicrotask(callback),
      run: async () => {
        const state = await monitorBctShell.monitorState();
        renderMonitorGithubInbox(state);
        monitorBctWindowNodesCache = monitorBctShell.displayWindowNodes
          ? monitorBctShell.displayWindowNodes(state, monitorBctWindowNodesCache || [])
          : monitorBctShell.windowNodes(state);
        resetMonitorBctProjectionConvergence();
        await refreshMonitorBctBrowserWindowGeometry();
        await refreshMonitorIdentityIndex(monitorLastAiState, true);
        refreshMonitorBctCurrentSessionWindowHwnd();
        refreshMonitorBctDisplayWindowHwnd();
        renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
        syncMonitorAllDesktopThumbnailNodeBadges();
        scheduleMonitorBctProjectionConvergence("bct-state");
        if (monitorBctWindowNodesCache.some(node => node.displayStale === true))
          scheduleMonitorBctNodeStartupRevalidation();
      },
      onError: error => {
        if (monitorBctNodeSummary) monitorBctNodeSummary.textContent = "상태 확인 실패";
        const message = document.createElement("div");
        message.className = "monitor-bct-node-empty is-error";
        message.textContent = `BCT 창 현황을 불러오지 못했습니다 · ${error?.message || error}`;
        monitorWorkers?.replaceChildren(message);
      }
    });
  }
  return monitorNodePanelRefreshController.refresh();
}

function renderMonitorGithubInbox(state) {
  if (!monitorGithubInbox) return;
  const items = Array.isArray(state?.github_run_inbox) ? state.github_run_inbox.slice(0, 12) : [];
  monitorGithubInbox.replaceChildren();
  if (!items.length) {
    monitorGithubInbox.textContent = "GitHub Inbox: no waiting or terminal results";
    return;
  }
  const heading = document.createElement("strong");
  const unreadCount = items.filter((item) => item?.unread === true).length;
  heading.textContent = `GitHub 완료 Inbox (${unreadCount} 미확인)`;
  monitorGithubInbox.append(heading);
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "monitor-bct-node-empty";
    const primary = document.createElement("strong");
    const stateLabel = String(item?.state || "UNKNOWN");
    const project = String(item?.repository || "");
    const kind = String(item?.context?.kind || item?.context?.type || "CI");
    primary.textContent = `${item?.unread ? "● " : ""}${stateLabel} · ${project} · ${kind} #${String(item?.run_id || "")}`;
    const details = document.createElement("div");
    const sha = String(item?.head_sha || "");
    const when = Number(item?.created_at || 0);
    const age = Number.isFinite(when) && when > 0 ? ` · ${Math.max(0, Math.floor(Date.now() / 1000 - when))}초 경과` : "";
    details.textContent = `Work ${String(item?.work_id || "")} · ${String(item?.node_id || "")} · ${sha.slice(0, 12)}${age}`;
    const action = document.createElement("div");
    action.textContent = `다음: ${String(item?.next_step || "참고용 결과 확인").slice(0, 240)}`;
    row.append(primary, details, action);
    if (item?.error_summary) {
      const error = document.createElement("div");
      error.textContent = `실패: ${String(item.error_summary).slice(0, 260)}`;
      row.append(error);
    }
    const target = String(item?.url || "");
    if (/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/actions\/runs\/[1-9][0-9]*$/.test(target)) {
      const link = document.createElement("a");
      link.href = target;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "GitHub 결과 보기";
      row.append(link);
    }
    monitorGithubInbox.append(row);
  }
}

async function refreshMonitorBctStatus() {
  if (!monitorVersion || !monitorBctShell) return;
  monitorVersion.classList.remove("healthy", "unhealthy");
  monitorVersion.setAttribute("aria-label", "BCT 연결 확인 중");
  try {
    const state = await monitorBctShell.health();
    monitorVersion.title = `${monitorVersion.textContent} · BCT 연결 정상`;
    monitorVersion.setAttribute("aria-label", `${monitorVersion.textContent} · BCT 연결 정상`);
    monitorVersion.classList.add("healthy");
  } catch (error) {
    monitorVersion.title = `${monitorVersion.textContent} · BCT 연결 안 됨 · ${error?.message || error}`;
    monitorVersion.setAttribute("aria-label", `${monitorVersion.textContent} · BCT 연결 안 됨`);
    monitorVersion.classList.add("unhealthy");
  }
}


monitorBctNodesRefresh?.addEventListener("click", () => {
  void refreshMonitorBctWindowNodes();
});

void refreshMonitorBctStatus();
void refreshMonitorBctWindowNodes();

async function refreshMonitorEndpointRegistry() {
  const refreshUrl = new URL("/browser/endpoints/refresh", ORCHESTRATOR_ROLE_ADMIN_URL).toString();
  const response = await actFetch(refreshUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.ok) throw new Error(result?.error || ("HTTP " + response.status));
  return result;
}

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

function monitorExactSelectedChatNode() {
  const nodes = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [];
  const selected = nodes.find((node) =>
    monitorNodePanelSelection.get() && monitorBctNodeSelectionKey(node) === monitorNodePanelSelection.get()
  );
  if (selected) return selected;
  const active = nodes.filter((node) => node.active === true && node.conversationKey && !node.displayStale);
  return active.length === 1 ? active[0] : null;
}

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

function scheduleMonitorStartupRecovery() {

  if (monitorStartupRecoveryUsed || monitorStartupRecoveryTimer) return;

  if (monitorStartupStateConfirmed && monitorStartupSharedRuntimeConfirmed && monitorStartupEndpointFreshConfirmed) return;

  monitorStartupRecoveryUsed = true;

  monitorStartupRecoveryTimer = setTimeout(async () => {

    monitorStartupRecoveryTimer = null;

    try { await monitorSyncSharedState("startup-settle", false); } catch (_) {}

    try { await refreshActHealth(); } catch (_) {}

    try { await refreshAiMonitor(); } catch (_) {}

  }, MONITOR_STARTUP_SETTLE_MS);

}

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

let monitorNativePort = null;

const monitorNativePending = new Map();
let monitorNativeRequestSequence = 0;

let monitorWallpaperNativePort = null;
const monitorWallpaperNativePending = new Map();
let monitorWallpaperNativeRequestSequence = 0;
let monitorWallpaperNativeQueue = Promise.resolve();

const monitorDesktopVisualSource = globalThis.MonitorDesktopVisualSource.create({ request: monitorWallpaperNativeRequest });
const monitorThumbnailLayerPolicy = globalThis.MonitorThumbnailLayerPolicy.create(
  globalThis.MonitorThumbnailLayerPolicy.MODES.BACKGROUND_WINDOWS_INTERACTION_NODES
);
globalThis.MonitorDesktopThumbnailV2.configure({
  visualSource: monitorDesktopVisualSource,
  readFrame: desktopId => captureDesktopFrame(desktopId, "thumb"),
  interactionPorts: {
    moveWindow: ({hwnd,sourceDesktopId,targetDesktopId}) => moveMonitorWindowToDesktop(hwnd,sourceDesktopId,targetDesktopId),
    onError: error => setMonitorStatus(`창 이동 실패 · ${error?.message || error}`, false),
  },
  afterWindowRender: visual => syncMonitorThumbnailTabBadges(visual,"monitor-desktop-thumb-window"),
  layerPolicy: monitorThumbnailLayerPolicy,
});

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

function ensureMonitorNativePort() {

  if (monitorNativePort) return monitorNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

  monitorNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.event === true && response?.type === "windowMoveSizeEnd") { scheduleMonitorWindowLifecycleEvent(response); return; }
    if (response?.event === true && response?.type === "externalWindowDropFinished") { void handleMonitorExternalWindowDropFinished(response); return; }
    if (response?.event === true && response?.type === "windowForegroundChanged") { handleMonitorForegroundChangedEvent(response); return; }
    if (response?.event === true && response?.type === "desktopWallpaperChanged") {
      const explicitId=String(response.desktopId||"").toLowerCase();
      const visuals=[...(monitorDesktopThumbs?.querySelectorAll?.(".monitor-desktop-thumb-visual")||[])];
      const currentId=String(monitorDesktopState?.currentDesktopId||"").toLowerCase();
      const selectedId=String(monitorDesktopState?.desktopIds?.[monitorDesktopState?.selectedIndex]||"").toLowerCase();
      const priority=id=>id===explicitId?0:id===currentId?1:id===selectedId?2:3;
      // Windows only persists per-virtual-desktop picture paths.  A desktop
      // without one follows the current global picture/solid mode, so a change
      // reported for the current GUID can also change those inherited tiles.
      // Re-read every canonical tile, with the reported/current/selected ones
      // first, instead of retaining an old inherited color or photo.
      const targets=visuals
        .sort((a,b)=>priority(String(a.dataset.desktopId||"").toLowerCase())-priority(String(b.dataset.desktopId||"").toLowerCase()));
      monitorDesktopThumbs.dataset.wallpaperEventAt=String(Date.now());
      // Native names the changed desktop. Older hosts without that field are
      // queued current-first; the injected wallpaper transport serializes I/O.
      void Promise.allSettled(targets.map(async visual=>{
          const id=String(visual.dataset.desktopId||"").toLowerCase();
          await globalThis.MonitorDesktopThumbnailV2.refreshBackground(
            visual,id,{forceWallpaper:true}).catch(()=>null);
          syncMonitorPreviewBackground(visual,id);
      }));
      return;
    }
    if (response?.event === true && response?.type === "monitorDragPreviewReleased") {
      const drag = monitorBctPointerDrag;
      if (drag?.active && response?.token === monitorBctNativePreviewToken) {
        cancelMonitorBctNodePointerDrag({ pointerId:drag.pointerId });
      }
      return;
    }

    if (response?.event === true) return; // Unsolicited events never complete requests.
    const requestId = String(response?.requestId || "");
    const pending = monitorNativePending.get(requestId);
    if (!pending) return;
    monitorNativePending.delete(requestId);
    pending.resolve(response);

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료";

    monitorNativePort = null;

    for (const pending of monitorNativePending.values()) pending.reject(new Error(error));
    monitorNativePending.clear();

  });

  return port;

}

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

// V2 owns all bottom desktop-thumbnail pixels and HWND DOM. Legacy lifecycle
// events may request refresh/removal; they must never create/modify tile images.
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

const monitorWindowLifecycleController = globalThis.MonitorWindowLifecycleQueue.create({handle: event => handleMonitorWindowLifecycleEvent(event), onError: error => setMonitorStatus(String(error), false)});

function scheduleMonitorWindowLifecycleEvent(event) { monitorWindowLifecycleController.schedule(event); }



async function handleMonitorWindowLifecycleEvent(event) {

  const hwnd=String(event?.hwnd||"").trim();

  if (!/^\d+$/.test(hwnd)||hwnd==="0") return;
  if (hwnd === String(monitorDesktopState.hostWindowHwnd || "")) {
    await chrome.runtime.sendMessage({ type:"monitor-save-popup-window-bounds" }).catch(() => null);
    scheduleMonitorExternalWindowDropTargets();
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

function monitorNative(message) {
  return MonitorNativeTrace.request("control", message, () => monitorControlNativeRequest(message));
}

function monitorControlNativeRequest(message) {
  // Pixel capture belongs exclusively to the WGC Core host. The Control host
  // still contains the legacy synchronous capture implementation.
  if (message?.type === "captureWindow") {
    return Promise.reject(new Error("CAPTURE_REQUIRES_WGC_CORE_ADAPTER"));
  }

  return new Promise((resolve, reject) => {

    const port = ensureMonitorNativePort();
    const requestId = `monitor-${Date.now().toString(36)}-${(++monitorNativeRequestSequence).toString(36)}`;
    monitorNativePending.set(requestId, { resolve, reject, message });

    try { port.postMessage({ ...message, requestId }); }

    catch (error) { monitorNativePending.delete(requestId); reject(error); }

  });

}

function ensureMonitorWallpaperNativePort() {
  if (monitorWallpaperNativePort) return monitorWallpaperNativePort;
  const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);
  monitorWallpaperNativePort = port;
  port.onMessage.addListener((response) => {
    if (response?.event === true) return;
    const requestId = String(response?.requestId || "");
    const pending = monitorWallpaperNativePending.get(requestId);
    if (!pending) return;
    monitorWallpaperNativePending.delete(requestId);
    pending.resolve(response);
  });
  port.onDisconnect.addListener(() => {
    if (monitorWallpaperNativePort === port) monitorWallpaperNativePort = null;
    const error = new Error(chrome.runtime.lastError?.message || "Monitor Wallpaper Native Host 연결 종료");
    for (const pending of monitorWallpaperNativePending.values()) pending.reject(error);
    monitorWallpaperNativePending.clear();
  });
  return port;
}

function monitorWallpaperNativeRequest(message, timeoutMs = 8000) {
  const run = () => new Promise((resolve, reject) => {
    const port = ensureMonitorWallpaperNativePort();
    const requestId = `wallpaper-${Date.now().toString(36)}-${(++monitorWallpaperNativeRequestSequence).toString(36)}`;
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      if (settled) return;
      const error = new Error("MONITOR_WALLPAPER_NATIVE_TIMEOUT");
      if (monitorWallpaperNativePort === port) monitorWallpaperNativePort = null;
      try { port.disconnect(); } catch (_) {}
      for (const pending of monitorWallpaperNativePending.values()) pending.reject(error);
      monitorWallpaperNativePending.clear();
    }, Math.max(1000, Number(timeoutMs) || 8000));
    monitorWallpaperNativePending.set(requestId, {
      message,
      resolve:value => finish(resolve,value),
      reject:error => finish(reject,error)
    });
    try {
      port.postMessage({ ...message, requestId });
    } catch (error) {
      monitorWallpaperNativePending.delete(requestId);
      if (monitorWallpaperNativePort === port) monitorWallpaperNativePort = null;
      try { port.disconnect(); } catch (_) {}
      finish(reject,error);
    }
  });
  const task = monitorWallpaperNativeQueue.catch(() => null).then(run);
  monitorWallpaperNativeQueue = task.catch(() => null);
  return task;
}

function monitorNativeLaunchIsolated(message) {

  return monitorControlNativeIsolatedRequest(message);

}

function monitorControlNativeIsolatedRequest(message) {

  return new Promise((resolve, reject) => {

    const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

    let settled = false;

    const finish = (fn, value) => {

      if (settled) return;

      settled = true;

      try { port.disconnect(); } catch (_) {}

      fn(value);

    };

    port.onMessage.addListener((response) => {

      if (response?.event === true) return;

      finish(resolve, response);

    });

    port.onDisconnect.addListener(() => {

      if (settled) return;

      finish(reject, new Error(chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료"));

    });

    try { port.postMessage(message); }

    catch (error) { finish(reject, error); }

  });

}
function monitorNativeWithTimeout(message, timeoutMs = 2500) {

  return new Promise((resolve, reject) => {

    let done = false;

    const timer = setTimeout(() => {

      if (done) return;

      done = true;

      try { monitorNativePort?.disconnect(); } catch (_) {}

      reject(new Error("MONITOR_NATIVE_TIMEOUT"));

    }, Math.max(250, Number(timeoutMs) || 2500));

    monitorNative(message).then((value) => { if (done) return; done = true; clearTimeout(timer); resolve(value); }, (error) => { if (done) return; done = true; clearTimeout(timer); reject(error); });

  });

}

async function approveMonitorNodeChatChange(worker, nodeState, button) {

  const binding=nodeState?.nodeBinding||{}, oldKey=String(nodeState?.previousConversationKey||binding.conversation_key||"").trim();

  const newKey=String(nodeState?.currentConversationKey||worker?.conversation_key||"").trim(); const hwnd=String(nodeState?.hwnd||binding.hwnd||"").trim();

  if(!oldKey||!newKey||oldKey===newKey||!hwnd){setMonitorStatus("챗 변경 승인 실패 · identity 부족",false);return;}

  button.disabled=true; const oldText=button.textContent; button.textContent="…";

  try{

    const response=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}); const state=response?.ok?await response.json():null;

    const endpoints=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===newKey);

    const currentEndpoint=nodeState?.endpoint||worker?.__endpoint||null;
    const currentTabId=Number(currentEndpoint?.tab_id||binding?.tab_id||0);
    const currentProfile=String(currentEndpoint?.profile_id||worker?.profile_id||binding?.profile_id||"").toUpperCase();

    let approvedEndpoint=null;
    if(currentEndpoint&&String(currentEndpoint?.conversation_key||"").trim()===newKey){
      const direct=endpoints.filter(ep=>
        Number(ep?.tab_id||0)===currentTabId
        && (!currentProfile||String(ep?.profile_id||"").toUpperCase()===currentProfile)
      );
      if(direct.length===1)approvedEndpoint=direct[0];
    }

    if(!approvedEndpoint&&currentTabId>0){
      const byTab=endpoints.filter(ep=>
        Number(ep?.tab_id||0)===currentTabId
        && (!currentProfile||String(ep?.profile_id||"").toUpperCase()===currentProfile)
      );
      if(byTab.length===1)approvedEndpoint=byTab[0];
      else if(byTab.length>1)throw new Error("현재 탭의 새 챗 endpoint가 중복됨");
    }

    if(!approvedEndpoint){
      const matching=endpoints.filter(ep=>String(monitorLocationForEndpoint(ep)?.hwnd||"")===hwnd);
      if(matching.length!==1)throw new Error(matching.length>1?"현재 창과 일치하는 새 챗 endpoint가 중복됨":"현재 탭/창의 새 챗 endpoint를 확인하지 못함");
      approvedEndpoint=matching[0];
    }

    const oldRoleSlot=(Array.isArray(state?.organization?.role_slots)?state.organization.role_slots:[]).find(x=>String(x?.state||"").toUpperCase()==="ACTIVE"&&String(x?.conversation_key||"").trim()===oldKey);

    if(oldRoleSlot){

      const role=String(oldRoleSlot?.role||"").toUpperCase();

      if(["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"].includes(role)){

        const r=await fetch(`${ORCHESTRATOR_ROLE_ADMIN_URL}/replace`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role,conversation_key:newKey,expected_generation:Number(oldRoleSlot.generation||0)})});

        const d=await r.json().catch(()=>null); if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);

      }

    }

    const next={...binding,conversation_key:newKey,profile_id:String(approvedEndpoint?.profile_id||binding.profile_id||"").toUpperCase(),title:String(approvedEndpoint?.title||worker?.title||binding.title||""),window_instance_id:String(approvedEndpoint?.window_instance_id||approvedEndpoint?.metadata?.window_instance_id||binding.window_instance_id||"")};

    const stored=monitorStoreNodeBinding(next,approvedEndpoint);

    monitorRememberApprovedChatTransition(stored?.node_identity_key||binding?.node_identity_key||monitorStableBrowserNodeKey({...worker,__endpoint:approvedEndpoint}),stored?.profile_id||binding.profile_id,oldKey,newKey);

    await refreshAiMonitor();

    setMonitorStatus(`${next.node_label||"노드"} 승인 · 새 챗과 매칭 유지`,true);

  }catch(error){setMonitorStatus(`챗 변경 승인 실패 · ${error?.message||error}`,false);}finally{button.textContent=oldText;button.disabled=false;}

}

async function restoreMonitorNodeChatChange(worker,nodeState,button){

  const binding=nodeState?.nodeBinding||{}; const key=String(binding.conversation_key||nodeState?.previousConversationKey||"").trim(); const profile=String(binding.profile_id||worker?.profile_id||"").toUpperCase(); const targetDesktopId=String(binding.desktop_id||"");

  if(!key||!profile){setMonitorStatus("원래 창 복구 실패 · 원래 대화 정보 없음",false);return;}

  button.disabled=true; const oldText=button.textContent; button.textContent="…";

  try{

    const stateResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}); const state=stateResponse?.ok?await stateResponse.json():null;

    const open=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===key);

    if(open.length>1)throw new Error("원래 대화가 여러 창에 열려 있음");

    const currentEndpoint=nodeState?.endpoint||worker?.__endpoint||null;
    const targetTabId=Number(currentEndpoint?.tab_id||binding?.tab_id||0);
    if(!Number.isInteger(targetTabId)||targetTabId<=0)throw new Error("현재 탭 ID 확인 실패");
    const otherOpen=open.filter(ep=>Number(ep?.tab_id||0)!==targetTabId);
    if(otherOpen.length)throw new Error("원래 대화가 다른 탭에 이미 열려 있음");
    let endpoint=String(currentEndpoint?.conversation_key||"").trim()===key ? currentEndpoint : null;

    if(!endpoint){
      const nav=await chrome.runtime.sendMessage({type:"monitor-navigate-chat-tab",tabId:targetTabId,conversationKey:key}).catch(error=>({ok:false,error:error?.message||String(error)}));
      if(!nav?.ok)throw new Error(nav?.error||"현재 탭 복구 실패");
    }

    for(let i=0;i<24&&!endpoint;i++){
      await new Promise(r=>setTimeout(r,250));
      const rr=await actFetch(ORCHESTRATOR_MONITOR_STATE_URL,{cache:"no-store"});
      const ss=rr?.ok?await rr.json():null;
      const matches=(Array.isArray(ss?.endpoints)?ss.endpoints:[]).filter(ep=>
        String(ep?.presence_state||"").toUpperCase()==="OPEN"
        && String(ep?.conversation_key||"").trim()===key
        && Number(ep?.tab_id||0)===targetTabId
      );
      if(matches.length>1)throw new Error("복구 endpoint 중복");
      if(matches.length===1)endpoint=matches[0];
    }

    if(!endpoint)throw new Error("복구된 대화가 ACT에 등록되지 않음");

    const hwnd=endpointOsWindowHandle(endpoint); if(!hwnd)throw new Error("복구된 창 HWND 확인 실패");

    if(targetDesktopId)await moveMonitorWindowToDesktop(hwnd,"",targetDesktopId);

    const next={...binding,conversation_key:key,profile_id:profile,title:String(endpoint?.title||binding.title||""),window_instance_id:String(endpoint?.window_instance_id||endpoint?.metadata?.window_instance_id||binding.window_instance_id||"")};

    monitorStoreNodeBinding(next,endpoint); await refreshAiMonitor(); setMonitorStatus(`${next.node_label||"노드"} 복구 · 현재 탭을 원래 챗으로 되돌림`,true);

  }catch(error){setMonitorStatus(`원래 챗 복구 실패 · ${error?.message||error}`,false);}finally{button.textContent=oldText;button.disabled=false;}

}

async function restoreMonitorAllRecovery(button,listRecords,items){

  if(!button||button.disabled)return; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  try{for(const item of listRecords||[])restoreMonitorTrashRecord(item?.conversation_key);for(const item of items||[]){const temp=document.createElement("button");temp.textContent="복구";await restoreMonitorDetachedTask(item,temp);}}

  finally{button.textContent=old;button.disabled=false;refreshMonitorRecoveryMenu();}

}

async function restoreMonitorRebootSnapshot(button) {

  const items=[...(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[])];

  if(!items.length||monitorRebootRestoreActive||!button)return {ok:false,status:"IGNORED",results:[]};

  monitorRebootRestoreActive=true; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  const results=[];

  try{    for(const item of items){

      const key=String(item?.conversation_key||"").trim(); if(!key)continue;

      monitorRebootRestorePendingKeys.add(key);

      const temp=document.createElement("button");temp.textContent="복구";

      const result=await restoreMonitorDetachedTask({...item,__reboot_restore:true},temp);

      results.push(result||{ok:false,status:"FAILED",conversationKey:key,error:"복구 결과 없음"});

      if(result?.ok){

        const r=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null),state=r?.ok?await r.json().catch(()=>null):null;

        const ep=(Array.isArray(state?.endpoints)?state.endpoints:[]).find((x)=>String(x?.conversation_key||"").trim()===key&&String(x?.presence_state||"").toUpperCase()==="OPEN");

        if(ep){

          const resolved=monitorExactConversationWindow(key,state,Date.now(),ep);

          const hwnd=String(resolved?.location?.hwnd||endpointOsWindowHandle(ep)||"").trim();

          const target=monitorDesktopState.desktopIds[Math.max(0,Number(item.desktop||1)-1)]||String(item.desktop_id||"");

          if(/^\d+$/.test(hwnd)&&hwnd!=="0"&&target){

            const moved=await monitorNative({type:"moveWindowToDesktop",hwnd,desktopId:target}).catch(()=>null);

            if(moved&&moved.ok===false)result.positionWarning=String(moved.error||"원래 데스크톱 이동 실패");

          }

        }

      }

      monitorRebootRestorePendingKeys.delete(key); await refreshAiMonitor();

    }

    const failed=results.filter((row)=>!row?.ok);

    const opened=results.filter((row)=>row?.ok&&row?.status==="RESTORED").length;

    const existing=results.filter((row)=>row?.ok&&row?.status==="ALREADY_OPEN").length;

    if(failed.length){

      const names=failed.slice(0,3).map((row)=>row?.nodeLabel||String(row?.conversationKey||"").slice(0,8)).join(", ");

      setMonitorStatus(`전체 복원 일부 실패 · 새로 ${opened} · 이미 열림 ${existing} · 실패 ${failed.length}${names?` · ${names}`:""}`,false);

    }else setMonitorStatus(`이전 상태 전체 복원 완료 · 새로 ${opened} · 이미 열림 ${existing}`,true);

    return {ok:failed.length===0,status:failed.length?"PARTIAL":"COMPLETE",results};  }catch(error){

    setMonitorStatus(`전체 복원 실패 · ${error?.message||error}`,false);

    return {ok:false,status:"FAILED",error:String(error?.message||error),results};

  }finally{

    for(const item of items)monitorRebootRestorePendingKeys.delete(String(item?.conversation_key||""));

    monitorRebootRestoreActive=false;

    const expected=items.filter((item)=>String(item?.conversation_key||"").trim()).length;

    const allVerified=results.length===expected&&results.every((row)=>row?.ok);

    button.disabled=false; button.textContent=old;

    if(monitorLastAiState){if(allVerified)monitorCaptureRebootSnapshot(monitorLastAiState);renderWorkers(monitorLastAiState);}

  }

}

function createMonitorContextContinueButton(item) {
  const captured = { ...item };
  return globalThis.MonitorContextResume.createButton({
    target: captured,
    fetcher: actFetch,
    openConversation: () => restoreMonitorDetachedTask(captured, document.createElement('button')),
  });
}

function createMonitorWorkRecoveryButton() {
  return globalThis.MonitorWorkRecovery.createButton({
    fetcher: actFetch,
    openConversation: target => restoreMonitorDetachedTask(target, document.createElement('button')),
  });
}

async function restoreMonitorDetachedTask(item, button) {

  const key=String(item?.conversation_key||"").trim();

  let profile=String(item?.profile_id||"").trim().toUpperCase();

  const nodeLabel=String(item?.node_label||"").trim();

  if(!key||!button)return {ok:false,status:"INVALID",conversationKey:key,profileId:profile,nodeLabel,error:"복구 대상 정보 없음"};

  if(button.disabled||monitorDetachedRestorePending.has(key))return {ok:false,status:"BUSY",conversationKey:key,profileId:profile,nodeLabel,error:"이미 복구 진행 중"};

  monitorDetachedRestorePending.add(key);

  button.disabled=true; const original=button.textContent; button.textContent="복구 중…";

  try{

    const preResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

    if(!preResponse?.ok)throw new Error("ACT 상태 확인 실패");

    const preState=await preResponse.json().catch(()=>null);

    if(!preState)throw new Error("ACT 상태 응답 해석 실패");

    const exactEndpoints=(Array.isArray(preState?.endpoints)?preState.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key);
    const observedProfiles=[...new Set(exactEndpoints.map((candidate)=>String(candidate?.profile_id||"").trim().toUpperCase()).filter(Boolean))];
    if(!profile){
      if(observedProfiles.length!==1)throw new Error(observedProfiles.length ? "복구 대상 Chrome 프로필이 여러 개라 자동으로 선택할 수 없음" : "복구 대상 Chrome 프로필이 ACT에 기록되어 있지 않음");
      profile=observedProfiles[0];
    }else if(observedProfiles.length&& !observedProfiles.includes(profile))throw new Error("기록의 Chrome 프로필이 ACT endpoint 기록과 다름");
    const alreadyOpen=exactEndpoints.filter((candidate)=>String(candidate?.presence_state||"").toUpperCase()==="OPEN");

    if(alreadyOpen.length>1)throw new Error("같은 대화의 OPEN endpoint가 여러 개임");    let endpoint=alreadyOpen[0]||null;

    let status=endpoint?"ALREADY_OPEN":"RESTORED";

    if(endpoint&&profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("이미 열린 대화의 Chrome 프로필이 복구 기록과 다름");

    if(!endpoint){

      const launch=await monitorNative({type:"restoreChatGptConversation",profileId:profile,conversationKey:key}).catch((error)=>({ok:false,error:String(error?.message||error)}));

      if(!launch?.ok||!launch?.launched)throw new Error(`브라우저 복구 실행 실패 · ${launch?.error||"Native Host 응답 없음"}`);

      for(let i=0;i<30&&!endpoint;i+=1){

        await new Promise((resolve)=>setTimeout(resolve,500));

        const response=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

        const state=response?.ok?await response.json().catch(()=>null):null;

        const matches=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key&&String(candidate?.presence_state||"").toUpperCase()==="OPEN");

        if(matches.length>1)throw new Error("Ambiguous OPEN endpoints after restore.");

        if(matches.length===1)endpoint=matches[0];

      }

      if(!endpoint)throw new Error("브라우저는 실행했지만 15초 안에 ACT endpoint가 등록되지 않음");

      if(profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("Restored endpoint profile mismatch.");

    }

    monitorHiddenGhosts.delete(key); monitorGhostPersist();

    if(!item?.__reboot_restore)monitorRecoveryPickerState.close();

    await refreshAiMonitor();

    if(!item?.__reboot_restore)setMonitorStatus(`${nodeLabel||"대화"} 복구 완료${status==="ALREADY_OPEN"?" · 이미 열려 있음":""}`,true);

    return {ok:true,status,conversationKey:key,profileId:profile,nodeLabel,endpoint};

  }catch(error){

    const message=String(error?.message||error);

    setMonitorStatus(`${nodeLabel||"대화"} 복구 실패 · ${message}`,false);

    button.title=message;

    console.warn("DesktopWindow Monitor conversation recovery failed",{conversationKey:key,profileId:profile,nodeLabel,error:message});

    return {ok:false,status:"FAILED",conversationKey:key,profileId:profile,nodeLabel,error:message};  }finally{

    monitorDetachedRestorePending.delete(key);

    button.textContent=original; button.disabled=false;

    if(monitorLastAiState)renderWorkers(monitorLastAiState);

  }

}

let monitorCoreNativePort = null;

const monitorCoreNativePending = [];

function ensureMonitorCoreNativePort() {

  if (monitorCoreNativePort) return monitorCoreNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CORE_HOST);

  monitorCoreNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.type === "shellMirrorChanged" || response?.subscribed === true) {

      window.dispatchEvent(new CustomEvent("desktopwindow-shell-native-event", { detail: response }));

      return;

    }

    if (response?.event === true) return; // Unsolicited native events cannot consume command replies.
    const pending = monitorCoreNativePending.shift();

    if (pending) pending.resolve(response);

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Core Native Host 연결 종료";

    monitorCoreNativePort = null;

    while (monitorCoreNativePending.length) monitorCoreNativePending.shift().reject(new Error(error));

  });

  // Core port carries request/response traffic only. Uncorrelated subscription
  // messages used to consume the next pending request response.

  return port;

}

function monitorCoreNative(message) {
  return MonitorNativeTrace.request("core", message, () => monitorCoreNativeRequest(message));
}

function monitorCoreNativeRequest(message) {

  return new Promise((resolve, reject) => {

    const port = ensureMonitorCoreNativePort(); monitorCoreNativePending.push({ resolve, reject });

    try { port.postMessage(message); } catch (error) { monitorCoreNativePending.pop(); reject(error); }

  });

}

let monitorWallpaperToken = 0;

const monitorWallpaperCache = new Map();
const monitorWallpaperActuals = new Map();

// Substitution wallpaper map removed.

const MONITOR_WALLPAPER_CACHE_MS = 15000;

const MONITOR_WALLPAPER_CACHE_LIMIT = 3;

const MONITOR_WALLPAPER_ACTUAL_LIMIT = 8;
const MONITOR_WALLPAPER_MAX_WIDTH = 960;
const MONITOR_WALLPAPER_MAX_HEIGHT = 600;
// Wallpaper pixels are bounded and cached separately. Individual window captures
// stay disabled until decoded-image ownership in the native capture path is fixed.
const MONITOR_PIXEL_VISUALS_ENABLED = true;
// Per-window pixels use the isolated one-frame WGC helper. Native capture is
// bounded to two concurrent requests and the helper exits after each snapshot.
const MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED = true;

function monitorRememberWallpaperEntry(map, desktopId, dataUri, limit) {
  const key = String(desktopId || "");
  if (!key || !dataUri) return;
  map.delete(key);
  map.set(key, { dataUri, at: Date.now() });
  while (map.size > limit) {
    const oldestKey = map.keys().next().value;
    if (!oldestKey) break;
    map.delete(oldestKey);
  }
}

async function monitorLightweightWallpaperDataUri(dataUri) {
  const source = String(dataUri || "");
  if (!source.startsWith("data:image/")) return source;
  try {
    const image = await new Promise((resolve, reject) => {
      const node = new Image();
      node.onload = () => resolve(node);
      node.onerror = reject;
      node.src = source;
    });
    const width = Math.max(1, Number(image.naturalWidth || image.width || 1));
    const height = Math.max(1, Number(image.naturalHeight || image.height || 1));
    const scale = Math.min(1, MONITOR_WALLPAPER_MAX_WIDTH / width, MONITOR_WALLPAPER_MAX_HEIGHT / height);
    if (scale >= 1) return source;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d", { alpha:false });
    if (!ctx) return source;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const compact = canvas.toDataURL("image/jpeg", 0.68);
    canvas.width = 1;
    canvas.height = 1;
    return compact || source;
  } catch (_) {
    return source;
  }
}

const monitorFrameCache = new Map();

const monitorFrameInflight = new Map();

const monitorDesktopFrameGenerationController = globalThis.MonitorDesktopFrameGeneration.create();

function monitorDesktopFrameGeneration(desktopId) { return monitorDesktopFrameGenerationController.generation(desktopId); }

const MONITOR_FRAME_CACHE_LIMIT = 4;
const MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS = 15000;
const MONITOR_WINDOW_CAPTURE_MAX_AGE_MS = 30000;
function monitorCaptureMatchesCurrentWindow(captureTitle,currentTitle,capturedAt,now=Date.now()){
  const age=Number(now)-Number(capturedAt||0);
  return Boolean(String(captureTitle||"").trim())
    && String(captureTitle||"").trim()===String(currentTitle||"").trim()
    && Number.isFinite(age)&&age>=0&&age<=MONITOR_WINDOW_CAPTURE_MAX_AGE_MS;
}

function monitorRevokeThumbWindowCaptureSource(source) {
  const value = String(source || "");
  if (!value.startsWith("blob:")) return;
  URL.revokeObjectURL(value);
  monitorRenderDiagnostics.blobRevokes += 1;
}

if (!globalThis.MonitorThumbnailService?.create) {
  throw new Error("MonitorThumbnailService module is not loaded");
}

// Profiles intentionally have separate caches (thumbnail, preview and frozen),
// but they all consume the same WGC/native capture resource.  A single gate
// prevents a mixed-profile refresh from turning three per-profile limits into
// six simultaneous native captures.
const monitorCaptureScheduler = (() => {
  // One WGC snapshot at a time keeps desktop interaction responsive. Refresh
  // queues remain coalesced by HWND, so this trades a little thumbnail latency
  // for a bounded CPU/GPU burst rather than dropping a requested frame.
  const maxConcurrent = 1;
  const queue = [];
  let active = 0;
  let maxObservedActive = 0;

  const drain = () => {
    while (active < maxConcurrent && queue.length) {
      const next = queue.shift();
      if (!next) continue;
      active += 1;
      maxObservedActive = Math.max(maxObservedActive, active);
      Promise.resolve()
        .then(next.task)
        .then(next.resolve, next.reject)
        .finally(() => {
          active = Math.max(0, active - 1);
          drain();
        });
    }
  };

  return Object.freeze({
    run(task) {
      return new Promise((resolve, reject) => {
        queue.push({ task, resolve, reject });
        drain();
      });
    },
    stats() {
      return Object.freeze({ maxConcurrent, active, queued: queue.length, maxObservedActive });
    }
  });
})();

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

const monitorThumbnailCaptureServices = Object.freeze({
  thumb: createMonitorWindowCaptureService({ maxEntries: 12, maxWidth: 480, maxHeight: 270, quality: 52 }),
  preview: createMonitorWindowCaptureService({ maxEntries: 6, maxWidth: 960, maxHeight: 540, quality: 68 }),
  frozen: createMonitorWindowCaptureService({ maxEntries: 32, maxWidth: 960, maxHeight: 540, quality: 68 })
});

function monitorWindowCaptureService(profile) {
  if (profile === "frozen") return monitorThumbnailCaptureServices.frozen;
  return profile === "preview" ? monitorThumbnailCaptureServices.preview : monitorThumbnailCaptureServices.thumb;
}

const monitorThumbnailService = Object.freeze({
  async requestSnapshot(hwnd, reason = "unspecified", profile = "thumb") {
    monitorRenderDiagnostics.captureRequests += 1;
    const key = String(hwnd || "").trim();
    if (!key || !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED) return "";
    const item = monitorWindowDesktopLocations.get(key);
    if (monitorWindowUsesFrozenCapture(item)) {
      const shared = String(item?.frozenDataUri || "");
      if (shared.startsWith("data:image/")) return shared;
    }
    const captureProfile = monitorWindowUsesFrozenCapture(item) ? "frozen" : profile;
    const service = monitorWindowCaptureService(captureProfile);
    const cached = service.getCached(key);
    if(cached&&!monitorCaptureMatchesCurrentWindow(cached.meta?.captureTitle,item?.title,cached.meta?.capturedAt))service.invalidate(key);
    const result = await service.requestSnapshot(key, reason).catch(() => null);
    return String(result?.value || "");
  },
  invalidate(hwnd) {
    const key = String(hwnd || "").trim();
    if (monitorWindowUsesFrozenCapture(monitorWindowDesktopLocations.get(key))) return false;
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.invalidate(key) || changed;
    return changed;
  },
  dispose(hwnd) {
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.dispose(hwnd) || changed;
    return changed;
  },
  disposeAll() {
    for (const service of Object.values(monitorThumbnailCaptureServices)) service.disposeAll();
  },
  stats() {
    const profiles = Object.fromEntries(Object.entries(monitorThumbnailCaptureServices).map(([name, service]) => [name, service.stats()]));
    const totals = Object.values(profiles).reduce((sum, profile) => {
      for (const key of ["requested", "cacheHits", "coalesced", "queued", "started", "completed", "failed", "staleDiscarded", "evicted", "disposedResults", "active", "queuedNow", "cached", "trackedWindows"]) sum[key] = Number(sum[key] || 0) + Number(profile[key] || 0);
      sum.maxObservedActive = Math.max(Number(sum.maxObservedActive || 0), Number(profile.maxObservedActive || 0));
      return sum;
    }, {});
    return { ...totals, profiles, nativeCapture: monitorCaptureScheduler.stats() };
  }
});

window.addEventListener("pagehide", () => {
  stopMonitorBctNativePreview();
  monitorThumbnailService.disposeAll();
}, { once:true });

async function monitorGetWindowCapture(hwnd, profile = "thumb") {
  return monitorThumbnailService.requestSnapshot(hwnd, "desktop-frame", profile);
}

let monitorOwnFrozenCaptureHwnd = "";
let monitorOwnFrozenCaptureAttemptedHwnd = "";
let monitorOwnFrozenCaptureBusy = false;

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


let monitorCurrentWallpaperCaptureBusy = false;

async function ensureMonitorCurrentWallpaperSnapshot(desktopIdValue) {
  const desktopId = String(desktopIdValue || "").trim();
  const currentDesktopId = String(monitorDesktopState.currentDesktopId || "").trim();
  if (!desktopId || desktopId !== currentDesktopId || !monitorIsActiveDesktopRenderer() || monitorCurrentWallpaperCaptureBusy) return false;

  monitorCurrentWallpaperCaptureBusy = true;
  try {
    const retryDelays = [0, 160, 420];
    for (const delay of retryDelays) {
      if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
      if (String(monitorDesktopState.currentDesktopId || "").trim() !== desktopId || !monitorIsActiveDesktopRenderer()) return false;

      const capture = await monitorCoreNative({
        type:"captureCurrentDesktopWallpaper",
        maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,
        maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,
        quality:68
      }).catch(() => null);
      const capturedDesktopId = String(capture?.desktopId || "").trim();
      const rawDataUri = capture?.ok && capturedDesktopId.toLowerCase() === desktopId.toLowerCase() ? String(capture?.dataUri || "") : "";
      if (!rawDataUri.startsWith("data:image/")) continue;

      const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);
      if (!String(dataUri || "").startsWith("data:image/")) continue;

      monitorRememberWallpaperEntry(monitorWallpaperActuals, desktopId, dataUri, MONITOR_WALLPAPER_ACTUAL_LIMIT);
      monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);
      invalidateMonitorDesktopFrames(desktopId);

      await chrome.runtime.sendMessage({
        type:"monitor-update-popup-runtime",
        desktopId,
        hwnd:String(monitorDesktopState.hostWindowHwnd || ""),
        wallpaperDataUri:dataUri
      }).catch(() => null);
      return true;
    }
    return false;
  } finally {
    monitorCurrentWallpaperCaptureBusy = false;
  }
}

let monitorThumbBatchGeneration = 0;

let monitorThumbBatchInflight = null;

function monitorIsActiveDesktopRenderer() {
  const hostDesktopId = String(monitorDesktopState.hostDesktopId || "").trim();
  const currentDesktopId = String(monitorDesktopState.currentDesktopId || "").trim();
  // Preserve startup/recovery until native host identity is known. After that,
  // only the Monitor on the current Windows virtual desktop may capture pixels.
  if (!hostDesktopId || !currentDesktopId) return true;
  return hostDesktopId === currentDesktopId;
}

async function getObservedWallpaper(desktopId, force = false) {

  if (!MONITOR_PIXEL_VISUALS_ENABLED || !desktopId) return "";

  const actual = monitorWallpaperActuals.get(desktopId);
  // Explicit refresh must consult Native, not reuse an indefinitely retained image.
  if (!force && actual?.dataUri) {
    monitorWallpaperActuals.delete(desktopId);
    monitorWallpaperActuals.set(desktopId, actual);
    return actual.dataUri;
  }
  const cached = monitorWallpaperCache.get(desktopId);

  if (!force && cached && Date.now() - cached.at <= MONITOR_WALLPAPER_CACHE_MS) { monitorWallpaperCache.delete(desktopId); monitorWallpaperCache.set(desktopId, cached); return cached.dataUri; }

  // Wallpaper fallback removed: only a genuine Native result is accepted.

  try {

    const response = await monitorCoreNative({
      type: "getDesktopVisualSnapshot",
      desktopId,
      maxWidth: MONITOR_WALLPAPER_MAX_WIDTH,
      maxHeight: MONITOR_WALLPAPER_MAX_HEIGHT,
      quality: 68
    });

    const rawDataUri = response?.wallpaper?.dataUri || "";
    const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);

    if (dataUri) monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);

    return dataUri;

  } catch (_) { return ""; }

}

async function monitorAcceptedDesktopBackground(desktopId, force = false) {
  const id=String(desktopId||"").toLowerCase();
  const tile=[...monitorDesktopThumbs.children].find(button=>String(button.dataset.desktopId||"").toLowerCase()===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  if(!visual?.isConnected||!renderer?.refreshBackground)return null;
  await renderer.refreshBackground(visual,id,{forceWallpaper:force===true}).catch(()=>null);
  return renderer.acceptedBackground?.(visual,id)||null;
}

function syncMonitorPreviewBackground(visual,desktopId) {
  const id=String(desktopId||"").toLowerCase();
  const selected=String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex]||"").toLowerCase();
  if(!id||id!==selected)return false;
  const snapshot=globalThis.MonitorDesktopThumbnailV2?.acceptedBackground?.(visual,id)||null;
  return snapshot ? monitorPreviewBackground.apply(id,snapshot) : monitorPreviewBackground.failed(id);
}

async function applyObservedWallpaper(desktopId, force = false) {
  const token = ++monitorWallpaperToken;
  const id=String(desktopId||"").toLowerCase();
  monitorPreviewBackground.begin(id);
  const tile=[...monitorDesktopThumbs.children].find(button=>String(button.dataset.desktopId||"").toLowerCase()===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  if(!visual?.isConnected||!renderer?.refreshBackground){
    if(token===monitorWallpaperToken)monitorPreviewBackground.failed(id);
    return false;
  }
  await renderer.refreshBackground(visual,id,{forceWallpaper:force===true}).catch(()=>null);
  if (token !== monitorWallpaperToken) return;
  return syncMonitorPreviewBackground(visual,id);
}

function monitorActDesktopVisualForDesktop(desktopId, state = monitorLastAiState) {

  const visual = state?.node_state?.desktop_visual;

  if (String(visual?.authority || "") !== "ACT" || String(visual?.source || "") !== "ACT_NATIVE_OBSERVER") return null;

  const desk = (Array.isArray(visual?.desktops) ? visual.desktops : []).find((row) => String(row?.desktop_id || "") === String(desktopId || ""));

  if (!desk) return null;

  const viewport = desk?.viewport || {};

  const windows = (Array.isArray(desk?.windows) ? desk.windows : []).map((row) => ({

    hwnd:String(row?.hwnd||""), left:Number(row?.rect?.left||0), top:Number(row?.rect?.top||0),

    width:Number(row?.rect?.width||0), height:Number(row?.rect?.height||0), z:Number(row?.z||0),

    conversationKey:String(row?.conversation_key||"")

  })).filter((row) => /^\d+$/.test(row.hwnd) && row.hwnd !== "0");

  return {ok:true, authority:"ACT", desktopId:String(desktopId||""), windows,

    previewVirtualLeft:Number(viewport.left||0), previewVirtualTop:Number(viewport.top||0),

    previewVirtualWidth:Number(viewport.width||0), previewVirtualHeight:Number(viewport.height||0)};

}

function monitorWindowUsesFrozenCapture(item) {
  const itemHwnd = String(item?.hwnd || "").trim();
  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();
  return /^[0-9]+$/.test(hostHwnd) && hostHwnd !== "0"
    && itemHwnd === hostHwnd && monitorIsOwnWindowTitle(item?.title);
}

function monitorWindowCanRefreshPixels(item) {
  // A Shell-cloaked HWND can still yield its real WGC pixels.  The capture
  // result, not the virtual-desktop cloak flag, decides whether pixels exist.
  // Minimized windows are excluded earlier and have no current surface here.
  return Boolean(item) && item.iconic !== true;
}

function monitorShouldKeepExistingCapture(existingState, existingSource, nextState) {
  const source = String(existingSource || "");
  return String(nextState || "") !== "captured"
    && String(existingState || "") === "captured"
    && (source.startsWith("blob:") || source.startsWith("data:image/"));
}

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

async function captureDesktopFrame(desktopId, profile = "main") {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return null;

  if (!desktopId) return null;

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") return null;

  const hasHostHwnd = true;

  const generation = monitorDesktopFrameGeneration(desktopId);

  const cacheKey = `${generation}:${desktopId}:${profile}:${hasHostHwnd ? hostHwnd : "ambiguous-host"}`;

  const cached = monitorFrameCache.get(cacheKey);
  if(cached&&Date.now()-Number(cached.at||0)<=MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS)return cached;
  if(cached)monitorFrameCache.delete(cacheKey);

  if (monitorFrameInflight.has(cacheKey)) return monitorFrameInflight.get(cacheKey);

  const job = (async () => {

    if (profile === "thumb" && String(desktopId) === String(monitorDesktopState.hostDesktopId || "")) {
      await ensureMonitorOwnFrozenSnapshot().catch(() => false);
    }

    const actMeta = monitorActDesktopVisualForDesktop(desktopId);

    // Window geometry/minimize state must come from the live Windows observer.

    // ACT metadata is still useful for identity, but stale ACT rects must never

    // override the actual desktop position shown in the preview/thumbs.

    const nativeMeta = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindows", desktopId, hostWindowHwnd: hostHwnd }

      : { type: "getDesktopWindows", desktopId }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    const meta = nativeMeta?.ok ? nativeMeta : actMeta;

    if (!meta?.ok) return null;

    const actByHwnd = new Map((Array.isArray(actMeta?.windows) ? actMeta.windows : []).map((item) => [String(item?.hwnd || ""), item]));

    const popupRuntime = await chrome.runtime.sendMessage({ type:"monitor-list-popup-runtime" }).catch(() => null);
    // Native intentionally excludes the Monitor host HWND while it captures a
    // desktop.  Keep that exclusion: including a live self-capture would make
    // Monitor recursively render itself.  The exact host is instead allowed
    // back in only through its bounded, frozen frame from the popup runtime.
    const monitorPopupWindows = (Array.isArray(popupRuntime?.windows) ? popupRuntime.windows : [])
      .filter((item) => String(item?.desktopId || "") === String(desktopId))
      .filter((item) => String(item?.hwnd || "") === hostHwnd && Boolean(item?.frozenDataUri));
    const windowRows = [...(Array.isArray(meta.windows) ? meta.windows : []), ...monitorPopupWindows];
    const windows = [...new Map(windowRows.map((item) => [String(item?.hwnd || ""), item])).values()]

      .map((item) => ({ ...item, conversationKey: String(item?.conversationKey || actByHwnd.get(String(item?.hwnd || ""))?.conversationKey || "") }));

    const handleSnapshot = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true }

      : { type: "getDesktopWindowHandles", desktopId, includeMonitorWindows: true }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    // Only a successful native snapshot can add/remove physical windows.
    const handlesConfirmed = handleSnapshot?.ok === true && Array.isArray(handleSnapshot.windows);
    const handleByHwnd = new Map((handlesConfirmed ? handleSnapshot.windows : []).map((item) => [String(item?.hwnd || ""), item]));
    const previousByHwnd = new Map(windows.map((item) => [String(item?.hwnd || ""), item]));
    // A confirmed native snapshot remains authoritative for real windows, but
    // it does not contain the deliberately excluded host Monitor HWND above.
    // Reinsert only that frozen self row after the snapshot so it cannot be
    // lost on every successful refresh.
    const currentWindowRows = handlesConfirmed
      ? [...handleByHwnd.values(), ...monitorPopupWindows]
      : windows;
    const currentWindows = [...new Map(currentWindowRows
      .filter((item) => /^[0-9]+$/.test(String(item?.hwnd || "")) && String(item.hwnd) !== "0" && (item.visible !== false || Boolean(item.iconic)))
      .map((item) => [String(item.hwnd), item])).values()];
    const liveWindows = currentWindows.map((item) => {
      const hwnd = String(item?.hwnd || "");
      const previous = previousByHwnd.get(hwnd);
      return { ...previous, ...item, conversationKey: String(item?.conversationKey || previous?.conversationKey || actByHwnd.get(hwnd)?.conversationKey || "") };
    });
    rememberMonitorDesktopWindows(desktopId, liveWindows);
    await refreshMonitorBctThumbnailProjectionForDesktop(desktopId);

    // Physical window existence/geometry/Z-order is native Windows truth. ACT only enriches identity.

    // Capture is optional visual content and must never decide whether a window exists in Monitor.

    const visibleWindows = liveWindows.filter((item) => !Boolean(item?.iconic));

    // Reconcile rendered windows against the current Native HWND snapshot. A minimized

    // window is still present in liveWindows, while a closed/destroyed window is absent.

    const liveHwndSet = new Set(liveWindows.map((item) => String(item?.hwnd || "")).filter(Boolean));

    const desktopTile = [...monitorDesktopThumbs.children].find((item) => String(item.dataset.desktopId || "") === String(desktopId));

    const desktopVisual = desktopTile?.querySelector(".monitor-desktop-thumb-visual");

    if (desktopVisual) {

      for (const stale of [...desktopVisual.querySelectorAll(".monitor-desktop-thumb-window")]) {

        const staleHwnd = String(stale.dataset.hwnd || "");

        if (!staleHwnd || liveHwndSet.has(staleHwnd)) continue;

        removeMonitorV2Window(staleHwnd);

        monitorThumbnailService.dispose(staleHwnd);

      }

    }

    const items = [...visibleWindows].sort((a,b)=>Number(b.z||0)-Number(a.z||0));

    // Coverage is complete; concurrency is bounded inside ThumbnailService.
    // Placeholder frames remain visible only while a capture is unavailable.
    const captureItems = MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED
      ? items.filter((item) => monitorWindowCanRefreshPixels(item) && !monitorWindowUsesFrozenCapture(item))
      : [];

    const frames = items.map((item) => ({
              capturedAt: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? Date.now() : 0,

      item,

      dataUri: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? String(item.frozenDataUri) : monitorWindowFallbackDataUri(item),

      captureState: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "captured" : "placeholder",

      physicalSource: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "monitor-frozen" : "windows-native",

      semanticSource: item?.conversationKey ? "act-enriched" : "none"

    }));

    const frameByHwnd = new Map(frames.map((entry) => [String(entry.item?.hwnd || ""), entry]));

    if (profile === "thumb") {

      // Desktop cards show real window pixels. Small captures plus a short HWND cache

      // keep ACT identity/state polling responsive; the label SVG is fallback only.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item?.hwnd || "");

        let dataUri = "";

        dataUri = await monitorGetWindowCapture(hwnd, "thumb");

        if (!dataUri) continue;

        const frameEntry = frameByHwnd.get(hwnd);

        if(frameEntry){
  const meta=monitorWindowCaptureService("thumb").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

      }

    } else {

      // Large selected preview keeps the real pixels. Native messaging is serialized,

      // so capture one window at a time to avoid starving identity/selection requests.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item.hwnd || "");

        const dataUri = await monitorGetWindowCapture(hwnd, "preview");
        if (dataUri) {

          const frameEntry = frameByHwnd.get(hwnd);

          if(frameEntry){
  const meta=monitorWindowCaptureService("preview").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

        }

      }

    }

    const observedWindowHwnds = [...new Set([

      ...visibleWindows.map((item) => String(item?.hwnd || "")),

      ...(handlesConfirmed ? handleSnapshot.windows : [])

        .filter((item) => Boolean(item?.visible) && !Boolean(item?.iconic))

        .map((item) => String(item?.hwnd || ""))

    ].filter(Boolean))];

    const frame = { at: Date.now(), meta: { ...meta, windows: visibleWindows, observedWindowHwnds }, frames };

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

    monitorFrameCache.set(cacheKey, frame);
    while (monitorFrameCache.size > MONITOR_FRAME_CACHE_LIMIT) {
      const oldestKey = monitorFrameCache.keys().next().value;
      if (!oldestKey) break;
      monitorFrameCache.delete(oldestKey);
    }

    return frame;

  })().finally(() => monitorFrameInflight.delete(cacheKey));

  monitorFrameInflight.set(cacheKey, job);

  return job;

}

function syncMonitorPauseOverlay(img, hwnd) {

  if (!img?.parentElement) return;

  const key = String(hwnd || "");

  let overlay = [...img.parentElement.querySelectorAll(".monitor-window-pause-overlay")].find((node)=>node.dataset.hwnd===key);

  if (img.classList.contains("monitor-desktop-thumb-window")
      && globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("status") === false) {
    overlay?.remove();
    return;
  }

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

function monitorAgeIdentityForWorkerGroup(members, state = monitorLastAiState) {

  const list=(Array.isArray(members)?members:[]).filter((worker)=>worker&&String(worker?.conversation_key||"").trim());

  if(!list.length)return { worker:null, conversationKey:"", profileId:"", ageing:0, nodeNumber:0 };

  const ranked=list.map((worker,index)=>{

    const physical=monitorCanonicalPhysicalLocation(worker,state);

    const label=String(physical?.label||resolveStableMonitorLocation(worker,state)||"").trim().toUpperCase();

    const match=/^D\d+-(\d+)$/.exec(label);

    return {worker,index,nodeNumber:match?Number(match[1]):Number.MAX_SAFE_INTEGER};

  }).sort((a,b)=>a.nodeNumber-b.nodeNumber||a.index-b.index);

  const picked=ranked[0]; const worker=picked?.worker||list[0];

  const conversationKey=String(worker?.conversation_key||"").trim();

  const profileId=String(worker?.profile_id||"").toUpperCase();

  const ghost=conversationKey?monitorGhostCache.get(conversationKey):null;

  return { worker, conversationKey, profileId, ageing:ghost?monitorGhostAgeing(ghost):0, nodeNumber:Number.isFinite(picked?.nodeNumber)&&picked.nodeNumber<Number.MAX_SAFE_INTEGER?picked.nodeNumber:0 };

}

function monitorAgeIdentityForHwnd(hwnd, state = monitorLastAiState) {

  const key=String(hwnd||"").trim(); if(!key||!state)return { worker:null, conversationKey:"", profileId:"", ageing:0, nodeNumber:0 };

  const workers=monitorWorkersForState(state).filter((worker)=>{

    if(classifyMonitorWorker(worker)!=="chatgpt"||!String(worker?.conversation_key||"").trim())return false;

    const location=monitorEndpointLocation(worker,state);

    return String(monitorResolvedWorkerHwnd(worker,state,location)||"").trim()===key;

  });

  return monitorAgeIdentityForWorkerGroup(workers,state);

}

function monitorObservedDesktopForHwnd(hwnd, state = monitorLastAiState) {
  const key=String(hwnd||"").trim();
  if(!key||!state)return null;
  const observer=state?.node_state?.observer||null;
  if(String(observer?.source||"")==="ACT_NATIVE_OBSERVER"){
    const row=(Array.isArray(observer?.windows)?observer.windows:[]).find((item)=>String(item?.hwnd||"").trim()===key);
    if(row){
      const desktopId=String(row?.desktop_id||"").trim();
      const desktopRow=(Array.isArray(observer?.desktops)?observer.desktops:[]).find((item)=>String(item?.desktop_id||"").trim()===desktopId);
      const desktop=Number(desktopRow?.index)||0;
      if(desktopId)return {desktopId,desktop,authority:"ACT_NATIVE_OBSERVER"};
    }
  }
  const remembered=monitorWindowDesktopLocations.get(key);
  const desktopId=String(remembered?.desktopId||"").trim();
  if(!desktopId)return null;
  const desktop=monitorDesktopState.desktopIds.indexOf(desktopId)+1;
  return {desktopId,desktop:desktop>0?desktop:0,authority:"MONITOR_NATIVE_EVENT"};
}

function monitorActNodeNumbersForHwnd(hwnd, state = monitorLastAiState) {
  const key=String(hwnd||"").trim();
  if(!key||!state)return [];
  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return [];
  const observed=monitorObservedDesktopForHwnd(key,state);
  if(!observed)return [];
  const numbers=new Set();
  const actNodes=Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[];
  for(const node of actNodes){
    if(String(node?.identity_authority||"")!=="ACT_TAB_CHAT") continue;
    if(String(node?.hwnd||"").trim()!==key) continue;
    const parts=monitorNodeIdentityParts(node?.node_label,node?.desktop_id);
    if(!parts.nodeNumber)continue;
    const slot=parts.nodeNumber;
    // Thumbnail node badges follow ACT_TAB_CHAT identity + exact HWND.
    // Desktop metadata may lag a move and must not hide an otherwise valid node number.
    if(Number.isInteger(slot)&&slot>0)numbers.add(slot);
  }
  return [...numbers].sort((a,b)=>a-b);
}

function monitorBadgeNodeNumbersForHwnd(hwnd, state = monitorLastAiState, options = null) {
  // BCT/RCC owns conversation labels, and Native/ACT maps the physical HWND.
  // Thumbnail labels use only the current-session/display contract. Legacy ACT
  // mappings may lag behind a Chrome tab detach/attach and must never merge two
  // different Chrome window_ids onto one physical thumbnail window.
  const includeTabIds = options?.includeTabIds === true;
  const tokenFor = (node) => {
    const match = /^N(\d+)$/.exec(String(node?.nodeLabel || "").trim());
    return match ? Number(match[1]) : "?";
  };
  const itemFor = (node, tabId = node?.tabId) => {
    const token = tokenFor(node);
    if (!includeTabIds) return token;
    const numericTabId = Number(tabId);
    return {
      token,
      tabId: Number.isInteger(numericTabId) && numericTabId >= 0 ? numericTabId : null,
    };
  };
  if (Array.isArray(monitorBctWindowNodesCache)) {
    const matched = monitorBctWindowNodesCache.filter((node) =>
      monitorBctDisplaySessionHwnd(node.windowId, node.instanceId, node.sessionId) === String(hwnd))
      .sort((left,right) =>
        (Number.isSafeInteger(left?.tabIndex) ? left.tabIndex : Number.MAX_SAFE_INTEGER) -
          (Number.isSafeInteger(right?.tabIndex) ? right.tabIndex : Number.MAX_SAFE_INTEGER) ||
        Number(left?.tabId || 0) - Number(right?.tabId || 0));
    const byTabId = new Map(matched.map((node) => [Number(node?.tabId), node])
      .filter(([tabId]) => Number.isInteger(tabId) && tabId >= 0));
    const browserWindowIds = [...new Set(matched.map((node) => Number(node?.windowId))
      .filter((windowId) => Number.isInteger(windowId)))];

    // When Chrome has just told us the current tab order, it is more current
    // than Core's next membership refresh. Keep non-BCT/UUID-less tabs visible
    // as `?` in that exact position rather than silently dropping them.
    if (browserWindowIds.length === 1) {
      const browserTabs = monitorBrowserVisualTabsForWindow(browserWindowIds[0]);
      if (browserTabs.length) {
        return browserTabs.map((tab) => itemFor(byTabId.get(Number(tab.tabId)), tab.tabId));
      }
    }

    return matched.map((node) => itemFor(node));
  }
  return monitorActNodeNumbersForHwnd(hwnd, state).map((token) => includeTabIds ? { token, tabId: null } : token);
}

function syncMonitorDesktopNumberBadge(img, hwnd) {

  if (!img?.parentElement) return;

  const key=String(hwnd||""), state=monitorLastAiState;

  let badge=[...img.parentElement.querySelectorAll(".monitor-window-desktop-badge")].find((node)=>node.dataset.hwnd===key);
  if(img.classList.contains("monitor-desktop-thumb-window")){
    badge?.remove();
    // Render once after the full Native frame is reconciled. Re-entering the
    // renderer here used to apply the window's physical offset to its child
    // badge a second time and made the result depend on image iteration order.
    return;
  }

  if(!state){badge?.remove();return;}

  const unique=monitorBadgeNodeNumbersForHwnd(key,state);

  if(!unique.length){ badge?.remove(); return; }

  if(!badge){badge=document.createElement("span");badge.className="monitor-node-number-badge monitor-window-desktop-badge";badge.dataset.hwnd=key;img.parentElement.append(badge);}

  badge.textContent=unique.length>1?unique.join("/"):String(unique[0]);

  badge.title=unique.length>1?`ACT 탭 노드 ${unique.join(" / ")}`:`ACT 노드 ${unique[0]}`;

  badge.style.left=img.style.left;badge.style.top=img.style.top;badge.style.zIndex=String(Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)));

}

function syncMonitorNonChatCountdown(img, hwnd, now = Date.now()) {
  // Non-ChatGPT Chrome windows remain filtered by the grace-state logic, but
  // they are not Monitor nodes and must not receive a visible countdown.
  if (img?.parentElement) {
    img.parentElement.querySelectorAll(".monitor-window-non-chat-countdown").forEach((node) => node.remove());
  }
  return;

  if (!img?.parentElement) return;

  const key=String(hwnd||"");

  let badge=[...img.parentElement.querySelectorAll(".monitor-window-non-chat-countdown")].find((node)=>node.dataset.hwnd===key);

  if(monitorHwndHasOpenChatEndpoint(key)){monitorNonChatStartedByHwnd.delete(key);const loc=monitorWindowDesktopLocations.get(key);if(loc)loc.nonChatSince=0;badge?.remove();return;}

  const since=Number(monitorNonChatStartedByHwnd.get(key)||monitorWindowDesktopLocations.get(key)?.nonChatSince||0);

  const remaining=since>0 ? Math.max(0, MONITOR_NON_CHAT_GRACE_MS-(now-since)) : 0;

  if(!remaining){badge?.remove();return;}

  if(!badge){badge=document.createElement("span");badge.className="monitor-window-non-chat-countdown";badge.dataset.hwnd=key;img.parentElement.append(badge);}

  badge.textContent=`${Math.max(1,Math.ceil(remaining/1000))}s`;

  badge.title="ChatGPT가 아닌 페이지 · Monitor 연결 해제까지 남은 시간";

  badge.style.left=img.style.left;badge.style.top=img.style.top;badge.style.width=img.style.width;badge.style.height=img.style.height;

  badge.style.zIndex=String(Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)));

  badge.classList.toggle("monitor-window-non-chat-countdown-thumb",img.classList.contains("monitor-desktop-thumb-window"));

}

function syncMonitorStatusLayer(img, hwnd) {

  if (!img?.parentElement) return;

  const isThumb=img.classList.contains("monitor-desktop-thumb-window");

  const isPreview=img.classList.contains("monitor-window-preview");

  if (!isThumb && !isPreview) return;

  const key=String(hwnd||"");

  const surface=isThumb?"thumb":"preview";

  const parent=img.parentElement;

  let layer=[...parent.querySelectorAll(".monitor-window-status-layer")].find((node)=>node.dataset.hwnd===key&&node.dataset.surface===surface);

  if(isThumb && globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("status") === false){

    layer?.remove();

    return;

  }

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

function reconcileFrame(container, frame, className) {

  if (!frame?.meta) return;

  const existing = new Map([...container.querySelectorAll(`.${className}`)].map(img => [img.dataset.hwnd, img]));
  const previousAgeLabels = new Map([...container.querySelectorAll(".monitor-window-capture-age-label")].map(label => [label.dataset.hwnd, label]));

  const observedSource = Array.isArray(frame.meta?.observedWindowHwnds) ? frame.meta.observedWindowHwnds : (Array.isArray(frame.meta?.windows) ? frame.meta.windows.map((item)=>item?.hwnd) : []);

  const observedHwnds = new Set(observedSource.map((item)=>String(item||"")).filter(Boolean));

  const vw = Math.max(1, Number(frame.meta.previewVirtualWidth ?? frame.meta.virtualWidth) || 1), vh = Math.max(1, Number(frame.meta.previewVirtualHeight ?? frame.meta.virtualHeight) || 1);

  const vl = Number(frame.meta.previewVirtualLeft ?? frame.meta.virtualLeft ?? 0), vt = Number(frame.meta.previewVirtualTop ?? frame.meta.virtualTop ?? 0);

  container.dataset.monitorPreviewVirtualLeft = String(vl);
  container.dataset.monitorPreviewVirtualTop = String(vt);
  container.dataset.monitorPreviewVirtualWidth = String(vw);
  container.dataset.monitorPreviewVirtualHeight = String(vh);

  for (const entry of frame.frames) {

    const key = String(entry.item.hwnd || "");

    let img = existing.get(key);

    if (!img) {

      img = document.createElement("img"); img.className = className; img.dataset.hwnd = key; img.alt = ""; container.append(img);

    }

    img.title = entry.item.title || "";

    img.dataset.physicalSource = entry.physicalSource || "windows-native";

    img.dataset.semanticSource = entry.semanticSource || (entry.item?.conversationKey ? "act-enriched" : "none");

    const captureTitle=String(entry.item?.title||"");
    const frozen=entry.physicalSource==="monitor-frozen";
    const freshEntry=frozen||monitorCaptureMatchesCurrentWindow(entry.captureTitle,captureTitle,entry.capturedAt);
    const nextCaptureState=freshEntry?(entry.captureState||"placeholder"):"placeholder";
    const previousFresh=monitorCaptureMatchesCurrentWindow(img.dataset.monitorCaptureTitle,captureTitle,img.dataset.monitorCapturedAt);
    const couldKeep=previousFresh&&(
      monitorShouldKeepExistingCapture(img.dataset.captureState,img.src,nextCaptureState)
      ||["held","stale"].includes(img.dataset.captureState)
    );
    const captureView = monitorChooseCaptureView({
      previousState: img.dataset.captureState,
      previousSource: couldKeep ? img.src : "",
      previousCapturedAt: Number(img.dataset.monitorCapturedAt || 0),
      nextState: nextCaptureState, nextSource: nextCaptureState==="captured"?entry.dataUri:"",
      nextCapturedAt: nextCaptureState==="captured"?Number(entry.capturedAt||Date.now()):0, now: Date.now()
    }, bwmUiLayoutControl?.read?.()?.captureFallback);
    img.dataset.captureState = captureView.state;
    img.dataset.monitorCapturedAt = String(captureView.capturedAt);
    if(captureView.state==="captured"&&nextCaptureState==="captured")img.dataset.monitorCaptureTitle=captureTitle;
    else if(!couldKeep)delete img.dataset.monitorCaptureTitle;
    img.dataset.captureFailureReason = nextCaptureState === "captured" ? "" :
      Number(entry.item?.cloaked || 0) !== 0 ? "CLOAKED" :
      !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED ? "CAPTURE_DISABLED" : "WGC_UNAVAILABLE";
    img.classList.toggle("monitor-window-capture-placeholder", captureView.state === "placeholder");
    img.classList.toggle("monitor-window-capture-stale", captureView.state === "stale");

    // Captured pixels are independent from ACT/node decoration. Identity delay may hide

    // a badge temporarily, but must never suppress the browser image itself.

    img.style.left = `${((Number(entry.item.left) - vl) / vw) * 100}%`;

    img.style.top = `${((Number(entry.item.top) - vt) / vh) * 100}%`;

    img.style.width = `${(Number(entry.item.width) / vw) * 100}%`; img.style.height = `${(Number(entry.item.height) / vh) * 100}%`;

    const nativeZ = Math.max(0, Number(entry.item.z) || 0);

    const nativeZIndex = String(10000 - Math.min(nativeZ, 9999));

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");

    const renderedSource = captureView.state === "placeholder" && !captureView.source ? monitorWindowFallbackDataUri(entry.item) : captureView.source;
    if (img.src !== renderedSource) img.src = renderedSource;
    img.title = captureView.label ? String(entry.item.title || "") + " - " + captureView.label : String(entry.item.title || "");
    let ageLabel = previousAgeLabels.get(key);
    if (captureView.label) {
      if (!ageLabel) {
        ageLabel = document.createElement("span");
        ageLabel.className = "monitor-window-capture-age-label";
        ageLabel.dataset.hwnd = key;
        container.append(ageLabel);
      }
      ageLabel.textContent = captureView.label;
      ageLabel.style.left = "calc(" + img.style.left + " + 3px)";
      ageLabel.style.top = "calc(" + img.style.top + " + " + img.style.height + " - 20px)";
      ageLabel.style.zIndex = String(Number(nativeZIndex) + 1);
    } else {
      ageLabel?.remove();
    }
    previousAgeLabels.delete(key);

    try {

      applyPersistentMonitorRoleClass(img, key);

      img.classList.toggle("monitor-window-row-hovered", Boolean(monitorHoveredHwnd) && key === monitorHoveredHwnd && !monitorSelectedHwnds.has(key));

      syncMonitorStatusLayer(img, key); syncMonitorPauseOverlay(img, key);

      syncMonitorDesktopNumberBadge(img, key); syncMonitorNonChatCountdown(img, key);

    } catch (error) { console.warn("DesktopWindow Monitor frame decoration delayed", key, error); }

    if (!img.dataset.monitorDragBound) {

      img.dataset.monitorDragBound = "1";

      img.draggable = false;

      img.addEventListener("pointerdown", beginMonitorWindowPointerDrag);

    }

    existing.delete(key);

  }

  for (const stale of existing.values()) {

    const key=String(stale.dataset.hwnd||"");

    // A transient WGC snapshot failure is not a window disappearance. Keep the last good

    // pixels and decorations while Native still reports the HWND on this desktop.

    if(observedHwnds.has(key)){applyPersistentMonitorRoleClass(stale,key);syncMonitorPauseOverlay(stale,key);syncMonitorDesktopNumberBadge(stale,key);syncMonitorNonChatCountdown(stale,key);continue;}

    stale.parentElement?.querySelectorAll(".monitor-window-status-layer, .monitor-window-pause-overlay, .monitor-window-desktop-badge, .monitor-window-non-chat-countdown").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();});

    stale.remove();

  }

  for (const unownedAgeLabel of previousAgeLabels.values()) { if (!observedHwnds.has(String(unownedAgeLabel.dataset.hwnd || ""))) unownedAgeLabel.remove(); }
if (monitorSelectedHwnds.size) applyMonitorWindowHighlight(monitorHighlightedHwnd, { preserve: true });

  scheduleMonitorHoverRecheck();

}
function syncMonitorThumbnailTabBadges(container, className) {

  if (className !== "monitor-desktop-thumb-window") return;
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("nodes") === false) {
    container.querySelectorAll(
      ".monitor-thumbnail-node-overlay, .monitor-thumbnail-tab-badge, .monitor-window-desktop-badge-thumb, .monitor-window-desktop-badge"
    ).forEach((node) => node.remove());
    container.dataset.monitorNodeOverlayStatus = "DISABLED_BY_LAYER_POLICY";
    container.dataset.monitorNodeOverlayCandidates = "0";
    container.dataset.monitorNodeOverlayMatched = "0";
    container.dataset.monitorNodeOverlayRendered = "0";
    return {status:"DISABLED_BY_LAYER_POLICY",candidates:0,matched:0,rendered:0};
  }
  const projection = globalThis.MonitorBctThumbnailProjection;
  if (!projection?.render) {
    container.dataset.monitorNodeOverlayStatus = "MODULE_MISSING";
    container.dataset.monitorNodeOverlayRendered = "0";
    return;
  }
  const selectedNode = (Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : []).find((node) =>
    monitorNodePanelSelection.get() && monitorBctNodeSelectionKey(node) === monitorNodePanelSelection.get()
  );
  const selectedHwnd = selectedNode
    ? monitorDisplayHwndForBrowserWindowId(selectedNode.windowId, monitorLastAiState, selectedNode.instanceId, selectedNode.sessionId)
    : "";
  const diagnostics = projection.render({
    container,
    state: monitorLastAiState,
    locations: monitorWindowDesktopLocations,
    highlightedHwnd: monitorBctNodeHighlightedHwnd,
    selectedNodeHwnd: selectedHwnd,
    selectedNodeToken: String(selectedNode?.nodeLabel || "").replace(/^N/, "") || "?",
    selectedNodeTabId: Number(selectedNode?.tabId),
    numbersForHwnd: (hwnd, state) => monitorBadgeNodeNumbersForHwnd(hwnd, state, { includeTabIds: true }),
  });
  container.dataset.monitorNodeOverlayStatus = String(diagnostics.status || "UNKNOWN");
  container.dataset.monitorNodeOverlayCandidates = String(Number(diagnostics.candidates) || 0);
  container.dataset.monitorNodeOverlayMatched = String(Number(diagnostics.matched) || 0);
  container.dataset.monitorNodeOverlayRendered = String(Number(diagnostics.rendered) || 0);
  scheduleMonitorThumbnailProjectionReceipt();
  return diagnostics;
}
function syncMonitorBctNodeLocationLabels() {
  // Refresh visible location only. No Chrome action, no polling, no stored binding.
  if (!Array.isArray(monitorBctWindowNodesCache) || !monitorWorkers) return;
  for (const row of monitorWorkers.querySelectorAll(".monitor-bct-node-row[data-window-id]")) {
    const hwnd = monitorDisplayHwndForBrowserWindowId(row.dataset.windowId, monitorLastAiState, row.dataset.instanceId, row.dataset.sessionId);
    const location = hwnd ? monitorWindowDesktopLocations.get(hwnd) : null;
    const index = location
      ? monitorDesktopState.desktopIds.indexOf(String(location.desktopId || ""))
      : -1;
    const position = row.querySelector(".monitor-bct-node-location");
    const node = monitorBctWindowNodesCache.find((item) =>
      String(item?.conversationKey || "") === String(row.dataset.conversationKey || "")
    );
    if (position) {
      position.textContent = monitorBctNodeLocationText(node, index);
      position.title = Array.isArray(node?.roleTags) && node.roleTags.length
        ? `${index >= 0 ? `D${index + 1}` : "위치 확인 중"} · ${node.roleTags.join(" · ")}`
        : position.textContent;
    }
    row.dataset.desktopNumber = index >= 0 ? String(index + 1) : "";
  }
}
let monitorThumbnailProjectionPublishSignature="";
let monitorThumbnailProjectionPublishTimer=0;
function monitorThumbnailProjectionRuntimeDiagnostics() {
  if(!monitorDesktopThumbs)return [];
  return [...monitorDesktopThumbs.children].map((button)=>{
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    return {
      desktop_id:String(button.dataset.desktopId||visual?.dataset?.desktopId||""),
      status:String(visual?.dataset?.monitorNodeOverlayStatus||"NOT_RENDERED"),
      candidates:Number(visual?.dataset?.monitorNodeOverlayCandidates)||0,
      matched:Number(visual?.dataset?.monitorNodeOverlayMatched)||0,
      rendered:Number(visual?.dataset?.monitorNodeOverlayRendered)||0,
    };
  });
}
function scheduleMonitorThumbnailProjectionReceipt() {
  const diagnostics=monitorThumbnailProjectionRuntimeDiagnostics();
  const signature=JSON.stringify(diagnostics);
  if(signature===monitorThumbnailProjectionPublishSignature)return;
  monitorThumbnailProjectionPublishSignature=signature;
  if(monitorThumbnailProjectionPublishTimer)clearTimeout(monitorThumbnailProjectionPublishTimer);
  monitorThumbnailProjectionPublishTimer=setTimeout(()=>{
    monitorThumbnailProjectionPublishTimer=0;
    void monitorPublishSharedInstance("thumbnail-projection");
  },500);
}
function syncMonitorAllDesktopThumbnailNodeBadges() {
  for (const button of monitorDesktopThumbs.children) {
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    if (visual?.isConnected) syncMonitorThumbnailTabBadges(visual,"monitor-desktop-thumb-window");
  }
  syncMonitorBctNodeLocationLabels();
  syncMonitorMinimizedNodeBadges(monitorLastAiState);
  syncMonitorBctNodeTargetHighlight();
  scheduleMonitorThumbnailProjectionReceipt();
}

let monitorWindowPointerDrag = null;

let monitorDesktopPointerDrag = null;

let monitorCreateDesktopDropBusy = false;

let monitorCreateDesktopDropConsumedUntil = 0;

let monitorExternalWindowDropTargetTimer = 0;

let monitorExternalWindowDropTargetSignature = "";

let monitorExternalWindowDropScreenOrigin = null;

async function syncMonitorNativeZOrder(desktopId) {

  const id = String(desktopId || "").trim();

  if (!id) return false;

  const result = await monitorNative({ type: "getDesktopWindows", desktopId: id }).catch(() => null);

  if (!result?.ok || !Array.isArray(result.windows)) return false;

  const zByHwnd = new Map(result.windows.map((item) => {

    const nativeZ = Math.max(0, Number(item?.z) || 0);

    return [String(item?.hwnd || ""), String(10000 - Math.min(nativeZ, 9999))];

  }));

  for (const img of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const nativeZIndex = zByHwnd.get(String(img.dataset.hwnd || ""));

    if (!nativeZIndex) continue;

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");
    syncMonitorStatusLayer(img, img.dataset.hwnd || "");
    syncMonitorPauseOverlay(img, img.dataset.hwnd || "");
    syncMonitorDesktopNumberBadge(img, img.dataset.hwnd || "");
    syncMonitorNonChatCountdown(img, img.dataset.hwnd || "");

  }

  return true;

}

function monitorSelectedEntries(primaryHwnd, sourceDesktopId) {

  const primary = String(primaryHwnd || "");

  const selected = monitorSelectedHwnds.has(primary) ? [...monitorSelectedHwnds] : [primary];

  return selected.map((hwnd) => {

    const location = monitorWindowDesktopLocations.get(String(hwnd));

    return { hwnd: String(hwnd), sourceDesktopId: String(location?.desktopId || sourceDesktopId || "") };

  }).filter((item) => /^\d+$/.test(item.hwnd) && item.hwnd !== "0" && item.sourceDesktopId === sourceDesktopId);

}

function monitorProfileIdForHwnd(hwnd) {

  const location = monitorWindowDesktopLocations.get(String(hwnd));

  const key = String(location?.conversationKey || "").trim();

  const endpoint = (Array.isArray(monitorLastAiState?.endpoints) ? monitorLastAiState.endpoints : []).find((item) => String(item?.conversation_key || "").trim() === key);

  const profile = String(endpoint?.profile_id || "").trim().toUpperCase();

  return ["GOOGLE", "NAVER"].includes(profile) ? profile : "";

}

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

async function snapshotAllChromeHwnds() {

  const snap = await monitorNative({ type: "getAllChromeWindowHandles" }).catch(() => null);

  return new Set((Array.isArray(snap?.hwnds) ? snap.hwnds : []).map(String).filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0"));

}

async function waitForNewChromeHwnd(before, timeoutMs = 7000) {

  const started = Date.now();

  while (Date.now() - started < timeoutMs) {

    await new Promise((resolve) => setTimeout(resolve, 120));

    const now = await snapshotAllChromeHwnds();

    for (const hwnd of now) if (/^\d+$/.test(hwnd) && hwnd !== "0" && !before.has(hwnd)) return hwnd;

  }

  return "";

}

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

async function performMonitorWindowDrop(entries, targetDesktopId, copyMode) {

  return copyMode ? cloneMonitorWindowSet(entries, targetDesktopId) : moveMonitorWindowSet(entries, targetDesktopId);

}

function createMonitorNodeDragGhost(img, event) {

  const rect = img.getBoundingClientRect();

  const ghost = document.createElement("div");

  ghost.className = "monitor-node-drag-ghost";

  ghost.style.width = `${Math.max(28, rect.width)}px`;

  ghost.style.height = `${Math.max(20, rect.height)}px`;

  ghost.style.left = "0px"; ghost.style.top = "0px";

  document.body.append(ghost);

  return ghost;

}

function moveMonitorNodeDragGhost(ghost, clientX, clientY) {

  if (!ghost) return;

  ghost.style.transform = `translate3d(${clientX}px, ${clientY}px, 0) translate(-50%, -50%)`;

}

function destroyMonitorNodeDragGhost(ghost) { ghost?.remove(); }

function monitorTrashDropTargetAt(clientX, clientY) {

  if (monitorNodeTrash.hidden) return null;

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.("#monitorNodeTrash") || null;

}

function clearMonitorTrashDropTarget() { monitorNodeTrash?.classList.remove("monitor-node-trash-drop-target","monitor-node-trash-drop-success"); }

function monitorConversationKeysForHwnd(hwnd,state=monitorLastAiState) {

  const target=String(hwnd||""); if(!target||!state)return [];

  return monitorWorkersForState(state).filter((worker)=>String(endpointOsWindowHandle(endpointForMonitorWorker(worker,state))||"")===target).map((worker)=>String(worker?.conversation_key||"").trim()).filter(Boolean);

}

function monitorTrashRecordForKey(key,sourceKind="list"){

  key=String(key||"").trim(); if(!key)return null;

  const state=monitorLastAiState, ghost=monitorGhostCache.get(key)||{};

  const worker=state?monitorWorkersForState(state).find((x)=>String(x?.conversation_key||"").trim()===key):null;

  const endpoint=worker&&state?endpointForMonitorWorker(worker,state):(Array.isArray(state?.endpoints)?state.endpoints.find((x)=>String(x?.conversation_key||"").trim()===key):null);

  const em=endpoint?.metadata||{}; const desktop=Number(ghost?.desktop||em.desktop_id||em.desktop_index||0), slot=Number(ghost?.slot||em.slot_index||0);
  const bctNode=(Array.isArray(monitorBctWindowNodesCache)?monitorBctWindowNodesCache:[]).find((item)=>String(item?.conversationKey||"")===key)||{};

  return {...ghost,conversation_key:key,profile_id:String(ghost?.profile_id||worker?.profile_id||endpoint?.profile_id||"").toUpperCase(),title:String(ghost?.title||endpoint?.title||bctNode?.title||""),meaningful_title:String(ghost?.meaningful_title||worker?.task_title||endpoint?.title||bctNode?.title||""),node_label:String(bctNode?.nodeLabel||ghost?.node_label||""),network_id:String(bctNode?.scopeId||ghost?.network_id||""),network_name:String(bctNode?.scopeName||ghost?.network_name||""),role_tags:Array.isArray(bctNode?.roleTags)?[...bctNode.roleTags]:(Array.isArray(ghost?.role_tags)?ghost.role_tags:[]),desktop:Number.isInteger(desktop)&&desktop>0?desktop:null,slot:Number.isInteger(slot)&&slot>0?slot:null,first_seen_ms:Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0),closed_at_ms:Number(ghost?.closed_at_ms||monitorGhostTime(endpoint?.closed_at)||0),trash_source:sourceKind==="thumbnail"?"thumbnail":"list",trashed_at_ms:Date.now()};

}

function persistMonitorTrashedNodes(){

  const records=[...monitorTrashRecords.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX);

  chrome.storage.local.set({[MONITOR_TRASHED_NODES_KEY]:[...monitorTrashedConversationKeys],[MONITOR_TRASH_RECORDS_KEY]:records});

}

function updateMonitorNodeTrashUndoUi(){

  clearTimeout(monitorNodeTrashUndoTimer); const now=Date.now(); monitorNodeTrash.hidden=false;

  if(!monitorNodeTrashUndoSnapshot||now>=monitorNodeTrashUndoExpiresAt){monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;monitorNodeTrashUndo.hidden=true;return;}

  monitorNodeTrashUndo.hidden=false; const seconds=Math.max(0,Math.ceil((monitorNodeTrashUndoExpiresAt-now)/1000)); monitorNodeTrashUndoCountdown.textContent=`${seconds}s`;

  monitorNodeTrashUndoTimer=setTimeout(updateMonitorNodeTrashUndoUi,250);

}

async function trashMonitorConversationKeys(keys,sourceKind="list"){

  const unique=[...new Set((keys||[]).map(String).filter(Boolean))].filter((key)=>!monitorTrashedConversationKeys.has(key)); if(!unique.length)return false;

  const endpoints=Array.isArray(monitorLastAiState?.endpoints)?monitorLastAiState.endpoints:[];

  const pending=[];

  for(const key of unique){

    const record=monitorTrashRecordForKey(key,sourceKind);

    const open=endpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key&&String(ep?.presence_state||"").toUpperCase()==="OPEN");

    const tabId=Number(open?.tab_id??open?.metadata?.tab_id);

    pending.push({key,record,open,tabId});

  }

  const failed=[];

  for(const item of pending){

    if(item.open&&Number.isInteger(item.tabId)&&item.tabId>=0){

      try{

        const ep=item.open;

        const body={conversation_key:item.key,tab_id:item.tabId,transport_instance_id:String(ep?.transport_instance_id||""),session_id:String(ep?.session_id||""),profile_id:String(ep?.profile_id||"")};

        const r=await actFetch(ORCHESTRATOR_CONVERSATION_CLOSE_TAB_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

        const data=await r.json().catch(()=>({}));

        if(!r.ok||!data?.ok||!data?.verified||!data?.closed){failed.push(item.key);continue;}

      }catch(_){failed.push(item.key);continue;}

    }

    if(item.record)monitorTrashRecords.set(item.key,item.record);

    monitorTrashedConversationKeys.add(item.key);monitorHiddenGhosts.delete(item.key);

  }

  if(failed.length){setMonitorStatus(`연결 탭 ${failed.length}개 닫기 실패 · 해당 노드는 유지됨`,false);}

  const succeeded=pending.filter((item)=>!failed.includes(item.key)).map((item)=>item.key);

  if(succeeded.length){persistMonitorTrashedNodes();monitorNodeTrashUndoSnapshot={keys:succeeded};monitorNodeTrashUndoExpiresAt=Date.now()+MONITOR_NODE_TRASH_UNDO_MS;updateMonitorNodeTrashUndoUi();if(monitorLastAiState)renderWorkers(monitorLastAiState);}

  if(succeeded.length&&!failed.length)setMonitorStatus(`노드 ${succeeded.length}개 삭제 · 연결 탭 닫힘 확인`,true);

  return succeeded.length>0;

}

function refreshMonitorRecoveryMenu(){

  if(!(monitorRecoveryPickerState.isOpen()&&monitorClosedRecoveryMenu&&monitorLastAiState))return;

  const panes=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane-scroll')].map((el)=>({cls:el.parentElement?.className||'',top:el.scrollTop}));

  monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));

  for(const saved of panes){const pane=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane')].find((el)=>(el.className||'')===saved.cls);const scroll=pane?.querySelector('.monitor-trash-pane-scroll');if(scroll)scroll.scrollTop=saved.top;}

}

function restoreMonitorTrashRecord(key){key=String(key||"");monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}

function deleteMonitorTrashRecord(key){key=String(key||"");monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}

function deleteMonitorRecoveryRecord(key){

  key=String(key||""); if(!key)return; monitorTrashRecords.delete(key); monitorTrashedConversationKeys.add(key); monitorGhostCache.delete(key); monitorHiddenGhosts.delete(key);

  const items=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>String(x?.conversation_key||"").trim()!==key); monitorRebootSnapshot={...monitorRebootSnapshot,items};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

function monitorDeletedDesktopLoadImage(src){

  return new Promise((resolve)=>{

    const value=String(src||"");

    if(!value){resolve(null);return;}

    const image=new Image();

    image.onload=()=>resolve(image);

    image.onerror=()=>resolve(null);

    image.src=value;

  });

}

function monitorDeletedDesktopDrawCover(ctx,image,width,height){

  if(!ctx||!image||!image.naturalWidth||!image.naturalHeight)return;

  const scale=Math.max(width/image.naturalWidth,height/image.naturalHeight);

  const drawWidth=image.naturalWidth*scale,drawHeight=image.naturalHeight*scale;

  ctx.drawImage(image,(width-drawWidth)/2,(height-drawHeight)/2,drawWidth,drawHeight);

}

async function monitorFreezeDesktopThumbnail(desktopId,wallpaperDataUri=""){

  if(!desktopId)return "";

  try{

    const width=320,height=180;

    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;

    const ctx=canvas.getContext("2d",{alpha:false});if(!ctx)return "";

    ctx.fillStyle="#121821";ctx.fillRect(0,0,width,height);

    const wallpaper=String(wallpaperDataUri||await getObservedWallpaper(desktopId,false).catch(()=>""));

    const wallpaperImage=await monitorDeletedDesktopLoadImage(wallpaper);

    if(wallpaperImage)monitorDeletedDesktopDrawCover(ctx,wallpaperImage,width,height);

    const tile=[...monitorDesktopThumbs.children].find((button)=>String(button.dataset.desktopId||"")===String(desktopId));

    const visual=tile?.querySelector(".monitor-desktop-thumb-visual");

    if(visual&&visual.dataset.monitorFrameReady!=="1")await refreshDesktopThumb(visual,desktopId).catch(()=>false);

    let painted=0;

    if(visual){

      const images=[...visual.querySelectorAll(".monitor-desktop-thumb-window")].filter((node)=>String(node.src||"")).sort((a,b)=>Number(a.style.zIndex||a.dataset.nativeZIndex||0)-Number(b.style.zIndex||b.dataset.nativeZIndex||0));

      for(const node of images){

        const image=await monitorDeletedDesktopLoadImage(node.src);

        if(!image)continue;

        const left=(parseFloat(node.style.left)||0)*width/100,top=(parseFloat(node.style.top)||0)*height/100;

        const w=(parseFloat(node.style.width)||0)*width/100,h=(parseFloat(node.style.height)||0)*height/100;

        if(w<=0||h<=0)continue;

        ctx.drawImage(image,left,top,w,h);painted+=1;

      }

    }

    if(!painted){

      const frame=await captureDesktopFrame(desktopId,"thumb").catch(()=>null);

      if(frame?.meta){

        const vw=Math.max(1,Number(frame.meta.previewVirtualWidth??frame.meta.virtualWidth)||1),vh=Math.max(1,Number(frame.meta.previewVirtualHeight??frame.meta.virtualHeight)||1);

        const vl=Number(frame.meta.previewVirtualLeft??frame.meta.virtualLeft??0),vt=Number(frame.meta.previewVirtualTop??frame.meta.virtualTop??0);

        for(const entry of Array.isArray(frame.frames)?frame.frames:[]){

          const image=await monitorDeletedDesktopLoadImage(entry?.dataUri),item=entry?.item||{};

          if(!image)continue;

          const left=((Number(item.left)-vl)/vw)*width,top=((Number(item.top)-vt)/vh)*height,w=(Number(item.width)/vw)*width,h=(Number(item.height)/vh)*height;

          if(![left,top,w,h].every(Number.isFinite)||w<=0||h<=0)continue;

          ctx.drawImage(image,left,top,w,h);painted+=1;

        }

      }

    }

    try{return canvas.toDataURL("image/webp",0.66)||canvas.toDataURL("image/png");}

    catch(_){return canvas.toDataURL("image/png");}

  }catch(_){return "";}

}

function persistMonitorTrashedDesktops(){chrome.storage.local.set({[MONITOR_TRASHED_DESKTOPS_KEY]:[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,30)});}

function monitorDesktopNodeSnapshots(desktopId,index,state=monitorLastAiState){const targetDesktop=Number(index)+1,out=[];for(const worker of monitorWorkersForState(state||{})){const key=String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim();if(!key)continue;const loc=monitorCanonicalPhysicalLocation(worker,state||{}),actNode=monitorActBrowserNode(worker,state||{}),sameId=desktopId&&String(actNode?.desktop_id||"").trim()===String(desktopId);if(!(sameId||Number(loc?.desktop)===targetDesktop))continue;out.push({conversation_key:key,profile_id:String(worker?.profile_id||worker?.__endpoint?.profile_id||"").toUpperCase(),title:String(worker?.task_title||worker?.title||worker?.__endpoint?.title||""),node_label:String(actNode?.node_label||loc?.label||""),slot:Number(loc?.slot||0)||null,hwnd:String(loc?.hwnd||actNode?.hwnd||"")});}return out;}

function restoreMonitorDesktopNodeSnapshots(nodes){for(const item of Array.isArray(nodes)?nodes:[]){const key=String(item?.conversation_key||"");if(!key)continue;monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);monitorHiddenGhosts.delete(key);}persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);}

function storeMonitorTrashedDesktop(snapshot){const id=String(snapshot?.desktopId||`desktop-${Date.now()}`);monitorTrashedDesktops.set(id,{...snapshot,id,trashed_at_ms:Date.now()});persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}

function deleteMonitorTrashedDesktop(id){monitorTrashedDesktops.delete(String(id||""));persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}

async function restoreMonitorTrashedDesktop(id,button){const item=monitorTrashedDesktops.get(String(id||""));if(!item)return;if(button)button.disabled=true;try{const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:item.hwnds||[]});if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");restoreMonitorDesktopNodeSnapshots(item.nodes);deleteMonitorTrashedDesktop(id);renderVirtualDesktops(result);}catch(error){setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false);if(button)button.disabled=false;}}

function clearMonitorThumbnailRecovery(){

  monitorTrashedDesktops.clear(); persistMonitorTrashedDesktops();

  for(const [key,item] of [...monitorTrashRecords]) if(String(item?.trash_source||"list")==="thumbnail"){monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(String(key));}

  persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

function clearMonitorConversationRecovery(){

  const recovery=monitorClosedConversationRecoveryItems(monitorLastAiState);

  for(const item of recovery){const key=String(item?.conversation_key||"").trim();if(key){monitorTrashedConversationKeys.add(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);}}

  for(const [key,item] of [...monitorTrashRecords]) if(String(item?.trash_source||"list")!=="thumbnail"){monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(String(key));}

  monitorRebootSnapshot={...monitorRebootSnapshot,items:[]};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

monitorNodeTrashUndoButton.addEventListener("click",()=>{const snap=monitorNodeTrashUndoSnapshot;if(!snap||Date.now()>=monitorNodeTrashUndoExpiresAt)return;for(const key of snap.keys||[]){monitorTrashedConversationKeys.delete(String(key));monitorTrashRecords.delete(String(key));}persistMonitorTrashedNodes();monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;updateMonitorNodeTrashUndoUi();if(monitorLastAiState)renderWorkers(monitorLastAiState);});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_TRASHED_NODES_KEY,MONITOR_TRASH_RECORDS_KEY,MONITOR_TRASHED_NOTES_KEY,MONITOR_TRASHED_DESKTOPS_KEY],(data)=>{for(const key of Array.isArray(data?.[MONITOR_TRASHED_NODES_KEY])?data[MONITOR_TRASHED_NODES_KEY]:[])monitorTrashedConversationKeys.add(String(key));for(const item of Array.isArray(data?.[MONITOR_TRASH_RECORDS_KEY])?data[MONITOR_TRASH_RECORDS_KEY]:[])if(item?.conversation_key)monitorTrashRecords.set(String(item.conversation_key),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_NOTES_KEY])?data[MONITOR_TRASHED_NOTES_KEY]:[])if(item?.id)monitorTrashedNotes.set(String(item.id),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_DESKTOPS_KEY])?data[MONITOR_TRASHED_DESKTOPS_KEY]:[])if(item?.id)monitorTrashedDesktops.set(String(item.id),item);if(monitorLastAiState)renderWorkers(monitorLastAiState);});

function monitorDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.(".monitor-desktop-thumb") || null;

}

function monitorCreateDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.("#monitorCreateDesktop") === monitorCreateDesktop ? monitorCreateDesktop : null;

}

function clearMonitorDesktopDropTargets() {

  for (const button of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb")) button.classList.remove("monitor-desktop-drop-target");

  monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-target");

}

function scheduleMonitorExternalWindowDropTargets() {
  if (monitorExternalWindowDropTargetTimer) return;
  monitorExternalWindowDropTargetTimer = setTimeout(() => {
    monitorExternalWindowDropTargetTimer = 0;
    void syncMonitorExternalWindowDropTargets();
  }, 0);
}

function recordMonitorExternalWindowDropPointer(event) {
  const screenX = Number(event?.screenX);
  const screenY = Number(event?.screenY);
  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  if (![screenX, screenY, clientX, clientY].every(Number.isFinite)) return;
  // A pointer observed by the Monitor document gives the exact document-to-
  // screen offset, including Chrome's non-document chrome. This is more
  // reliable than assuming window.screenY is the document origin.
  monitorExternalWindowDropScreenOrigin = { left: screenX - clientX, top: screenY - clientY };
}

async function syncMonitorExternalWindowDropTargets() {
  const hostWindowHwnd = String(monitorDesktopState?.hostWindowHwnd || "").trim();
  const screenScale = Math.max(.5, Math.min(4, Number(window.devicePixelRatio) || 1));
  const screenOrigin = monitorExternalWindowDropScreenOrigin || { left: Number(window.screenX || 0), top: Number(window.screenY || 0) };
  const targets = [...monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb[data-desktop-id]")]
    .map((tile) => {
      const desktopId = String(tile.dataset.desktopId || "").trim().toLowerCase();
      const rect = tile.getBoundingClientRect();
      return { desktopId, left: screenOrigin.left + rect.left, top: screenOrigin.top + rect.top, width: rect.width, height: rect.height };
    })
    .filter((target) => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(target.desktopId) && target.width >= 16 && target.height >= 16);
  const signature = JSON.stringify({ hostWindowHwnd, screenScale, targets });
  if (signature === monitorExternalWindowDropTargetSignature) return;
  monitorExternalWindowDropTargetSignature = signature;
  if (!/^\d+$/.test(hostWindowHwnd) || hostWindowHwnd === "0") return;
  const receipt = await monitorNative({ type:"setExternalWindowDropTargets", hostWindowHwnd, screenScale, targets }).catch(() => null);
  if (!receipt?.ok) monitorExternalWindowDropTargetSignature = "";
}

async function handleMonitorExternalWindowDropFinished(event) {
  if (event?.ok !== true) return;
  const desktopId = String(event.desktopId || "").trim().toLowerCase();
  invalidateMonitorDesktopFrames(...[desktopId].filter(Boolean));
  await refreshVirtualDesktops();
  void refreshWindowsCurrentState();
  void refreshSelectedThumb();
}

let monitorWorkerRowPointerDrag = null;

let monitorWorkerRowSuppressClickUntil = 0;

function monitorWorkerRowOrderTargetAt(clientX, clientY) {

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.(".monitor-worker-row[data-conversation-key][data-desktop-id]") || null;

}

function clearMonitorWorkerOrderTargets() {

  for(const row of monitorWorkers.querySelectorAll(".monitor-worker-row.monitor-worker-order-target-before,.monitor-worker-row.monitor-worker-order-target-after")) row.classList.remove("monitor-worker-order-target-before","monitor-worker-order-target-after");

}

function beginMonitorWorkerRowPointerDrag(event) {

  if(monitorRoleAssignMode) return;

  if(event.button!==0 || event.target?.closest?.("button,input,textarea,select,a,.monitor-work-state")) return;

  const row=event.currentTarget, hwnd=String(row?.dataset?.hwnd||""), key=String(row?.dataset?.conversationKey||""), sourceDesktopId=String(row?.dataset?.desktopId||"");

  let keys=[key]; try{const parsed=JSON.parse(String(row?.dataset?.conversationKeys||"[]"));if(Array.isArray(parsed)&&parsed.length)keys=[...new Set(parsed.map(String).filter(Boolean))];}catch(_){}

  if(!/^\d+$/.test(hwnd)||hwnd==="0"||!key||!sourceDesktopId) return;

  const currentOrder=[...monitorWorkers.querySelectorAll(`.monitor-worker-row[data-desktop-id="${CSS.escape(sourceDesktopId)}"][data-conversation-key]`)].map(x=>String(x.dataset.conversationKey||"")).filter(Boolean);

  if(currentOrder.length) monitorSetWorkerOrder(sourceDesktopId,currentOrder);

  monitorWorkerRowPointerDrag={pointerId:event.pointerId,row,hwnd,key,keys,sourceDesktopId,entries:[{hwnd,sourceDesktopId}],ghost:null,startX:event.clientX,startY:event.clientY,moved:false};

}

function updateMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||event.pointerId!==drag.pointerId)return;

  if(!drag.moved&&Math.hypot(event.clientX-drag.startX,event.clientY-drag.startY)>=10){

    drag.moved=true;

    drag.ghost=createMonitorNodeDragGhost(drag.row,event); drag.ghost.classList.add("monitor-worker-row-drag-ghost"); moveMonitorNodeDragGhost(drag.ghost,event.clientX,event.clientY);

    drag.row.classList.add("monitor-worker-row-dragging");

    try{drag.row.setPointerCapture(event.pointerId);}catch(_){}

  }

  if(!drag.moved)return;

  event.preventDefault(); moveMonitorNodeDragGhost(drag.ghost,event.clientX,event.clientY); clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

  if(monitorTrashDropTargetAt(event.clientX,event.clientY)){monitorNodeTrash.classList.add("monitor-node-trash-drop-target");return;}

  if(monitorCreateDesktopDropTargetAt(event.clientX,event.clientY)){monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");return;}

  const desktopTarget=monitorDesktopDropTargetAt(event.clientX,event.clientY);

  if(desktopTarget?.dataset?.desktopId&&desktopTarget.dataset.desktopId!==drag.sourceDesktopId){desktopTarget.classList.add("monitor-desktop-drop-target");return;}

  const rowTarget=monitorWorkerRowOrderTargetAt(event.clientX,event.clientY);

  if(rowTarget&&rowTarget!==drag.row&&String(rowTarget.dataset.desktopId||"")===drag.sourceDesktopId){

    const rect=rowTarget.getBoundingClientRect(), after=event.clientY>rect.top+rect.height/2;

    rowTarget.classList.add(after?"monitor-worker-order-target-after":"monitor-worker-order-target-before");

  }

}

async function finishMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||event.pointerId!==drag.pointerId)return;

  monitorWorkerRowPointerDrag=null; drag.row?.classList.remove("monitor-worker-row-dragging"); destroyMonitorNodeDragGhost(drag.ghost);

  try{drag.row?.releasePointerCapture(event.pointerId);}catch(_){}

  if(!drag.moved){clearMonitorDesktopDropTargets();clearMonitorWorkerOrderTargets();return;}

  monitorWorkerRowSuppressClickUntil=Date.now()+650;

  const trashTarget=monitorTrashDropTargetAt(event.clientX,event.clientY);

  const createTarget=trashTarget?null:monitorCreateDesktopDropTargetAt(event.clientX,event.clientY);

  const desktopTarget=createTarget?null:monitorDesktopDropTargetAt(event.clientX,event.clientY);

  const rowTarget=(!createTarget&&!desktopTarget)?monitorWorkerRowOrderTargetAt(event.clientX,event.clientY):null;

  const rect=rowTarget?.getBoundingClientRect?.(), after=Boolean(rowTarget&&event.clientY>rect.top+rect.height/2);

  clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

  if(trashTarget){if(await trashMonitorConversationKeys(drag.keys||[drag.key],"list")){monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);}return;}

  if(createTarget){

    monitorCreateDesktopDropConsumedUntil=Date.now()+700; monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

    try{const created=await createDesktopForDrop(drag.sourceDesktopId,[drag.hwnd],false);if(created?.ok)monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");}

    catch(error){setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message||error}`,false);}

    finally{setTimeout(()=>monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending","monitor-create-desktop-drop-success"),650);}

    return;

  }

  const targetDesktopId=String(desktopTarget?.dataset?.desktopId||"");

  if(targetDesktopId&&targetDesktopId!==drag.sourceDesktopId){

    desktopTarget.classList.add("monitor-desktop-drop-pending");

    try{if(await performMonitorWindowDrop(drag.entries,targetDesktopId,false)){monitorMoveWorkerOrderKey(drag.key,drag.sourceDesktopId,targetDesktopId);desktopTarget.classList.add("monitor-desktop-drop-success");}}

    finally{setTimeout(()=>desktopTarget.classList.remove("monitor-desktop-drop-pending","monitor-desktop-drop-success"),650);}

    return;

  }

  if(rowTarget&&rowTarget!==drag.row&&String(rowTarget.dataset.desktopId||"")===drag.sourceDesktopId){

    const targetKey=String(rowTarget.dataset.conversationKey||"");

    if(monitorReorderWorkerKey(drag.sourceDesktopId,drag.key,targetKey,after)&&monitorLastAiState)renderWorkers(monitorLastAiState);

  }

}

function cancelMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||(event?.pointerId!=null&&event.pointerId!==drag.pointerId))return;

  monitorWorkerRowPointerDrag=null; drag.row?.classList.remove("monitor-worker-row-dragging"); destroyMonitorNodeDragGhost(drag.ghost); clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

}

function beginMonitorWindowPointerDrag(event) {

  if (event.button !== 0) return;

  const img = event.currentTarget;

  const hwnd = String(img?.dataset?.hwnd || "");

  if (!/^\d+$/.test(hwnd) || hwnd === "0") return;

  // Clicking the window surface inside Monitor counts as reading the same alert as clicking the real Chrome window.

  monitorAcknowledgePostWorkForHwnd(hwnd);

  const sourceDesktopId = img.closest(".monitor-desktop-thumb")?.dataset.desktopId || img.parentElement?.dataset?.desktopId || "";

  const initiallySelected = monitorSelectedHwnds.has(hwnd);

  if (event.ctrlKey) applyMonitorWindowHighlight(hwnd, { toggle: true }); else if (!initiallySelected) applyMonitorWindowHighlight(hwnd);

  if (!monitorSelectedHwnds.has(hwnd)) return;

  const entries = monitorSelectedEntries(hwnd, sourceDesktopId);

  const ghost = createMonitorNodeDragGhost(img, event);

  moveMonitorNodeDragGhost(ghost, event.clientX, event.clientY);

  monitorWindowPointerDrag = { pointerId: event.pointerId, hwnd, sourceDesktopId, entries, img, ghost, startX: event.clientX, startY: event.clientY, moved: false, copyMode: Boolean(event.shiftKey), initiallySelected, ctrlSelectionHandled: Boolean(event.ctrlKey) };

  img.classList.add("monitor-window-dragging");

  try { img.setPointerCapture(event.pointerId); } catch (_) {}

  event.preventDefault();

}

function updateMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= 5) drag.moved = true;

  moveMonitorNodeDragGhost(drag.ghost, event.clientX, event.clientY);

  clearMonitorDesktopDropTargets();

  clearMonitorHierarchyTargets();

  clearMonitorTrashDropTarget();

  if (monitorTrashDropTargetAt(event.clientX,event.clientY)) { monitorNodeTrash.classList.add("monitor-node-trash-drop-target"); return; }

  if (monitorStructureOpen) {

    const hierarchyTarget = monitorHierarchyTargetAt(event.clientX, event.clientY);

    if (hierarchyTarget) hierarchyTarget.classList.add("monitor-org-socket-target");

    return;

  }

  if (monitorCreateDesktopDropTargetAt(event.clientX, event.clientY)) {

    monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");

    return;

  }

  const target = monitorDesktopDropTargetAt(event.clientX, event.clientY);

  if (target && target.dataset.desktopId && (event.shiftKey || drag.copyMode || target.dataset.desktopId !== drag.sourceDesktopId)) target.classList.add("monitor-desktop-drop-target");

}

async function finishMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  monitorWindowPointerDrag = null;

  drag.img?.classList.remove("monitor-window-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  try { drag.img?.releasePointerCapture(event.pointerId); } catch (_) {}

  if (!drag.moved) {

    if (drag.initiallySelected && !drag.ctrlSelectionHandled) applyMonitorWindowHighlight(drag.hwnd, { toggle: true });

    clearMonitorDesktopDropTargets(); clearMonitorHierarchyTargets(); return;

  }

  if (monitorStructureOpen) {

    const hierarchyTarget = monitorHierarchyTargetAt(event.clientX, event.clientY);

    clearMonitorHierarchyTargets();

    if (!hierarchyTarget) return;

    try { await monitorHierarchyApplyDrop(hierarchyTarget, drag.hwnd); }

    catch (error) { const st=document.getElementById("monitorStructureStatus"); if(st)st.textContent=`지정 실패 · ${monitorDiagTextError(error?.message||error)}`; }

    return;

  }

  const trashTarget = monitorTrashDropTargetAt(event.clientX,event.clientY);

  const createTarget = trashTarget ? null : monitorCreateDesktopDropTargetAt(event.clientX, event.clientY);

  const target = (trashTarget||createTarget) ? null : monitorDesktopDropTargetAt(event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (trashTarget) { const keys=[...new Set((drag.entries||[]).flatMap((entry)=>monitorConversationKeysForHwnd(entry.hwnd)))]; if(await trashMonitorConversationKeys(keys,"thumbnail")){monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);} return; }

  if (createTarget) {

    monitorCreateDesktopDropConsumedUntil = Date.now() + 700;

    monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

    try {

      const created = await createDesktopForDrop(drag.sourceDesktopId, drag.entries.map((item) => item.hwnd), Boolean(event.shiftKey || drag.copyMode));

      if (created?.ok) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");

    } catch (error) {

      setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message || error}`, false);

    } finally {

      setTimeout(() => monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending", "monitor-create-desktop-drop-success"), 650);

    }

    return;

  }

  const targetDesktopId = target?.dataset?.desktopId || "";

  const copyMode = Boolean(event.shiftKey || drag.copyMode);

  if (!target || !targetDesktopId || (!copyMode && targetDesktopId === drag.sourceDesktopId)) return;

  target.classList.add("monitor-desktop-drop-pending");

  try {

    if (await performMonitorWindowDrop(drag.entries, targetDesktopId, copyMode)) target.classList.add("monitor-desktop-drop-success");

  } finally {

    setTimeout(() => target.classList.remove("monitor-desktop-drop-pending", "monitor-desktop-drop-success"), 650);

  }

}

function cancelMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;

  monitorWindowPointerDrag = null;

  drag.img?.classList.remove("monitor-window-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  clearMonitorDesktopDropTargets();

  clearMonitorHierarchyTargets();

  clearMonitorTrashDropTarget();

}

function beginMonitorDesktopPointerDrag(event) {

  if (event.button !== 0 || event.target?.closest?.(".monitor-desktop-thumb-window")) return;

  const button = event.currentTarget;

  const sourceDesktopId = String(button?.dataset?.desktopId || "");

  if (!sourceDesktopId) return;

  const visual = button.querySelector(".monitor-desktop-thumb-visual") || button;

  const ghost = createMonitorNodeDragGhost(visual, event);

  ghost.classList.add("monitor-desktop-drag-ghost");

  moveMonitorNodeDragGhost(ghost, event.clientX, event.clientY);

  monitorDesktopPointerDrag = { pointerId: event.pointerId, sourceDesktopId, button, ghost, startX: event.clientX, startY: event.clientY, moved: false, copyMode: Boolean(event.shiftKey) };

  try { button.setPointerCapture(event.pointerId); } catch (_) {}

}

function updateMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= 6) {

    drag.moved = true;

    drag.button.classList.add("monitor-desktop-dragging");

  }

  if (!drag.moved) return;

  event.preventDefault();

  moveMonitorNodeDragGhost(drag.ghost, event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (drag.sourceDesktopId !== monitorDesktopState.currentDesktopId && monitorTrashDropTargetAt(event.clientX,event.clientY)) { monitorNodeTrash.classList.add("monitor-node-trash-drop-target"); return; }

  if (monitorCreateDesktopDropTargetAt(event.clientX, event.clientY)) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");

}

async function finishMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  monitorDesktopPointerDrag = null;

  drag.button.classList.remove("monitor-desktop-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  try { drag.button.releasePointerCapture(event.pointerId); } catch (_) {}

  if (!drag.moved) { clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget(); return; }

  drag.button.dataset.monitorDropSuppressClick = "1";

  setTimeout(() => delete drag.button.dataset.monitorDropSuppressClick, 0);

  const trashTarget = drag.sourceDesktopId !== monitorDesktopState.currentDesktopId ? monitorTrashDropTargetAt(event.clientX,event.clientY) : null;

  const createTarget = trashTarget ? null : monitorCreateDesktopDropTargetAt(event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (trashTarget) {

    const sourceIndex=monitorDesktopState.desktopIds.indexOf(drag.sourceDesktopId);

    if(sourceIndex>=0){await removeVirtualDesktopPreview(sourceIndex,{trashDrop:true});monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);}

    return;

  }

  if (!createTarget) return;

  monitorCreateDesktopDropConsumedUntil = Date.now() + 700;

  monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

  try {

    const hwnds = await getDesktopBrowserWindowHandles(drag.sourceDesktopId);

    const created = await createDesktopForDrop(drag.sourceDesktopId, hwnds, Boolean(event.shiftKey || drag.copyMode));

    if (created?.ok) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");

  } catch (error) {

    setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message || error}`, false);

  } finally {

    setTimeout(() => monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending", "monitor-create-desktop-drop-success"), 650);

  }

}

function cancelMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;

  monitorDesktopPointerDrag = null;

  drag.button?.classList.remove("monitor-desktop-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

}

document.addEventListener("pointermove", updateMonitorWindowPointerDrag, true);

document.addEventListener("pointermove", recordMonitorExternalWindowDropPointer, true);

document.addEventListener("pointerup", finishMonitorWindowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWindowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointerup", finishMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorDesktopPointerDrag, true);

document.addEventListener("pointerup", finishMonitorDesktopPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorDesktopPointerDrag, true);

function invalidateMonitorDesktopFrames(...desktopIds) {

  // Every invalidation starts a new capture generation so an older in-flight

  // capture can never repopulate the cache after a move/layout change.

  // Generation invalidation is scoped below after the affected desktop IDs are known.

  // Thumbnail batch generation only changes for a full invalidation.

  const ids = monitorDesktopFrameGenerationController.invalidate(desktopIds);
  if (!ids.size) monitorThumbBatchGeneration += 1;

  for (const key of [...monitorFrameCache.keys()]) {

    // cacheKey = generation:desktopId:profile:hostHwnd

    const desktopId = String(key).split(":")[1] || "";

    if (!ids.size || ids.has(desktopId)) monitorFrameCache.delete(key);

  }

}

async function moveMonitorWindowToDesktop(hwnd, sourceDesktopId, targetDesktopId) {

  if (!/^\d+$/.test(String(hwnd || "")) || !targetDesktopId) return false;

  const result = await monitorNative({ type: "moveWindowToDesktop", hwnd: String(hwnd), desktopId: targetDesktopId }).catch(() => null);

  if (!result?.ok) return false;

  const actualSourceDesktopId = sourceDesktopId || result.sourceDesktopId || "";

  invalidateMonitorDesktopFrames(actualSourceDesktopId, targetDesktopId);

  setTimeout(() => { refreshDesktopDropThumbnails(actualSourceDesktopId, targetDesktopId).catch(() => {}); }, 120);

  return true;

}

async function getDesktopBrowserWindowHandles(desktopId) {

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") throw new Error("Monitor host HWND를 확인할 수 없어 데스크톱 이동을 중단했습니다.");

  const snapshot = await monitorNative({ type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true });

  if (!snapshot?.ok) throw new Error(snapshot?.error || "데스크톱 창 목록을 읽지 못했습니다.");

  const hwnds = (Array.isArray(snapshot.windows) ? snapshot.windows : [])

    .filter((item) => item?.className === "Chrome_WidgetWin_1" && (item?.visible || item?.iconic))

    .map((item) => String(item?.hwnd || ""))

    .filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0" && hwnd !== hostHwnd);

  return [...new Set(hwnds)];

}

async function refreshDesktopDropThumbnails(sourceDesktopId, targetDesktopId) {

  invalidateMonitorDesktopFrames(sourceDesktopId, targetDesktopId);

  await new Promise((resolve) => setTimeout(resolve, 140));

  for (const desktopId of [sourceDesktopId, targetDesktopId]) {

    const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === desktopId);

    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

    if (visual) await refreshDesktopThumb(visual, desktopId);

  }

  await refreshObservedWindows();

}

async function createDesktopForDrop(sourceDesktopId, hwnds, copyMode = false) {

  if (monitorCreateDesktopDropBusy) return { ok: false, error: "DROP_BUSY" };

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!sourceDesktopId || !/^\d+$/.test(hostHwnd) || hostHwnd === "0") throw new Error("Monitor host HWND 또는 원본 데스크톱을 확인할 수 없습니다.");

  const exactHwnds = [...new Set((Array.isArray(hwnds) ? hwnds : []).map(String).filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0" && hwnd !== hostHwnd))];

  if (!exactHwnds.length) throw new Error("이동할 브라우저 창이 없습니다.");

  const authoritative = await monitorNative({ type: "getDesktopWindowHandles", desktopId: sourceDesktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true });

  if (!authoritative?.ok) throw new Error(authoritative?.error || "원본 데스크톱 창 목록을 확인하지 못했습니다.");

  const authoritativeHwnds = new Set((Array.isArray(authoritative.windows) ? authoritative.windows : []).map((item) => String(item?.hwnd || "")));

  const stale = exactHwnds.filter((hwnd) => !authoritativeHwnds.has(hwnd));

  if (stale.length) throw new Error(`원본 데스크톱에서 HWND를 재확인하지 못했습니다 · ${stale.join(",")}`);

  monitorCreateDesktopDropBusy = true;

  try {

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const result = await monitorNative({ type: "createVirtualDesktop" });

    if (!result?.ok) throw new Error(result?.error || "새 데스크톱 생성 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const createdIds = resultIds.filter((id) => !beforeIds.has(id));

    if (createdIds.length !== 1) throw new Error(`새 데스크톱 식별 실패 · created=${createdIds.length}`);

    const createdId = createdIds[0];

    const entries = exactHwnds.map((hwnd) => ({ hwnd, sourceDesktopId }));

    const success = copyMode

      ? await cloneMonitorWindowSet(entries, createdId, "create-copy", { createdId, sourceDesktopId })

      : await moveMonitorWindowSet(entries, createdId, "create-move", { createdId, sourceDesktopId });

    const moved = success ? [...exactHwnds] : [];

    const failed = success ? [] : [...exactHwnds];

    monitorDesktopState.observedDesktopId = createdId;

    renderVirtualDesktops(result);

    const createdIndex = monitorDesktopState.desktopIds.indexOf(createdId);

    if (createdIndex >= 0) selectVirtualDesktopPreview(createdIndex);

    await refreshDesktopDropThumbnails(sourceDesktopId, createdId);

    await refreshVirtualDesktops();

    settleNewDesktopWallpaper(createdId).catch(() => {});

    if (failed.length) {

      setMonitorStatus(`새 데스크톱 부분 이동 · 성공 ${moved.length} / 실패 ${failed.length}`, false);

      return { ok: false, partial: moved.length > 0, createdId, moved, failed };

    }

    return { ok: true, createdId, moved, failed: [] };

  } finally {

    monitorCreateDesktopDropBusy = false;

  }

}

function bindDesktopDropTarget(button) {

  if (!button || button.dataset.monitorDropBound) return;

  button.dataset.monitorDropBound = "1";

  const readPayload = (event) => {

    try { return JSON.parse(event.dataTransfer.getData("application/x-desktopwindow-hwnd") || "null"); } catch (_) { return null; }

  };

  button.addEventListener("dragover", (event) => {

    if (!event.dataTransfer.types.includes("application/x-desktopwindow-hwnd")) return;

    event.preventDefault(); event.dataTransfer.dropEffect = "move"; button.classList.add("monitor-desktop-drop-target");

  });

  button.addEventListener("dragleave", (event) => { if (!button.contains(event.relatedTarget)) button.classList.remove("monitor-desktop-drop-target"); });

  button.addEventListener("drop", async (event) => {

    event.preventDefault(); button.classList.remove("monitor-desktop-drop-target");

    const payload = readPayload(event);

    const targetDesktopId = button.dataset.desktopId || "";

    if (!payload?.hwnd || !targetDesktopId || payload.sourceDesktopId === targetDesktopId) return;

    button.classList.add("monitor-desktop-drop-pending");

    try { if (await moveMonitorWindowToDesktop(payload.hwnd, payload.sourceDesktopId, targetDesktopId)) button.classList.add("monitor-desktop-drop-success"); }

    finally { setTimeout(() => button.classList.remove("monitor-desktop-drop-pending", "monitor-desktop-drop-success"), 650); }

  });

}

function decorateMonitorThumbnailWindows(tile) {
  for (const image of tile.querySelectorAll(".monitor-desktop-thumb-window")) {
    const hwnd = String(image.dataset.hwnd || "");
    try {
      applyPersistentMonitorRoleClass(image,hwnd);
      image.classList.toggle("monitor-window-row-hovered",
        Boolean(monitorHoveredHwnd) && hwnd===monitorHoveredHwnd && !monitorSelectedHwnds.has(hwnd));
      syncMonitorStatusLayer(image,hwnd);
      syncMonitorPauseOverlay(image,hwnd);
      syncMonitorDesktopNumberBadge(image,hwnd);
      syncMonitorNonChatCountdown(image,hwnd);
    } catch (error) { console.warn("Monitor thumbnail V2 badge delayed",hwnd,error); }
  }
  syncMonitorThumbnailTabBadges(tile,"monitor-desktop-thumb-window");
}

async function refreshDesktopThumb(visual, desktopId) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED || !visual?.isConnected) return false;
  if (String(visual.dataset.desktopId || "").toLowerCase() !== String(desktopId || "").toLowerCase()) return false;
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer) return false;
  const result = await renderer.refresh(visual,desktopId);
  return result?.ok === true;
}

function monitorThumbnailBackgroundRuntimeDiagnostics() {
  const visuals = [...(monitorDesktopThumbs?.querySelectorAll?.(".monitor-desktop-thumb-visual") || [])];
  return visuals.map((visual) => ({
    desktop_id:String(visual.dataset.desktopId || ""),
    layer_mode:String(visual.dataset.monitorThumbnailLayerMode || globalThis.MonitorDesktopThumbnailV2?.mode || "unknown"),
    card_renderer:String(monitorDesktopThumbs?.dataset?.thumbnailCardRenderer || "unknown"),
    card_renderer_reason:String(monitorDesktopThumbs?.dataset?.thumbnailCardRendererReason || ""),
    card_renderer_error:String(monitorDesktopThumbs?.dataset?.thumbnailCardRendererError || "").slice(0,120),
    capture:String(visual.dataset.wallpaperCapture || "unobserved"),
    source:String(visual.dataset.wallpaperSource || "none"),
    accepted_kind:String(visual.dataset.wallpaperAcceptedKind || ""),
    accepted_at_ms:Number(visual.dataset.wallpaperAcceptedAt || 0),
    failure_reason:String(visual.dataset.wallpaperFailureReason || "").slice(0,120),
    thumbnail_ready:String(visual.dataset.monitorThumbnailReady || ""),
    composite_ready:String(visual.dataset.monitorThumbnailCompositeReady || ""),
    frame_ready:String(visual.dataset.monitorFrameReady || ""),
    actual_windows:Number(visual.dataset.monitorThumbnailWindows || 0),
    captured_windows:visual.querySelectorAll(".monitor-desktop-thumb-window[data-capture-state='captured']").length,
    failed_windows:visual.querySelectorAll(".monitor-desktop-thumb-window[data-capture-state='failed']").length,
    has_background_image:Boolean(visual.style.backgroundImage),
    has_background_color:Boolean(visual.style.backgroundColor)
  }));
}

function syncMonitorMinimizedNodeBadges(state = monitorLastAiState) {
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") === false) {
    for (const host of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-minimized-nodes")) host.remove();
    return;
  }
  const tokensByDesktop = monitorMinimizedNodeTokensByDesktop(state);
  const selectedKey = String(monitorNodePanelSelection.get() || "");
  const selectedNode = (Array.isArray(globalThis.monitorBctWindowNodesCache) ? globalThis.monitorBctWindowNodesCache : []).find((node) => monitorBctNodeSelectionKey(node) === selectedKey);
  const selectedToken = String(selectedNode?.nodeLabel || "").trim().replace(/^N/i, "") || "?";
  const selectedTabId = Number(selectedNode?.tabId) || 0;
  for (const button of monitorDesktopThumbs.children) {
    const visual = button.querySelector(".monitor-desktop-thumb-visual");
    if (!visual) continue;
    const label = button.querySelector(".monitor-desktop-thumb-label");
    if (!label) continue;
    visual.querySelector(".monitor-desktop-minimized-nodes")?.remove();
    let host = label.querySelector(".monitor-desktop-minimized-nodes");
    if (!host) { host = document.createElement("span"); host.className = "monitor-desktop-minimized-nodes"; label.append(host); }
    const tokens = tokensByDesktop.get(String(button.dataset.desktopId || "")) || [];
    const selectedIndex = tokens.findIndex((item) => selectedTabId ? Number(item.tabId) === selectedTabId : selectedToken !== "?" && item.token === selectedToken);
    const width = Number(label.getBoundingClientRect?.().width || 0);
    const budget = Math.max(9, Math.floor((width || 118) / 6.2));
    let first = 0, last = Math.max(0, tokens.length - 1);
    const lengthFor = (left, right) => (left > 0 ? 1 : 0) + (right < tokens.length - 1 ? 1 : 0) + tokens.slice(left, right + 1).map((item) => item.token).join("/").length;
    if (tokens.length && lengthFor(first, last) > budget) {
      const center = selectedIndex >= 0 ? selectedIndex : 0;
      first = center; last = center;
      let preferRight = true;
      while (true) {
        const rightFits = last < tokens.length - 1 && lengthFor(first, last + 1) <= budget;
        const leftFits = first > 0 && lengthFor(first - 1, last) <= budget;
        if (!leftFits && !rightFits) break;
        if ((preferRight && rightFits) || !leftFits) last += 1;
        else first -= 1;
        preferRight = !preferRight;
      }
    }
    const fullText = tokens.length ? tokens.map((item) => item.token).join("/") : "";
    const parts = [];
    if (tokens.length) {
      if (first > 0) { const more = document.createElement("span"); more.className = "monitor-desktop-minimized-more"; more.textContent = "…"; parts.push(more); }
      for (let index = first; index <= last; index += 1) {
        if (index > first) { const slash = document.createElement("span"); slash.className = "monitor-desktop-minimized-separator"; slash.textContent = "/"; parts.push(slash); }
        const badge = document.createElement("span");
        const selected = index === selectedIndex;
        badge.className = `monitor-desktop-minimized-node${selected ? " monitor-desktop-minimized-node-selected" : ""}`;
        badge.textContent = tokens[index].token; badge.title = `최소화 노드 ${tokens[index].token}`; parts.push(badge);
      }
      if (last < tokens.length - 1) { const more = document.createElement("span"); more.className = "monitor-desktop-minimized-more"; more.textContent = "…"; parts.push(more); }
    }
    host.className = `monitor-desktop-minimized-nodes${selectedIndex >= 0 ? " monitor-bct-minimized-selection" : ""}`;
    host.title = fullText ? `최소화 노드 ${fullText}` : "";
    host.replaceChildren(...parts);
    host.hidden = tokens.length === 0;
  }
}
function syncDesktopSwitcher() {
  const createdDesktopIds = [];

  const existing = new Map([...monitorDesktopThumbs.children].filter(button => !button.dataset.deletedPlaceholder).map(button => [button.dataset.desktopId, button]));

  for (let index = 0; index < monitorDesktopState.count; index += 1) {

    const desktopId = monitorDesktopState.desktopIds[index] || `index-${index}`;

    let button = existing.get(desktopId);

    if (!button) {

      button = document.createElement("button"); button.type = "button"; button.className = "monitor-desktop-thumb"; button.dataset.desktopId = desktopId;

      const visual = document.createElement("span"); visual.className = "monitor-desktop-thumb-visual"; visual.dataset.desktopId = desktopId;

      const label = document.createElement("span"); label.className = "monitor-desktop-thumb-label";

      const desktopBadge = document.createElement("span"); desktopBadge.className = "monitor-desktop-number-badge";

      const labelText = document.createElement("span"); labelText.className = "monitor-desktop-label-text";

      const minimizedNodes = document.createElement("span"); minimizedNodes.className = "monitor-desktop-minimized-nodes"; minimizedNodes.hidden = true;

      label.append(desktopBadge, labelText, minimizedNodes);
      monitorAttachDesktopManagementControl(label, desktopId);

      button.append(visual, label);

      button.addEventListener("pointerdown", beginMonitorDesktopPointerDrag);

      button.addEventListener("click", (event) => {

        if (button.dataset.monitorDropSuppressClick === "1") { event.preventDefault(); event.stopPropagation(); return; }

        selectVirtualDesktopPreview(Number(button.dataset.index || 0));

      });

      button.addEventListener("dblclick", async (event) => {

        event.preventDefault();

        const index = Number(button.dataset.index || 0);

        button.classList.add("monitor-desktop-switch-pending");

        try {

          const result = await monitorNative({ type: "switchVirtualDesktop", index });

          if (!result?.ok) throw new Error(result?.error || "데스크톱 전환 실패");

          renderVirtualDesktops(result);

          selectVirtualDesktopPreview(index);

        } catch (error) { setMonitorStatus(`데스크톱 전환 실패 · ${error?.message || error}`, false); }

        finally { setTimeout(() => button.classList.remove("monitor-desktop-switch-pending"), 350); }

      });

      bindDesktopDropTarget(button);

      monitorDesktopThumbs.append(button);
      createdDesktopIds.push(desktopId);

    }

    button.dataset.index = String(index); button.classList.toggle("selected", index === monitorDesktopState.selectedIndex); button.classList.toggle("current", index === monitorDesktopState.currentIndex);
    monitorAttachDesktopManagementControl(button.querySelector(".monitor-desktop-thumb-label"), desktopId);

    const displayIndex = monitorDeletedDesktopUndo && Date.now() < monitorDeletedDesktopUndoExpiresAt && index >= Number(monitorDeletedDesktopUndo.index) ? index + 1 : index;

    const labelText=button.querySelector(".monitor-desktop-label-text"); if(labelText)labelText.textContent=`데스크톱 ${displayIndex + 1}`; const desktopBadge=button.querySelector(".monitor-desktop-number-badge"); if(desktopBadge)desktopBadge.textContent=`D${displayIndex + 1}`;

    existing.delete(desktopId);

  }

  for (const stale of existing.values()) { const key=String(stale.dataset.hwnd||""); stale.parentElement?.querySelectorAll(".monitor-window-pause-overlay").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();}); stale.remove(); }

  for (const stalePlaceholder of [...monitorDesktopThumbs.querySelectorAll(".monitor-desktop-trash-placeholder")]) stalePlaceholder.remove();

  if (monitorDeletedDesktopUndo && Date.now() < monitorDeletedDesktopUndoExpiresAt) {

    const placeholder=document.createElement("div"); placeholder.className="monitor-desktop-thumb monitor-desktop-trash-placeholder"; placeholder.dataset.deletedPlaceholder="1";

    const undo=document.createElement("button"); undo.type="button"; undo.className="monitor-desktop-trash-placeholder-undo"; undo.title="삭제한 데스크톱 되돌리기"; undo.setAttribute("aria-label","삭제한 데스크톱 되돌리기");

    const icon=document.createElement("span"); icon.className="monitor-desktop-trash-placeholder-icon"; icon.textContent="↶";

    const countdown=document.createElement("span"); countdown.className="monitor-desktop-trash-placeholder-countdown"; countdown.textContent=`${Math.max(0,Math.ceil((monitorDeletedDesktopUndoExpiresAt-Date.now())/1000))}s`;

    undo.append(icon,countdown); undo.addEventListener("click", undoDeletedDesktopTrash); placeholder.append(undo);

    const at=Math.max(0,Math.min(Number(monitorDeletedDesktopUndo.index)||0,monitorDesktopThumbs.children.length));

    monitorDesktopThumbs.insertBefore(placeholder,monitorDesktopThumbs.children[at]||null);

  }

  // Background identity is the desktop GUID, not the Monitor popup's owning
  // desktop. Every new canonical card enters the same bottom-layer port used
  // by the lightweight renderer; V2 coalesces startup overlap per tile.
  if (createdDesktopIds.length) requestAnimationFrame(() => {
    const renderer = globalThis.MonitorDesktopThumbnailV2;
    for (const desktopId of createdDesktopIds) {
      const tile = [...monitorDesktopThumbs.children].find((item) => (
        String(item.dataset.desktopId || "") === String(desktopId)
      ));
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (visual?.isConnected) void renderer?.refreshBackground?.(visual, desktopId).catch(() => null);
    }
  });
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") !== false) syncMonitorMinimizedNodeBadges();
  requestAnimationFrame(syncMonitorDesktopScrollArrows);

}

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

globalThis.addEventListener("bwm-thumbnail-policy-changed", () => {
  const ids = [...(monitorDesktopState.desktopIds || [])].filter(Boolean);
  if (!ids.length || !monitorIsActiveDesktopRenderer()) return;
  invalidateMonitorDesktopFrames(...ids);
  void refreshSelectedThumb().catch(() => false);
  void refreshBackgroundThumbs(...ids).catch(() => []);
});
async function refreshSelectedThumb() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;

  const desktopId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "";

  if (!desktopId) return false;

  const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (!visual) return false;
  return await refreshDesktopThumb(visual, desktopId);

}

async function refreshInitialWindowThumbs() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refresh) {
    monitorInitialThumbStage = "window-renderer-unavailable";
    monitorInitialThumbError = "THUMBNAIL_WINDOW_RENDERER_UNAVAILABLE";
    return false;
  }
  const selectedId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "";
  const desktopIds = [
    selectedId,
    ...monitorDesktopState.desktopIds.filter((id) => id && id !== selectedId)
  ].filter(Boolean);
  if (!desktopIds.length) return false;

  monitorInitialThumbStage = "windows-requesting";
  monitorInitialThumbError = "";
  let pending = desktopIds;
  const retryDelays = [180, 500];
  for (let attempt = 0; pending.length; attempt += 1) {
    const failed = [];
    for (const desktopId of pending) {
      const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (!visual?.isConnected) { failed.push(desktopId); continue; }
      const result = await renderer.refresh(visual, desktopId).catch(() => null);
      if (result?.frameReady !== true) failed.push(desktopId);
    }
    pending = failed;
    if (!pending.length || attempt >= retryDelays.length) break;
    await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
  }
  monitorInitialThumbStage = pending.length ? "windows-partial" : "windows-ready";
  monitorInitialThumbError = pending.length ? `UNREADY_WINDOW_DESKTOPS:${pending.join(",")}` : "";
  return pending.length === 0;
}

async function refreshInitialSelectedThumb({ allowWindows = true } = {}) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  if (!monitorInitialThumbBatchDone) {
    monitorInitialThumbStage = "background-starting";
    monitorInitialThumbError = "";
    const refreshTask = refreshInitialBackgroundThumbs();
    const pendingReportTimer = setTimeout(() => {
      void monitorPublishSharedInstance("thumbnail-background-pending");
    }, 2500);
    const backgroundReady = await refreshTask.catch((error) => {
      monitorInitialThumbStage = "background-exception";
      monitorInitialThumbError = String(error?.message || error || "BACKGROUND_EXCEPTION").slice(0,160);
      return false;
    });
    clearTimeout(pendingReportTimer);
    monitorInitialThumbBatchDone = backgroundReady === true;
  }
  if (!monitorInitialThumbBatchDone) {
    await monitorPublishSharedInstance("thumbnail-background-failed").catch(() => null);
    return false;
  }
  if (!allowWindows) {
    monitorInitialThumbStage = "windows-awaiting-host";
    monitorInitialThumbError = "";
    await monitorPublishSharedInstance("thumbnail-windows-awaiting-host").catch(() => null);
    return true;
  }
  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();
  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") {
    monitorInitialThumbStage = "windows-awaiting-host";
    monitorInitialThumbError = "MONITOR_HOST_HWND_UNRESOLVED";
    await monitorPublishSharedInstance("thumbnail-windows-awaiting-host").catch(() => null);
    return true;
  }
  const windowsReady = monitorInitialWindowBatchDone || await refreshInitialWindowThumbs().catch((error) => {
    monitorInitialThumbStage = "windows-exception";
    monitorInitialThumbError = String(error?.message || error || "WINDOW_EXCEPTION").slice(0,160);
    return false;
  });
  monitorInitialWindowBatchDone = windowsReady === true;
  await monitorPublishSharedInstance(
    windowsReady ? "thumbnail-composite-ready" : "thumbnail-windows-partial"
  ).catch(() => null);
  scheduleInitialSemanticThumbSync();
  void checkMonitorDeploymentUpdate();
  return true;
}

async function refreshBackgroundThumbs(...desktopIds) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return [];
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refreshBackground) return desktopIds.filter(Boolean);
  const selectedDesktopId = String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "");
  const ids = new Set(desktopIds.map((id) => String(id || "")).filter(Boolean));
  if (selectedDesktopId) ids.delete(selectedDesktopId);
  const failed = [];
  for (const desktopId of ids) {
    const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
    if (!visual?.isConnected) continue;
    const result = await renderer.refreshBackground(visual, desktopId).catch(() => null);
    if (result?.wallpaperReady !== true) failed.push(desktopId);
  }
  return failed;
}

function scheduleInitialSemanticThumbSync(delay = 180) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return;
  if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight) return;
  if (monitorInitialSemanticThumbSyncTimer) clearTimeout(monitorInitialSemanticThumbSyncTimer);
  monitorInitialSemanticThumbSyncTimer = setTimeout(async () => {
    monitorInitialSemanticThumbSyncTimer = 0;
    if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight || !monitorInitialThumbBatchDone) return;
    const state = monitorLastAiState;
    const observer = state?.node_state?.observer;
    const semanticReady = state?.ok === true && (
      (String(observer?.source || "") === "ACT_NATIVE_OBSERVER" && Array.isArray(observer?.windows)) ||
      (Array.isArray(state?.endpoints) && state.endpoints.length > 0) ||
      (Array.isArray(state?.node_state?.nodes) && state.node_state.nodes.length > 0)
    );
    if (!semanticReady) return;
    monitorInitialSemanticThumbSyncInflight = true;
    try {
      syncMonitorAllDesktopThumbnailNodeBadges();
      monitorInitialSemanticThumbSyncDone = true;
    } finally {
      monitorInitialSemanticThumbSyncInflight = false;
    }
  }, Math.max(0, Number(delay) || 0));
}

let monitorThumbnailLayoutSignature = "";

window.addEventListener("resize", () => scheduleMonitorExternalWindowDropTargets());

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

async function monitorThumbnailLayoutWatch() {

  const desktopIds = monitorDesktopState.desktopIds.filter(Boolean);

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!desktopIds.length || !/^\d+$/.test(hostHwnd) || hostHwnd === "0") return;

  const parts = [];

  for (const desktopId of desktopIds) {

    const snap = await monitorNative({ type:"getDesktopWindowHandles", desktopId, hostWindowHwnd:hostHwnd, includeMonitorWindows:true }).catch(() => null);

    if (!snap?.ok) continue;

    applyMonitorLiveWindowGeometry(desktopId, snap);

    const rows = (Array.isArray(snap.windows) ? snap.windows : [])

      .filter((item) => String(item?.hwnd || "") !== hostHwnd)

      .map((item) => [String(item?.hwnd||""),Number(item?.left||0),Number(item?.top||0),Number(item?.width||0),Number(item?.height||0),Boolean(item?.iconic)].join(":"))

      .sort();

    parts.push(`${desktopId}=${rows.join(",")}`);

  }

  const signature = parts.join("|");

  if (!signature) return;

  if (!monitorThumbnailLayoutSignature) {

    monitorThumbnailLayoutSignature = signature;

    invalidateMonitorDesktopFrames(...desktopIds);

    void refreshSelectedThumb();
    void refreshBackgroundThumbs(...desktopIds);

    void refreshAiMonitor().catch(() => {});

    return;

  }

  if (signature !== monitorThumbnailLayoutSignature) {

    monitorThumbnailLayoutSignature = signature;

    // Recovery-only reconciliation. Live move/snap/desktop-transfer rendering is driven

    // by Native window events; never pause or schedule delayed redraws from this watcher.

    invalidateMonitorDesktopFrames(...desktopIds);

    void refreshSelectedThumb();
    void refreshBackgroundThumbs(...desktopIds);

    void refreshAiMonitor().catch(() => {});

  }

}

let monitorWindowsStateRefreshBusy = false;

async function refreshWindowsCurrentState() {
  if (monitorWindowsStateRefreshBusy) return;
  monitorWindowsStateRefreshBusy = true;
  try {
    await refreshVirtualDesktops();
  } finally {
    monitorWindowsStateRefreshBusy = false;
  }
}

function renderLightweightDesktopCards(reason = "EXPLICIT") {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) { monitorDesktopThumbs.replaceChildren(); return true; }

  const ids = Array.isArray(monitorDesktopState.desktopIds) ? monitorDesktopState.desktopIds.filter(Boolean) : [];

  if (!ids.length) return false;

  monitorDesktopThumbs.replaceChildren();
  monitorDesktopThumbs.dataset.thumbnailCardRenderer = "lightweight";
  monitorDesktopThumbs.dataset.thumbnailCardRendererReason = String(reason || "EXPLICIT");
  const createdVisuals = [];

  ids.forEach((desktopId, index) => {

    const button = document.createElement("button");

    button.type = "button"; button.className = "monitor-desktop-thumb monitor-desktop-thumb-lite";

    button.dataset.desktopId = desktopId; button.dataset.index = String(index);

    button.classList.toggle("selected", index === monitorDesktopState.selectedIndex);

    button.classList.toggle("current", index === monitorDesktopState.currentIndex);

    const visual = document.createElement("span");

    visual.className = "monitor-desktop-thumb-visual"; visual.dataset.desktopId = desktopId;

    const label = document.createElement("span"); label.className = "monitor-desktop-thumb-label";

    const badge = document.createElement("span"); badge.className = "monitor-desktop-number-badge"; badge.textContent = `D${index + 1}`;

    const text = document.createElement("span"); text.className = "monitor-desktop-label-text"; text.textContent = `???? ${index + 1}`;

    const minimizedNodes = document.createElement("span");
    minimizedNodes.className = "monitor-desktop-minimized-nodes";
    minimizedNodes.hidden = true;
    label.append(badge, text, minimizedNodes); button.append(visual, label); monitorAttachDesktopManagementControl(label, desktopId);

    button.addEventListener("click", () => selectVirtualDesktopPreview(index));

    button.addEventListener("dblclick", async (event) => {

      event.preventDefault();

      const result = await monitorNative({ type:"switchVirtualDesktop", index }).catch(() => null);

      if (result?.ok) { renderVirtualDesktops(result); selectVirtualDesktopPreview(index); }

    });

    monitorDesktopThumbs.append(button);
    createdVisuals.push({visual, desktopId});

  });

  requestAnimationFrame(() => {
    const renderer = globalThis.MonitorDesktopThumbnailV2;
    for (const entry of createdVisuals) {
      if (entry.visual.isConnected) void renderer?.refreshBackground?.(entry.visual, entry.desktopId).catch(() => null);
    }
  });
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") !== false) syncMonitorMinimizedNodeBadges();
  return true;

}

function renderVirtualDesktops(state) {

  const reportedHostTitle = String(state?.hostWindowTitle || "").trim();

  if (reportedHostTitle && reportedHostTitle !== monitorLocalHostWindowTitle) monitorLocalHostWindowTitle = reportedHostTitle;

  const desktopIds = Array.isArray(state?.desktopIds) ? state.desktopIds : [];

  const count = Math.max(1, Number(state?.count) || desktopIds.length || 1);

  const currentIndex = Math.min(Math.max(0, Number(state?.currentIndex) || 0), Math.max(0, count - 1));

  const currentDesktopId = desktopIds[currentIndex] || null;

  const reportedHostId = typeof state?.hostDesktopId === "string" && desktopIds.includes(state.hostDesktopId) ? state.hostDesktopId : null;

  const hostAmbiguous = state?.hostWindowAmbiguous === true;

  const previousCurrentDesktopId = monitorDesktopState.currentDesktopId;
  const previousHostId = monitorDesktopState.hostDesktopId;

  const hostDesktopId = hostAmbiguous ? null : (reportedHostId || (previousHostId && desktopIds.includes(previousHostId) ? previousHostId : null));

  const previousHostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  const reportedHostHwnd = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0" ? String(state.hostWindowHwnd) : null;

  const hostWindowHwnd = hostAmbiguous ? null : (reportedHostHwnd || monitorDesktopState.hostWindowHwnd || null);

  const hostWindowChanged = hostAmbiguous ? Boolean(previousHostHwnd) : Boolean(reportedHostHwnd && reportedHostHwnd !== previousHostHwnd);

  const previousObservedId = monitorDesktopState.observedDesktopId;

  const sharedObservedId = monitorSharedSelectionReady && monitorSharedSelectedDesktopId && desktopIds.includes(monitorSharedSelectedDesktopId) ? monitorSharedSelectedDesktopId : null;

  const observedDesktopId = sharedObservedId || (previousObservedId && desktopIds.includes(previousObservedId) ? previousObservedId : (reportedHostId || currentDesktopId || desktopIds[0] || null));

  const selectedIndex = Math.max(0, desktopIds.indexOf(observedDesktopId));

  monitorDesktopState = { count, currentIndex, selectedIndex, currentDesktopId, hostDesktopId, hostWindowHwnd, observedDesktopId, desktopIds };
  // BCT node state can arrive before Native desktop topology. Once the
  // desktop IDs exist, perform only a bounded exact identity reconciliation
  // so the semantic thumbnail overlay has a verified HWND to project onto.
  scheduleMonitorBctProjectionConvergence("desktop-topology");
  if (currentDesktopId && currentDesktopId !== previousCurrentDesktopId) void ensureMonitorCurrentWallpaperSnapshot(currentDesktopId);
  if (hostDesktopId && /^\d+$/.test(String(hostWindowHwnd || "")) && String(hostWindowHwnd) !== "0") {
    void chrome.runtime.sendMessage({ type:"monitor-update-popup-runtime", desktopId:hostDesktopId, hwnd:String(hostWindowHwnd) }).catch(() => null);
    void ensureMonitorOwnFrozenSnapshot();
  }

  document.body.dataset.monitorActiveDesktopId = currentDesktopId || "";

  document.body.dataset.monitorHostDesktopId = hostDesktopId || "";

  document.body.dataset.monitorObservedDesktopId = observedDesktopId || "";

  document.body.classList.toggle("monitor-preview-remote", selectedIndex !== currentIndex);

  document.body.dataset.monitorPreviewDesktop = String(selectedIndex + 1);

  const selectedId = observedDesktopId;
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) {
    monitorDesktopThumbs.replaceChildren();
    monitorPreviewBackground.clear(selectedId || "");
    monitorWindowLayer.replaceChildren();
    monitorFrameCache.clear();
    scheduleMonitorExternalWindowDropTargets();
    if (hostWindowChanged) void monitorPublishSharedInstance("host-hwnd-changed");
    return;
  }

  try {

    syncDesktopSwitcher();
    monitorDesktopThumbs.dataset.thumbnailCardRenderer = "canonical";
    monitorDesktopThumbs.dataset.thumbnailCardRendererReason = "";
    monitorDesktopThumbs.dataset.thumbnailCardRendererError = "";

  } catch (error) {

    console.warn("DesktopWindow Monitor desktop card renderer failed; using lightweight fallback", error);

    monitorDesktopThumbs.dataset.thumbnailCardRendererError = String(error?.message || error || "RENDER_EXCEPTION");
    renderLightweightDesktopCards("RENDER_EXCEPTION");

  }

  if (desktopIds.length && monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb[data-desktop-id]").length < desktopIds.length) {

    monitorDesktopThumbs.dataset.thumbnailCardRendererError = "";
    renderLightweightDesktopCards("CARD_COUNT_MISMATCH");

  }

  if (hostWindowChanged) {

    void monitorPublishSharedInstance("host-hwnd-changed");

    monitorFrameCache.clear();

    for (const visual of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb-visual")) delete visual.dataset.monitorFrameReady;

    if (monitorInitialWindowBatchDone) {

      setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); }, 0);

    }

  }

  if (selectedId) {

    const wallpaperChangedDesktop = monitorPreviewBackground.desktopId !== String(selectedId).toLowerCase();

    applyObservedWallpaper(selectedId, wallpaperChangedDesktop);

  }

  if (selectedId && monitorWindowLayer.dataset.desktopId !== selectedId) {

    refreshObservedWindows();

  }

  if (monitorStructureOpen && document.getElementById("monitorStructureManagers")) renderMonitorStructure();

  scheduleMonitorExternalWindowDropTargets();

}

let monitorHostResolveRetryCount = 0;

let monitorHostResolveRetryTimer = 0;

async function refreshVirtualDesktops() {

  try {

    if (!monitorInitialThumbBatchDone) monitorInitialThumbStage = "topology-requesting";
    const currentWindow = await chrome.windows.getCurrent();

    const topology = await monitorNative({

      type: "getVirtualDesktops", hostTitle: document.title,

      left: currentWindow?.left, top: currentWindow?.top,

      width: currentWindow?.width, height: currentWindow?.height

    });

    if (topology?.ok) {

      if (!monitorInitialThumbBatchDone) monitorInitialThumbStage = "cards-rendering";
      try {
        renderVirtualDesktops(topology);
      } catch (error) {
        // Card extras must never prevent the independent exact-GUID
        // background layer from reaching its Native source.
        monitorInitialThumbStage = "cards-partial";
        monitorInitialThumbError = String(error?.message || error || "CARD_RENDER_EXCEPTION").slice(0,160);
      }

      if (!monitorInitialThumbBatchDone) await refreshInitialSelectedThumb({ allowWindows: false });

      // Window ownership is a separate, later layer. It must not delay card
      // creation or exact-GUID wallpaper acceptance.
      const state = await globalThis.MonitorHostWindowIdentity.resolve(topology, {
        title: document.title,
        bounds: {left:currentWindow?.left,top:currentWindow?.top,
          width:currentWindow?.width,height:currentWindow?.height},
        requestNative: query => monitorNative(query),
        isOwnTitle: monitorIsOwnWindowTitle,
      });
      if (state !== topology) {
        try { renderVirtualDesktops(state); }
        catch (error) {
          monitorInitialThumbError = String(error?.message || error || "HOST_RENDER_EXCEPTION").slice(0,160);
        }
      }

      const resolved = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0";

      if (resolved) {

        if (!monitorInitialWindowBatchDone) await refreshInitialSelectedThumb({ allowWindows: true });

        monitorHostResolveRetryCount = 0;

        if (monitorHostResolveRetryTimer) clearTimeout(monitorHostResolveRetryTimer);

        monitorHostResolveRetryTimer = 0;

      } else if (monitorHostResolveRetryCount < 8 && !monitorHostResolveRetryTimer) {

        monitorHostResolveRetryCount += 1;

        monitorHostResolveRetryTimer = setTimeout(() => {

          monitorHostResolveRetryTimer = 0;

          refreshVirtualDesktops();

        }, Math.min(1200, 250 + monitorHostResolveRetryCount * 150));

      }

    } else if (!monitorHostResolveRetryTimer) {

      monitorInitialThumbStage = "topology-failed";
      monitorInitialThumbError = String(topology?.error || "GET_VIRTUAL_DESKTOPS_FAILED").slice(0,160);
      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  } catch (error) {

    monitorInitialThumbStage = "topology-exception";
    monitorInitialThumbError = String(error?.message || error || "TOPOLOGY_EXCEPTION").slice(0,160);
    if (!monitorHostResolveRetryTimer) {

      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  }

}

function flashDesktopTransition() {

  monitorTransitionFlash.classList.remove("active");

  const button=[...monitorDesktopThumbs.children].find((node)=>Number(node.dataset.index)===monitorDesktopState.selectedIndex);

  if(!button)return;

  button.classList.remove("monitor-desktop-card-flash");

  void button.offsetWidth;

  button.classList.add("monitor-desktop-card-flash");

  setTimeout(()=>button.classList.remove("monitor-desktop-card-flash"),420);

}

function primeSelectedDesktopPreview(desktopId) {
  const id = String(desktopId || "");
  if (!id) return;
  const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === id);
  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
  monitorWindowLayer.replaceChildren();
  monitorWindowLayer.dataset.desktopId = id;
  monitorPreviewBackground.begin(id);
  if (!visual) return;
  syncMonitorPreviewBackground(visual,id);
  for (const source of visual.querySelectorAll(".monitor-desktop-thumb-window")) {
    const img = source.cloneNode(false);
    img.className = "monitor-window-preview";
    img.dataset.hwnd = String(source.dataset.hwnd || "");
    monitorWindowLayer.append(img);
  }
}

function selectVirtualDesktopPreview(index) {

  const bounded = Math.min(Math.max(0, index), monitorDesktopState.count - 1);

  const changed = bounded !== monitorDesktopState.selectedIndex;

  monitorDesktopState.selectedIndex = bounded;

  const desktopId = monitorDesktopState.desktopIds[bounded] || null;

  monitorSharedSelectedDesktopId = desktopId || "";

  monitorDesktopState.observedDesktopId = desktopId;

  publishMonitorSharedSelection();

  document.body.dataset.monitorObservedDesktopId = desktopId || "";

  if (changed) flashDesktopTransition();

  document.body.classList.toggle("monitor-preview-remote", bounded !== monitorDesktopState.currentIndex);

  document.body.dataset.monitorPreviewDesktop = String(bounded + 1);

  if (changed && desktopId) {
    primeSelectedDesktopPreview(desktopId);
    void applyObservedWallpaper(desktopId, true);
  }

  window.dispatchEvent(new CustomEvent("desktopwindow-monitor-preview", {

    detail: { index: bounded, desktopId, currentIndex: monitorDesktopState.currentIndex }

  }));

  renderVirtualDesktops({

    count: monitorDesktopState.count,

    currentIndex: monitorDesktopState.currentIndex,

    desktopIds: monitorDesktopState.desktopIds

  });

  // Selecting a preview does not change Windows topology.  Do not invalidate
  // other desktop captures here: rapid D1/D2 navigation used to cancel valid
  // in-flight card frames and temporarily blank their accepted pixels.
  void refreshObservedWindows();
  void refreshSelectedThumb();

}

function expireDesktopUndoSession(now = Date.now()) { return monitorRecoveryUndoSession.expire(now); }



function pushDesktopUndoSnapshot(snapshot, now = Date.now()) { monitorRecoveryUndoSession.push(snapshot, now); }

function peekDesktopUndoSnapshot(now = Date.now()) { return monitorRecoveryUndoSession.peek(now); }

function commitDesktopUndoRestore(now = Date.now()) { monitorRecoveryUndoSession.pop(now); }

function updateDesktopUndoUi() {

  const now = Date.now();

  expireDesktopUndoSession(now);

  clearTimeout(monitorUndoTimer);

  const latest = monitorRecoveryUndoSession.peek(now);

  monitorDesktopUndo.hidden = !latest;

  if (!latest) return;

  const seconds = Math.max(0, Math.ceil(monitorRecoveryUndoSession.remainingMs(now) / 1000));

  monitorDesktopUndoCountdown.textContent = `${seconds}s`;

  const label = latest.kind === "window-move" ? "window move" : latest.kind === "window-copy" ? "window copy" : latest.kind === "create-move" ? "new desktop move" : latest.kind === "create-copy" ? "new desktop copy" : `desktop ${Number(latest.index) + 1}`;

  monitorDesktopUndoButton.title = `Undo ${label} - ${seconds}s left`;

  monitorUndoTimer = setTimeout(updateDesktopUndoUi, Math.min(250, Math.max(50, monitorRecoveryUndoSession.remainingMs(now))));

}

function showDesktopUndo(snapshot) {

  pushDesktopUndoSnapshot(snapshot);

  updateDesktopUndoUi();

}

function updateDeletedDesktopTrashUi() {

  clearTimeout(monitorDeletedDesktopUndoTimer);

  if (!monitorDeletedDesktopUndo) return;

  const now=Date.now();

  if (now >= monitorDeletedDesktopUndoExpiresAt) { monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; syncDesktopSwitcher(); return; }

  syncDesktopSwitcher();

  monitorDeletedDesktopUndoTimer=setTimeout(updateDeletedDesktopTrashUi,250);

}

function showDeletedDesktopTrashUndo(snapshot) {

  monitorDeletedDesktopUndo={...snapshot}; monitorDeletedDesktopUndoExpiresAt=Date.now()+MONITOR_DESKTOP_TRASH_UNDO_MS; updateDeletedDesktopTrashUi();

}

async function undoDeletedDesktopTrash() {

  const snapshot=monitorDeletedDesktopUndo; if(!snapshot||Date.now()>=monitorDeletedDesktopUndoExpiresAt)return;

  const button=monitorDesktopThumbs.querySelector(".monitor-desktop-trash-placeholder-undo"); if(button)button.disabled=true;

  try {

    const beforeIds=new Set(monitorDesktopState.desktopIds);

    const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:snapshot.hwnds});

    if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");

    const resultIds=Array.isArray(result.desktopIds)?result.desktopIds:[];

    const restoredId=resultIds.find((id)=>!beforeIds.has(id))||resultIds[resultIds.length-1]||null;

    monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; clearTimeout(monitorDeletedDesktopUndoTimer);

    restoreMonitorDesktopNodeSnapshots(snapshot.nodes);

    if(snapshot.desktopId) deleteMonitorTrashedDesktop(snapshot.desktopId);

    monitorDesktopState.observedDesktopId=restoredId; renderVirtualDesktops(result); if(restoredId)settleNewDesktopWallpaper(restoredId).catch(()=>{});

  } catch(error) { setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false); if(button)button.disabled=false; }

}

async function removeVirtualDesktopPreview(index, options={}) {

  if (monitorDesktopState.count <= 1 || index < 0 || index >= monitorDesktopState.count) return;

  const desktopId = monitorDesktopState.desktopIds[index] || null;

  const fallbackIndex = index < monitorDesktopState.count - 1 ? index + 1 : index - 1;

  try {

    const nodeSnapshots = monitorDesktopNodeSnapshots(desktopId,index);

    const snapshot = desktopId ? await monitorNative({ type: "getDesktopWindowHandles", desktopId }) : null;

    const wallpaperDataUri = desktopId ? await getObservedWallpaper(desktopId, true) : "";

    const thumbnail = desktopId ? await monitorFreezeDesktopThumbnail(desktopId, wallpaperDataUri).catch(() => "") : "";

    const hwnds = Array.isArray(snapshot?.hwnds) ? snapshot.hwnds.map(String).filter(Boolean) : [];

    const result = await monitorNative({ type: "removeVirtualDesktop", index, fallbackIndex });

    if (!result?.ok) throw new Error(result?.error || "데스크톱 삭제 실패");

    monitorFrameCache.clear(); monitorWallpaperCache.delete(desktopId); monitorWallpaperActuals.delete(desktopId);

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    if (monitorDesktopState.observedDesktopId === desktopId) {

      monitorDesktopState.observedDesktopId = resultIds[Math.min(index, Math.max(0, resultIds.length - 1))] || resultIds[0] || null;

    }

    renderVirtualDesktops(result);

    const undoSnapshot={kind:"desktop-delete",desktopId,index,hwnds,nodes:nodeSnapshots,wallpaperDataUri,thumbnail};

    storeMonitorTrashedDesktop({desktopId,index,desktop_number:index+1,thumbnail,hwnds,nodes:nodeSnapshots});

    showDeletedDesktopTrashUndo(undoSnapshot);

    flashDesktopTransition();

  } catch (error) { setMonitorStatus(`데스크톱 삭제 실패 · ${error?.message || error}`, false); }

}

async function removeCreatedDesktopIfSafe(snapshot) {

  const createdId = String(snapshot?.createdId || ""); if (!createdId) return;

  await new Promise((resolve) => setTimeout(resolve, 260));

  const check = await monitorNative({ type: "getDesktopWindowHandles", desktopId: createdId }).catch(() => null);

  if (!check?.ok || (Array.isArray(check.hwnds) && check.hwnds.length)) return;

  await refreshVirtualDesktops();

  const index = monitorDesktopState.desktopIds.indexOf(createdId); if (index < 0 || monitorDesktopState.count <= 1) return;

  const sourceIndex = Math.max(0, monitorDesktopState.desktopIds.indexOf(String(snapshot.sourceDesktopId || "")));

  const fallbackIndex = sourceIndex === index ? (index > 0 ? index - 1 : Math.min(1, monitorDesktopState.count - 1)) : sourceIndex;

  await monitorNative({ type: "removeVirtualDesktop", index, fallbackIndex }).catch(() => null);

  await refreshVirtualDesktops();

}

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

async function settleNewDesktopWallpaper(createdId) {

  if (!createdId) return false;

  const renderer=globalThis.MonitorDesktopThumbnailV2;
  const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === createdId);
  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
  const started = Date.now(); let ready = false;

  while (Date.now() - started < 5000) {

    if (visual) {
      const result=await renderer?.refreshBackground?.(visual,createdId,{forceWallpaper:true}).catch(()=>null);
      if(result?.wallpaperReady===true){ready=true;break;}
    }

    await new Promise((resolve) => setTimeout(resolve, 160));

  }

  if (!ready) return false;

  monitorWallpaperCache.delete(createdId);

  if (visual) {
    syncMonitorPreviewBackground(visual,createdId);
  }
  return Boolean(renderer?.acceptedBackground?.(visual,createdId));
}

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

function monitorConversationStateSignature(state) { return globalThis.MonitorDomainAPIs["conversations"]["monitorConversationStateSignature"].apply(this, arguments); }

async function refreshMonitorConversationStateFast(forceBadgeSync = false) {
  if (forceBadgeSync) monitorConversationStateForceBadgeSyncPending = true;
  if (monitorConversationStateRefreshBusy || monitorRefreshBusy) return;
  monitorConversationStateRefreshBusy = true;
  try {
    const response = await actFetch(ORCHESTRATOR_MONITOR_STATE_URL, { cache: "no-store" }).catch(() => null);
    if (!response?.ok) return;
    const state = await response.json().catch(() => null);
    if (!state?.ok) return;
    const signature = monitorConversationStateSignature(state);
    const previous = monitorConversationStateSignatureCache || monitorConversationStateSignature(monitorLastAiState);
    const forceSync=monitorConversationStateForceBadgeSyncPending;
    monitorConversationStateForceBadgeSyncPending=false;
    monitorConversationStateSignatureCache = signature;
    const changed=signature!==previous;
    if (!changed && !forceSync) return;
    state.llm_nodes = Array.isArray(monitorLastAiState?.llm_nodes) ? monitorLastAiState.llm_nodes : monitorCachedLlmNodes;
    monitorLastAiState = state;
    pruneMonitorEphemeralGenerationState(state);
    chrome.storage.local.set({ [MONITOR_AI_STATE_CACHE_KEY]: { at: Date.now(), state } }).catch(() => {});
    if(changed) renderWorkers(state);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleInitialSemanticThumbSync();
  } finally {
    monitorConversationStateRefreshBusy = false;
    if (monitorConversationStateForceBadgeSyncPending && !monitorRefreshBusy) setTimeout(()=>{ void refreshMonitorConversationStateFast(); },0);
  }
}

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

function monitorStructureFinishHtmlDragGhost(){
  destroyMonitorNodeDragGhost(monitorStructureHtmlDragGhost);
  monitorStructureHtmlDragGhost=null;
}

function monitorStructureTrackHtmlDragGhost(event){
  if(!monitorStructureHtmlDragGhost)return;
  moveMonitorNodeDragGhost(monitorStructureHtmlDragGhost,event.clientX,event.clientY);
}

function monitorStructureUseNodeDragGhost(event){
  const source=event?.target?.closest?.(".monitor-org-node-card,.monitor-org-bundle,.monitor-worker-row")||event?.currentTarget;
  if(!source)return;
  monitorStructureFinishHtmlDragGhost();
  const ghost=createMonitorNodeDragGhost(source,event);
  if(!ghost)return;
  ghost.classList.add("monitor-org-drag-ghost");
  ghost.style.transform="translate3d(-10000px,-10000px,0)";
  monitorStructureHtmlDragGhost=ghost;
  try{const nativeDragImage=document.createElement("canvas");nativeDragImage.width=1;nativeDragImage.height=1;event?.dataTransfer?.setDragImage(nativeDragImage,0,0);}catch(_){}
  requestAnimationFrame(()=>{if(monitorStructureHtmlDragGhost===ghost)moveMonitorNodeDragGhost(ghost,event.clientX,event.clientY);});
}

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

function monitorStructureNodeFromWorker(worker,state){

  const key=String(worker?.conversation_key||"").trim(); if(!key)return null;

  const endpoints=monitorOpenEndpointsForConversation(state,key); if(endpoints.length!==1)return null;

  const ep=endpoints[0]; const location=monitorCanonicalPhysicalLocation(worker,state);

  const hwnd=String(location?.hwnd||""); const remembered=monitorWindowDesktopLocations.get(hwnd);

  const desktopId=String(location?.location?.desktopId||location?.desktopId||remembered?.desktopId||"");

  const stableKey=monitorStableBrowserNodeKey(worker);

  const stable=(stableKey&&monitorStableNodeSlotRecord(worker,stableKey))||monitorStableNodeSlot(worker,state);

  const stableLabel=stable&&Number(stable.desktop)>0&&Number(stable.slot)>0?`D${stable.desktop}-${stable.slot}`:"";

  const orderMatch=stableLabel.match(/-(\d+)\b/);

  return {conversation_key:key,profile_id:String(ep?.profile_id||"").toUpperCase(),role:String(worker?.role||"").toUpperCase(),exemption:worker?.exemption||null,transport_instance_id:String(ep?.transport_instance_id||""),session_id:String(ep?.session_id||""),tab_id:ep?.tab_id??null,hwnd,desktop_id:desktopId,node_order:orderMatch?Number(orderMatch[1]):999,label:stableLabel||String(location?.label||"")||key.slice(0,8),title:monitorWorkerMeaningfulTitle(worker,state,ep)||""};

}

function monitorStructureNodeIdentityTokens(node) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureNodeIdentityTokens"].apply(this, arguments); }

function monitorStructureAvailableNodes(){

  const state=monitorLastAiState||{}; const seen=new Set(), seenPhysicalNodes=new Set(), out=[];

  for(const worker of monitorWorkersForState(state)){
    const profile=String(worker?.profile_id||"").toUpperCase();
    if(!["GOOGLE","NAVER"].includes(profile))continue;
    const node=monitorStructureNodeFromWorker(worker,state);
    if(!node)continue;
    const identityTokens=monitorStructureNodeIdentityTokens(node);
    if(seen.has(node.conversation_key)||identityTokens.some(token=>seenPhysicalNodes.has(token)))continue;
    seen.add(node.conversation_key);
    identityTokens.forEach(token=>seenPhysicalNodes.add(token));
    out.push(node);
  }
  return out;

}
function monitorStructureEffectiveDesktopId(node){const key=String(node?.conversation_key||"");return String(monitorStructureDeskMembership[key]||node?.desktop_id||"");}

function monitorStructureMoveNodeToDesk(nodeKey,desktopId){nodeKey=String(nodeKey||"");desktopId=String(desktopId||"");if(!nodeKey||!desktopId)return false;const bundleKind=nodeKey.startsWith("LLM:")?nodeKey.slice(4):"";if(monitorStructureBundleOrder().includes(bundleKind))return monitorStructureMoveBundleToDesk(bundleKind,desktopId);const historyBefore=monitorStructureHistorySnapshot();if(String(monitorStructureSocketDraft.orchestrator?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.orchestrator=null;if(String(monitorStructureSocketDraft.aux1?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.aux1=null;if(String(monitorStructureSocketDraft.aux2?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.aux2=null;monitorStructureDeskMembership[nodeKey]=desktopId;for(const [desk,node] of Object.entries(monitorStructureSocketDraft.managers||{})){if(String(node?.conversation_key||"")===nodeKey)delete monitorStructureSocketDraft.managers[desk];}monitorStructureDirty=true;monitorStructureHistoryCommit(historyBefore);renderMonitorStructure();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="이동 예정 · 실행 시 실제 Desk 이동 후 노드 번호 확정";return true;}

function monitorStructureMoveBundleToDesk(kind,desktopId,asManager=false){
  kind=String(kind||"");desktopId=String(desktopId||"");
  if(!kind||!desktopId)return false;
  const historyBefore=monitorStructureHistorySnapshot();
  if(asManager){
    for(const [otherKind,otherDesk] of Object.entries(monitorStructureManagerBundleDesk))if(String(otherDesk)===desktopId)delete monitorStructureManagerBundleDesk[otherKind];
    monitorStructureManagerBundleDesk[kind]=desktopId;
    delete monitorStructureBundleDesk[kind];
  }else{
    monitorStructureBundleDesk[kind]=desktopId;
    delete monitorStructureManagerBundleDesk[kind];
  }
  monitorStructureDirty=true;
  monitorStructureHistoryCommit(historyBefore);
  renderMonitorStructure();
  const status=document.getElementById("monitorStructureStatus");
  if(status)status.textContent="번들 이동 예정 · 실행을 눌러야 확정됨";
  return true;
}

function monitorStructureBundleOrder() { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureBundleOrder"].apply(this, arguments); }

function monitorStructureBundleKinds(){
  const projectedResources = monitorLastAiState && typeof monitorWorkersProjectionForState === "function"
    ? monitorWorkersProjectionForState(monitorLastAiState).filter((node)=>node?.__kind==="LLM_NODE")
    : [];
  const merged=[
    ...(Array.isArray(monitorStructureAiNodes)?monitorStructureAiNodes:[]),
    ...(Array.isArray(monitorLastAiState?.llm_nodes)?monitorLastAiState.llm_nodes:[]),
    ...projectedResources,
  ];
  const by={local:[],external:[],"codex-google":[]},seen=new Set();
  for(const n of merged){
    const id=String(n?.node_id||n?.resource_id||n?.conversation_key||"");
    if(!id||seen.has(id))continue;
    seen.add(id);
    const raw=String(n?.kind||n?.provider_kind||n?.provider||"").toLowerCase();
    const isCodex=raw==="codex"||String(n?.provider||"").toLowerCase()==="codex";
    const kind=isCodex?"codex-google":(raw==="local"?"local":"external");
    by[kind].push(n);
  }
  return by;
}

function monitorStructureEnsureBundleDefaults(desktopIds){

  const ids=(Array.isArray(desktopIds)?desktopIds:[]).map(String).filter(Boolean);if(!ids.length)return false;

  // Resources have no physical desktop window. Automatic layout therefore
  // always collects them in the last existing Desk (D6 when D6 is last).
  const resourceDesk=ids[ids.length-1]||"";let changed=false;

  if(monitorStructureBundleDesk.codex){monitorStructureBundleDesk["codex-google"]||=monitorStructureBundleDesk.codex;delete monitorStructureBundleDesk.codex;changed=true;}

  for(const kind of monitorStructureBundleOrder()){

    if(!monitorStructureBundleDesk[kind]&&resourceDesk){monitorStructureBundleDesk[kind]=resourceDesk;changed=true;}

  }

  return changed;

}

function monitorStructureBundleName(kind) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureBundleName"].apply(this, arguments); }

function monitorStructureNodeIsActive(node,kind) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureNodeIsActive"].apply(this, arguments); }

function monitorStructureBundleIsActive(kind){
  if(kind==="local")return monitorLocalLlmIsUsable();
  return (monitorStructureBundleKinds()[kind]||[]).some(node=>monitorStructureNodeIsActive(node,kind));
}

async function monitorStructureShowLocalModels(){
  const control=await monitorEnsureLocalLlmControlStatus(true)||monitorLocalLlmControlState;
  const nodes=control?monitorLocalOllamaModels(control):(monitorStructureBundleKinds().local||[]);
  let dialog=document.getElementById("monitorStructureLocalModels");
  if(!dialog){dialog=document.createElement("dialog");dialog.id="monitorStructureLocalModels";dialog.className="monitor-org-local-models";monitorStructurePanel.append(dialog);}
  dialog.replaceChildren();

  const title=document.createElement("strong");title.textContent="L-LLM";
  const mode=document.createElement("small");mode.textContent="모델 관리 · 자동 권장";

  const list=document.createElement("div");list.className="monitor-org-local-model-list";
  for(const node of nodes){
    const row=document.createElement("div");
    const name=document.createElement("b");name.textContent=String(node?.model||node?.label||node?.node_id||"알 수 없는 모델");
    const state=document.createElement("small");
    const loaded=monitorLocalModelIsLoaded(node);
    state.textContent=loaded?"LOADED":"READY";
    row.className=loaded?"is-loaded":"is-ready";
    row.append(name,state);list.append(row);
  }
  if(!nodes.length)list.textContent="등록된 로컬 모델이 없습니다.";

  const actions=document.createElement("div");actions.className="monitor-worker-group-actions monitor-org-local-model-actions";
  const power=document.createElement("button");power.type="button";power.className="monitor-local-llm-toggle monitor-local-llm-dialog-action";
  monitorUpdateLocalLlmToggleButton(power);
  power.addEventListener("click",async()=>{
    if(monitorLocalLlmCommandState.inFlight)return;
    await monitorSetLocalLlmEnabled(monitorLocalLlmReadyState()!=="ready");
    if(dialog.open)void monitorStructureShowLocalModels();
  });
  const openUi=document.createElement("button");openUi.type="button";openUi.className="monitor-local-llm-open-ui monitor-local-llm-dialog-action";openUi.textContent="UI 열기";
  openUi.addEventListener("click",()=>chrome.windows.create({url:LOCAL_LLM_UI_URL,type:"popup",width:1200,height:820,focused:true}));
  const close=document.createElement("button");close.type="button";close.className="monitor-local-llm-dialog-action";close.textContent="닫기";close.addEventListener("click",()=>dialog.close());
  actions.append(power,openUi,close);

  dialog.append(title,mode,actions,list);
  if(!dialog.open)dialog.showModal();
}

function monitorStructureBundleNode(kind){
  kind=String(kind||"");
  const active=monitorStructureBundleIsActive(kind);
  return {
    node_key:"LLM:"+kind,
    node_id:"LLM:"+kind,
    node_type:"LLM",
    desktop_id:String(monitorStructureBundleDesk[kind]||""),
    role:"RESOURCE",
    capability:kind==="local"?"LOCAL_LLM":kind.startsWith("codex-")?"CODEX":"EXTERNAL_LLM",
    execution_mode:"INTERNAL",
    wake_mode:"NONE",
    status:active?"AVAILABLE":"OFFLINE",
    label:monitorStructureBundleName(kind),
  };
}

function monitorStructureSyncLocalBundleManagerEdges(layout=null){
  const localDesk=String(monitorStructureBundleDesk.local||"");
  const localResources=(monitorStructureBundleKinds().local||[])
    .map(node=>String(node?.resource_id||node?.node_id||"").trim())
    .filter(Boolean);
  const localSet=new Set(localResources);
  const preserved=monitorStructureResourceEdges.filter(edge=>!localSet.has(String(edge?.resource_id||"")));
  if(!localDesk||!localResources.length){
    monitorStructureResourceEdges=preserved;
    return false;
  }
  const resolved=layout||monitorStructureAutoLayout();
  const manager=resolved?.desktops?.[localDesk]?.manager||null;
  const supervisorKey=String(manager?.conversation_key||"").trim();
  if(!supervisorKey){
    monitorStructureResourceEdges=preserved;
    return false;
  }
  const next=localResources.map(resourceId=>({supervisor_key:supervisorKey,resource_id:resourceId,relation:"USES"}));
  monitorStructureResourceEdges=[...preserved,...next];
  return true;
}

function monitorStructureBundleCard(kind){
  const resources=monitorStructureBundleKinds()[kind]||[];
  const node=monitorStructureBundleNode(kind);
  const active=node.status==="AVAILABLE";
  const isCodex=kind.startsWith("codex-");
  const first=resources[0]||null;
  const identity=String(first?.label||first?.node_id||first?.resource_id||first?.model_id||first?.model||"RESOURCE").trim();
  const name=node.label;
  const card=document.createElement("div");
  card.className="monitor-org-bundle monitor-org-node-card monitor-org-bundle-"+(isCodex?"codex":kind)+(active?" is-available":" is-offline");
  card.draggable=true;
  card.dataset.bundleKind=kind;
  card.dataset.nodeKey=node.node_key;
  card.dataset.nodeType=node.node_type;
  card.dataset.desktopId=node.desktop_id;
  card.dataset.nodeRole=node.role;
  card.dataset.capability=node.capability;
  card.dataset.executionMode=node.execution_mode;
  card.dataset.wakeMode=node.wake_mode;
  card.dataset.nodeStatus=node.status;
  card.dataset.orgMoveNode="1";
  const id=document.createElement("b");
  id.textContent=name;
  const label=document.createElement("small");
  label.textContent=identity;
  card.append(id,label);
  card.title=(isCodex?"Google Codex":(kind==="local"?"Local LLM":"External LLM"))+" · "+identity+" · "+(active?"READY":"OFFLINE");
  if(kind==="local"){
    card.addEventListener("pointerdown",event=>event.stopPropagation());
    card.addEventListener("dblclick",event=>{event.preventDefault();event.stopPropagation();void monitorStructureShowLocalModels();});
  }
  return card;
}
function monitorStructureInstalledBundles(desktopId){const wrap=document.createElement("div");wrap.className="monitor-org-desk-bundles";for(const kind of monitorStructureBundleOrder())if(String(monitorStructureBundleDesk[kind]||"")===String(desktopId||""))wrap.append(monitorStructureBundleCard(kind));return wrap;}

function monitorStructureDeskNodeGrid(nodes,desktopId){
  const grid=monitorStructureWorkerStrip(nodes||[]);
  const bundles=[...monitorStructureInstalledBundles(desktopId).children];
  bundles.sort((a,b)=>Number(b.classList.contains("is-available"))-Number(a.classList.contains("is-available")));
  grid.append(...bundles,monitorStructureDeskTransferSlot(desktopId));
  return grid;
}

function monitorStructureAutoLayout(){

  const nodes=monitorStructureAvailableNodes().map(node=>({...node,placement_exempt:monitorStructureNodeIsPlacementExempt(node)})); const used=new Set(); const isExempt=(node)=>Boolean(node?.placement_exempt); const liveByKey=new Map(nodes.map(n=>[String(n.conversation_key||""),n])); const liveDraft=(node)=>{const draft=node?liveByKey.get(String(node.conversation_key||""))||null:null;return draft&&!isExempt(draft)?draft:null;}; const pickRole=(role)=>nodes.find(n=>n.role===role&&!isExempt(n)&&!used.has(n.conversation_key))||null; const commandDesktopId=String(monitorDesktopState.desktopIds?.[0]||""); const pickCommandFallback=()=>nodes.find(n=>!isExempt(n)&&!used.has(n.conversation_key)&&commandDesktopId&&monitorStructureEffectiveDesktopId(n)===commandDesktopId)||null;

  const orchestrator=liveDraft(monitorStructureSocketDraft.orchestrator)||pickRole("ORCHESTRATOR")||pickCommandFallback(); if(orchestrator)used.add(orchestrator.conversation_key);

  const aux1=liveDraft(monitorStructureSocketDraft.aux1)||pickRole("COORDINATOR_1")||pickCommandFallback(); if(aux1)used.add(aux1.conversation_key);

  const aux2=liveDraft(monitorStructureSocketDraft.aux2)||pickRole("COORDINATOR_2")||pickCommandFallback(); if(aux2)used.add(aux2.conversation_key);

  const desktops={};

  const observedDesktopIds=monitorDesktopState.desktopIds.length?monitorDesktopState.desktopIds.slice():[...monitorDesktopThumbs.querySelectorAll('.monitor-desktop-thumb[data-desktop-id]')].map(x=>String(x.dataset.desktopId||'')).filter(Boolean);
  // D1 is a permanent command Desk in the organization projection.  A
  // transiently empty browser/native snapshot must not make it disappear.
  const desktopIds=observedDesktopIds.length?observedDesktopIds:["D1"];

  monitorStructureEnsureBundleDefaults(desktopIds);

  desktopIds.forEach((desktopId,index)=>{

    // Command roles are D1 slots, not ordinary Desk membership.  Keeping the
    // slots fixed makes an empty D1 legible and prevents a coordinator from
    // visually drifting into a worker Desk.
    const roles=index===0?[orchestrator,aux1,aux2].filter(Boolean):[];
    const all=nodes.filter(n=>monitorStructureEffectiveDesktopId(n)===desktopId&&!used.has(n.conversation_key)).sort((a,b)=>a.node_order-b.node_order||a.label.localeCompare(b.label));

    const hasOrchestrator=index===0;const manual=hasOrchestrator?null:liveDraft(monitorStructureSocketDraft.managers?.[desktopId]||null);const roleManager=hasOrchestrator?null:all.find(n=>!isExempt(n)&&n.role==="MANAGER")||null;const manager=hasOrchestrator?null:(manual||roleManager||all.find(n=>!isExempt(n))||null);if(manager)used.add(manager.conversation_key);

    desktops[desktopId]={index,roles,manager,workers:all.filter(n=>!manager||n.conversation_key!==manager.conversation_key)};

  });

  return {orchestrator,aux1,aux2,desktops};

}

function monitorStructureNodeForHwnd(hwnd){return monitorStructureAvailableNodes().find(node=>String(node.hwnd||"")===String(hwnd||""))||null;}

function monitorStructureRemoveNode(key){

  if(monitorStructureSocketDraft.orchestrator?.conversation_key===key)monitorStructureSocketDraft.orchestrator=null;

  if(monitorStructureSocketDraft.aux1?.conversation_key===key)monitorStructureSocketDraft.aux1=null;

  if(monitorStructureSocketDraft.aux2?.conversation_key===key)monitorStructureSocketDraft.aux2=null;

  for(const desktopId of Object.keys(monitorStructureSocketDraft.managers||{}))if(monitorStructureSocketDraft.managers[desktopId]?.conversation_key===key)delete monitorStructureSocketDraft.managers[desktopId];

}

function monitorStructureNodeControlState(key){

  const saved=monitorStructureNodeControls?.[String(key||"")]||{};

  return {auto:Boolean(saved.auto ?? saved.auto_wake ?? false)};

}

function monitorStructurePersistNodeControls(){chrome.storage.local.set({[MONITOR_STRUCTURE_NODE_CONTROL_KEY]:monitorStructureNodeControls});}

async function monitorStructureToggleNodeControl(key){

  key=String(key||"");if(!key)return;

  const enabled=!monitorStructureNodeControlState(key).auto;

  const r=await actFetch(ORCHESTRATOR_NODE_CONTROL_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_key:key,enabled})});

  const d=await r.json().catch(()=>null);if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);

  monitorStructureNodeControls[key]={auto:Boolean(d.auto_wake??d.enabled)};monitorStructurePersistNodeControls();renderMonitorStructure();

}

function monitorStructureNodeDisplayName(node) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureNodeDisplayName"].apply(this, arguments); }

function monitorStructureNodeShortNumber(node) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureNodeShortNumber"].apply(this, arguments); }

function monitorStructureSocketCard(node,compact=false,withControls=false){
  const controlState=withControls?monitorStructureNodeControlState(node?.conversation_key):null;
  const numberText=compact?monitorStructureNodeShortNumber(node):(String(node?.label||"").trim()||"NODE");
  const nameText=monitorStructureNodeDisplayName(node);
  const card=document.createElement("div");
  card.className="monitor-org-node-card"+(compact?" monitor-org-node-card-compact":"")+(withControls?" monitor-org-node-controlled":"")+(controlState?.auto?" is-auto":"")+(monitorStructureNodeIsPlacementExempt(node)?" is-exempt":"");
  card.setAttribute("role","button");
  card.setAttribute("aria-label",numberText+" · "+nameText+(withControls?(" · AUTO "+(controlState?.auto?"ON":"OFF")):""));
  card.title=numberText+" · "+nameText;
  if(withControls)card.dataset.controlNode="1";

  const number=document.createElement("span");
  number.className="monitor-org-node-number";
  number.textContent=numberText;

  const marker=document.createElement("span");marker.className="monitor-org-node-marker";marker.setAttribute("aria-hidden","true");
  card.append(marker,number);
  if(!compact){
    const name=document.createElement("span");
    name.className="monitor-org-node-name";
    name.textContent=nameText;
    card.append(name);
  }
  return card;
}

function monitorStructureRenderSocket(box,node){
  box.replaceChildren();
  if(node){
    const card=monitorStructureSocketCard(node,true,true);
    card.dataset.nodeKey=String(node.conversation_key||"");
    card.draggable=false;
    card.dataset.orgMoveNode="1";
    box.append(card);
  }else{
    const hint=document.createElement("span");
    hint.className="monitor-org-socket-hint";
    hint.setAttribute("aria-label","빈 역할 슬롯");
    box.append(hint);
  }
}
function monitorStructureWorkerStrip(nodes){

  const strip=document.createElement("div");strip.className="monitor-org-workers";

  for(const node of nodes){const item=monitorStructureSocketCard(node,true,true);item.classList.add("monitor-org-worker-card");item.draggable=false;item.dataset.nodeKey=String(node.conversation_key||"");item.dataset.orgMoveNode="1";strip.append(item);}return strip;

}

function monitorStructureDeskTransferSlot(desktopId){const slot=document.createElement("div");slot.className="monitor-org-node-slot";slot.dataset.desktopId=String(desktopId||"");slot.textContent="+";slot.title="이 데스크로 노드 또는 자원 이동";return slot;}

function monitorStructureDefaultParents(layout){

  const parents={},key=n=>String(n?.conversation_key||""),isExempt=n=>Boolean(n?.placement_exempt);

  for(const group of Object.values(layout.desktops||{})){
    const managerKey=key(group?.manager);if(!managerKey||isExempt(group?.manager))continue;
    for(const worker of (group?.workers||[])){const workerKey=key(worker);if(workerKey&&workerKey!==managerKey&&!isExempt(worker))parents[workerKey]=managerKey;}
  }
  const managers=Object.values(layout.desktops||{}).map(g=>g.manager).filter(Boolean);

  const auxes=[layout.aux1,layout.aux2].filter(Boolean);

  if(layout.orchestrator&&!isExempt(layout.orchestrator))for(const aux of auxes)if(!isExempt(aux))parents[key(aux)]=key(layout.orchestrator);

  if(auxes.length===2){const split=Math.ceil(managers.length/2);managers.forEach((m,i)=>{const parent=i<split?auxes[0]:auxes[1];if(!isExempt(m)&&!isExempt(parent))parents[key(m)]=key(parent);});}

  else if(auxes.length===1)managers.forEach(m=>{if(!isExempt(m)&&!isExempt(auxes[0]))parents[key(m)]=key(auxes[0]);});

  else if(layout.orchestrator&&!isExempt(layout.orchestrator))managers.forEach(m=>{if(!isExempt(m))parents[key(m)]=key(layout.orchestrator);});

  return parents;

}

function monitorStructureEffectiveParents(layout){const parents=monitorStructureDefaultParents(layout);for(const [child,parent] of Object.entries(monitorStructureLinkOverrides||{})){if(parent)parents[child]=parent;else delete parents[child];}return parents;}

function monitorStructureAuthorityOverrides(data,layout){
  const defaults=monitorStructureDefaultParents(layout),nextLinks={};
  for(const edge of (Array.isArray(data?.edges)?data.edges:[])){
    const child=String(edge?.child_key||"").trim(),parent=String(edge?.parent_key||"").trim();
    if(child&&parent&&defaults[child]!==parent)nextLinks[child]=parent;
  }
  for(const child of (Array.isArray(data?.detached_children)?data.detached_children:[])){
    const key=String(child||"").trim();if(key)nextLinks[key]=null;
  }
  return nextLinks;
}

function monitorStructurePersistLinks(){chrome.storage.local.set({[MONITOR_STRUCTURE_LINK_KEY]:monitorStructureLinkOverrides});}

function monitorStructureWouldCycle(child,parent,parents){let cur=parent;const seen=new Set([child]);while(cur){if(seen.has(cur))return true;seen.add(cur);cur=parents[cur]||"";}return false;}

function monitorStructureSupervisorKeys(layout){

  return new Set([layout.orchestrator,layout.aux1,layout.aux2,...Object.values(layout.desktops||{}).map(x=>x.manager)].filter(Boolean).map(x=>String(x.conversation_key||"")));

}

function monitorStructureResourceConnections(resourceId){

  return monitorStructureResourceEdges.filter(e=>String(e.resource_id||"")===String(resourceId||"")).map(e=>String(e.supervisor_key||""));

}

function monitorStructureToggleResourceEdge(supervisorKey,resourceId){

  supervisorKey=String(supervisorKey||"");resourceId=String(resourceId||"");if(!supervisorKey||!resourceId)return;

  const historyBefore=monitorStructureHistorySnapshot();
  const exists=monitorStructureResourceEdges.some(e=>e.supervisor_key===supervisorKey&&e.resource_id===resourceId);

  monitorStructureResourceEdges=exists?monitorStructureResourceEdges.filter(e=>!(e.supervisor_key===supervisorKey&&e.resource_id===resourceId)):[...monitorStructureResourceEdges,{supervisor_key:supervisorKey,resource_id:resourceId,relation:"USES"}];

  monitorStructureDirty=true;
  monitorStructureHistoryCommit(historyBefore);

  renderMonitorStructure(); const status=document.getElementById("monitorStructureStatus"); if(status)status.textContent="DRAFT ? AI ?? ?? ??? ? ?? ?";

}

function monitorStructureRenderResourcePools(){

  const local=document.getElementById("monitorStructureLocalPool"),external=document.getElementById("monitorStructureExternalPool"),codex=document.getElementById("monitorStructureCodexPool");if(!local||!external||!codex)return;local.replaceChildren();external.replaceChildren();codex.replaceChildren();

  const legacy=Array.isArray(monitorLastAiState?.llm_nodes)?monitorLastAiState.llm_nodes:[];

  const merged=[...(Array.isArray(monitorStructureAiNodes)?monitorStructureAiNodes:[]),...legacy];

  const seen=new Set();

  for(const node of merged){

    const resourceId=String(node?.node_id||node?.resource_id||"");if(!resourceId||seen.has(resourceId))continue;seen.add(resourceId);

    const rawKind=String(node?.kind||node?.provider_kind||node?.provider||"").toLowerCase();

    const kind=rawKind==="codex"||String(node?.provider||"").toLowerCase()==="codex"?"codex":rawKind==="local"?"local":"external";

    const card=document.createElement("div");card.className="monitor-org-resource-card";card.draggable=true;card.dataset.resourceId=resourceId;

    if(monitorStructureResourceConnections(resourceId).length)card.classList.add("is-linked");

    const identity=document.createElement("div");identity.className="monitor-org-resource-identity";identity.textContent=String(node?.model||node?.model_id||resourceId||"AI");

    const taskRole=String(node?.current_task_role||node?.task_role||"").trim().toUpperCase();

    const runtime=String(node?.busy===true?"BUSY":node?.status||node?.availability||"UNKNOWN").trim().toUpperCase();

    const trust=String(node?.trust_tier||"STANDARD").trim().toUpperCase();

    const policy=String(node?.execution_policy||"ACT_POLICY").trim().toUpperCase();

    const meta=document.createElement("div");meta.className="monitor-org-resource-meta";meta.textContent=[runtime,taskRole?`ROLE ${taskRole}`:"ROLE -",`TRUST ${trust}`,`EXEC ${policy}`].join(" ? ");

    const links=monitorStructureResourceConnections(resourceId);const edge=document.createElement("div");edge.className="monitor-org-resource-edge";edge.textContent=links.length?`USES ${links.length}`:"USES 0";

    card.append(identity,meta,edge);card.title=`model=${identity.textContent} | role=${taskRole||"none"} | state=${runtime} | trust=${trust} | execution=${policy}`;

    (kind==="local"?local:kind==="codex"?codex:external).append(card);

  }

  if(!local.children.length)local.textContent="No LOCAL AI resource";if(!external.children.length)external.textContent="No EXTERNAL AI resource";if(!codex.children.length)codex.textContent="No CODEX resource";

  const managerState=document.getElementById("monitorStructureCodexManagerState");

  if(managerState){const ws=(monitorStructureWorkspaces||[]).find(x=>String(x?.workspace_id||"").toUpperCase()==="CODEX");const metrics=monitorStructureExecutorMetrics?.codex||{};const manager=String(ws?.manager_key||"").trim()||"UNASSIGNED";const workers=Array.isArray(ws?.workers)?ws.workers.length:0;const runs=Number(metrics?.runs_with_telemetry||0);const avg=Number(metrics?.average_elapsed_s);const usage=metrics?.usage||{};const tokenTotal=Number(usage?.input_tokens||0)+Number(usage?.output_tokens||0);managerState.textContent=`${manager} ? ${ws?.status||"NO WORKSPACE"} ? worker ${workers} ? measured ${runs}${Number.isFinite(avg)?` ? avg ${avg.toFixed(2)}s`:""}${tokenTotal?` ? token ${tokenTotal.toLocaleString()}`:""}`;}

}

function monitorStructureApplyActHierarchy(data){

  const nextLinks=monitorStructureAuthorityOverrides(data,monitorStructureAutoLayout());

  monitorStructureLinkOverrides=nextLinks;monitorStructurePersistLinks();

  const nextControls={};for(const item of (Array.isArray(data?.node_controls)?data.node_controls:[])){const key=String(item?.conversation_key||"").trim();if(key)nextControls[key]={auto:Boolean(item?.auto_wake??item?.enabled)};}

  monitorStructureNodeControls=nextControls;monitorStructurePersistNodeControls();

  if(Array.isArray(data?.resource_edges))monitorStructureResourceEdges=data.resource_edges.map(e=>({supervisor_key:String(e?.supervisor_key||""),resource_id:String(e?.resource_id||""),relation:"USES"})).filter(e=>e.supervisor_key&&e.resource_id);

  if(Number.isInteger(Number(data?.organization_generation)))monitorStructureOrganizationGeneration=Number(data.organization_generation);

}

async function monitorStructureRefreshAuthority(){

  const [hr,rr,ar,wr,mr]=await Promise.all([actFetch(ORCHESTRATOR_HIERARCHY_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_RESOURCES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_AI_NODES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_WORKSPACES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_EXECUTOR_METRICS_URL,{cache:"no-store"})]);

  const h=await hr.json().catch(()=>null),r=await rr.json().catch(()=>null),a=await ar.json().catch(()=>null),w=await wr.json().catch(()=>null),m=await mr.json().catch(()=>null);

  if(!hr.ok||!h?.ok)throw new Error(h?.error||`HTTP ${hr.status}`);if(rr.ok&&r?.ok){h.resource_edges=Array.isArray(r.resource_edges)?r.resource_edges:[];h.organization_generation=r.organization_generation;}

  monitorStructureAiNodes=ar.ok&&a?.ok&&Array.isArray(a.nodes)?a.nodes:[];monitorStructureWorkspaces=wr.ok&&w?.ok&&Array.isArray(w.workspaces)?w.workspaces:[];monitorStructureExecutorMetrics=mr.ok&&m?.ok?m:null;monitorStructureApplyActHierarchy(h);return h;

}

function monitorStructureBuildSavePayload(){

  const layout=monitorStructureAutoLayout(),assignments=[],workplaces=[];

  const add=(node,role,workplace,slot_id)=>{if(node?.conversation_key)assignments.push({conversation_key:String(node.conversation_key),role,workplace:workplace||null,slot_id,transport_instance_id:String(node.transport_instance_id||""),session_id:String(node.session_id||""),tab_id:node.tab_id??null});};

  const roleWorkplace=node=>{const key=String(node?.conversation_key||""),entry=Object.values(layout.desktops||{}).find(group=>(group.roles||[]).some(roleNode=>String(roleNode?.conversation_key||"")===key));return entry?`D${Number(entry.index)+1}`:null;};
  const addRole=(node,role)=>{const workplace=roleWorkplace(node);add(node,role,workplace,workplace?`${workplace}:${role}`:role);};
  addRole(layout.orchestrator,"ORCHESTRATOR");addRole(layout.aux1,"COORDINATOR_1");addRole(layout.aux2,"COORDINATOR_2");

  for(const [,group] of Object.entries(layout.desktops||{}).sort((a,b)=>Number(a[1]?.index)-Number(b[1]?.index))){

    const workplace=`D${Number(group.index)+1}`;workplaces.push(workplace);add(group.manager,"MANAGER",workplace,`${workplace}:MANAGER`);

    (group.workers||[]).forEach((node,index)=>add(node,"WORKER",workplace,`${workplace}:WORKER-${index+1}`));

  }

  const keys=new Set(assignments.map(x=>x.conversation_key)),parents=monitorStructureEffectiveParents(layout);

  const edges=Object.entries(parents).filter(([child,parent])=>keys.has(child)&&keys.has(String(parent||""))).map(([child,parent])=>({parent_key:String(parent),child_key:String(child),relation:"MANAGES"}));

  const detached_children=Object.entries(monitorStructureLinkOverrides||{}).filter(([child,parent])=>parent===null&&keys.has(child)).map(([child])=>child);

  if(!Number.isInteger(monitorStructureOrganizationGeneration))throw new Error("ORGANIZATION_GENERATION_REQUIRED");

  return {assignments,workplaces,edges,detached_children,resource_edges:monitorStructureResourceEdges.slice(),expected_generation:monitorStructureOrganizationGeneration,actor:"USER_MONITOR"};

}

function monitorStructureCloneDraftValue(value){
  try{return structuredClone(value);}catch(_){try{return JSON.parse(JSON.stringify(value));}catch(__){return value;}}
}

function monitorStructureHistorySnapshot(){
  return {
    socketDraft:monitorStructureCloneDraftValue(monitorStructureSocketDraft),
    linkOverrides:monitorStructureCloneDraftValue(monitorStructureLinkOverrides),
    placementExemptions:monitorStructureCloneDraftValue(monitorStructurePlacementExemptions),
    deskMembership:monitorStructureCloneDraftValue(monitorStructureDeskMembership),
    bundleDesk:monitorStructureCloneDraftValue(monitorStructureBundleDesk),
    resourceEdges:monitorStructureCloneDraftValue(monitorStructureResourceEdges),
    dirty:Boolean(monitorStructureDirty),
  };
}

function monitorStructureHistoryKey(snapshot) { return globalThis.MonitorDomainAPIs["organization"]["monitorStructureHistoryKey"].apply(this, arguments); }

function monitorStructureUpdateHistoryButtons(){
  const undo=document.getElementById("monitorStructureUndo");
  const redo=document.getElementById("monitorStructureRedo");
  if(undo)undo.disabled=monitorStructureUndoStack.length===0;
  if(redo)redo.disabled=monitorStructureRedoStack.length===0;
}

function monitorStructureHistoryReset(){
  monitorStructureUndoStack.length=0;
  monitorStructureRedoStack.length=0;
  monitorStructureUpdateHistoryButtons();
}

function monitorStructureHistoryCommit(before){
  if(!before)return false;
  const after=monitorStructureHistorySnapshot();
  if(monitorStructureHistoryKey(before)===monitorStructureHistoryKey(after))return false;
  monitorStructureUndoStack.push(monitorStructureCloneDraftValue(before));
  if(monitorStructureUndoStack.length>MONITOR_STRUCTURE_HISTORY_LIMIT)monitorStructureUndoStack.shift();
  monitorStructureRedoStack.length=0;
  monitorStructureUpdateHistoryButtons();
  void monitorStructurePersistWorkingDraft();
  return true;
}

function monitorStructureApplyHistorySnapshot(snapshot){
  if(!snapshot)return false;
  monitorStructureSocketDraft=monitorStructureCloneDraftValue(snapshot.socketDraft)||{orchestrator:null,aux1:null,aux2:null,managers:{}};
  monitorStructureLinkOverrides=monitorStructureCloneDraftValue(snapshot.linkOverrides)||{};
  monitorStructurePlacementExemptions=monitorStructureCloneDraftValue(snapshot.placementExemptions)||{};
  monitorStructureDeskMembership=monitorStructureCloneDraftValue(snapshot.deskMembership)||{};
  monitorStructureBundleDesk=monitorStructureCloneDraftValue(snapshot.bundleDesk)||{};
  monitorStructureResourceEdges=Array.isArray(snapshot.resourceEdges)?monitorStructureCloneDraftValue(snapshot.resourceEdges):[];
  monitorStructureDirty=Boolean(snapshot.dirty);
  renderMonitorStructure();
  void monitorStructurePersistWorkingDraft();
  return true;
}

function monitorStructureUndoAction(){
  if(!monitorStructureUndoStack.length)return;
  const current=monitorStructureHistorySnapshot();
  const previous=monitorStructureUndoStack.pop();
  monitorStructureRedoStack.push(current);
  if(monitorStructureRedoStack.length>MONITOR_STRUCTURE_HISTORY_LIMIT)monitorStructureRedoStack.shift();
  monitorStructureApplyHistorySnapshot(previous);
  monitorStructureUpdateHistoryButtons();
  const status=document.getElementById("monitorStructureStatus");
  if(status)status.textContent="UNDO · 직전 조직도 변경을 되돌렸습니다";
}

function monitorStructureRedoAction(){
  if(!monitorStructureRedoStack.length)return;
  const current=monitorStructureHistorySnapshot();
  const next=monitorStructureRedoStack.pop();
  monitorStructureUndoStack.push(current);
  if(monitorStructureUndoStack.length>MONITOR_STRUCTURE_HISTORY_LIMIT)monitorStructureUndoStack.shift();
  monitorStructureApplyHistorySnapshot(next);
  monitorStructureUpdateHistoryButtons();
  const status=document.getElementById("monitorStructureStatus");
  if(status)status.textContent="REDO · 되돌린 조직도 변경을 다시 적용했습니다";
}

function monitorStructureBaselineSnapshot(){
  return {...monitorStructureHistorySnapshot(),savedAt:Date.now()};
}

function monitorStructurePersistWorkingDraft(){
  const snapshot={...monitorStructureHistorySnapshot(),savedAt:Date.now()};
  return chrome.storage.local.set({[MONITOR_STRUCTURE_WORKING_DRAFT_KEY]:snapshot});
}

function monitorStructureReconcileSnapshot(snapshot){
  if(!snapshot||typeof snapshot!=="object")return null;
  const next=monitorStructureCloneDraftValue(snapshot)||null;
  if(!next)return null;
  const liveKeys=new Set(monitorStructureAvailableNodes().map(node=>String(node?.conversation_key||"")).filter(Boolean));
  const desktops=new Set((monitorDesktopState.desktopIds||[]).map(String));
  const keepNode=node=>node&&liveKeys.has(String(node?.conversation_key||""))?node:null;
  next.socketDraft=next.socketDraft&&typeof next.socketDraft==="object"?next.socketDraft:{orchestrator:null,aux1:null,aux2:null,managers:{}};
  next.socketDraft.orchestrator=keepNode(next.socketDraft.orchestrator);
  next.socketDraft.aux1=keepNode(next.socketDraft.aux1);
  next.socketDraft.aux2=keepNode(next.socketDraft.aux2);
  const managers={};
  for(const [desktopId,node] of Object.entries(next.socketDraft.managers||{})){
    const kept=keepNode(node);
    if(kept&&desktops.has(String(desktopId)))managers[String(desktopId)]=kept;
  }
  next.socketDraft.managers=managers;

  const commandDeskId=String((monitorDesktopState.desktopIds||[])[0]||"");
  if(commandDeskId){
    const assigned=new Set([
      String(next.socketDraft.orchestrator?.conversation_key||""),
      String(next.socketDraft.aux1?.conversation_key||""),
      String(next.socketDraft.aux2?.conversation_key||""),
    ].filter(Boolean));
    const candidates=monitorStructureAvailableNodes()
      .filter(node=>String(node?.desktop_id||"")===commandDeskId&&!assigned.has(String(node?.conversation_key||"")))
      .sort((a,b)=>Number(a?.node_order||0)-Number(b?.node_order||0)||String(a?.label||"").localeCompare(String(b?.label||"")));
    if(!next.socketDraft.orchestrator)next.socketDraft.orchestrator=candidates.shift()||null;
    if(!next.socketDraft.aux1)next.socketDraft.aux1=candidates.shift()||null;
    if(!next.socketDraft.aux2)next.socketDraft.aux2=candidates.shift()||null;
  }

  const links={};
  for(const [child,parent] of Object.entries(next.linkOverrides||{})){
    const childKey=String(child||"");
    const parentKey=String(parent||"");
    if(!liveKeys.has(childKey))continue;
    if(!parent){links[childKey]=null;continue;}
    if(liveKeys.has(parentKey))links[childKey]=parentKey;
  }
  next.linkOverrides=links;
  const placementExemptions={};
  for(const [key,value] of Object.entries(next.placementExemptions||{})){
    if(liveKeys.has(String(key)))placementExemptions[String(key)]=Boolean(value);
  }
  next.placementExemptions=placementExemptions;
  const membership={};
  for(const [key,desktopId] of Object.entries(next.deskMembership||{})){
    if(liveKeys.has(String(key))&&desktops.has(String(desktopId)))membership[String(key)]=String(desktopId);
  }
  next.deskMembership=membership;
  const bundleDesk={};
  for(const [kind,desktopId] of Object.entries(next.bundleDesk||{})){
    if(desktops.has(String(desktopId)))bundleDesk[String(kind)]=String(desktopId);
  }
  next.bundleDesk=bundleDesk;
  next.resourceEdges=Array.isArray(next.resourceEdges)?next.resourceEdges.filter(edge=>{
    const supervisor=String(edge?.supervisor_key||"");
    return !supervisor||liveKeys.has(supervisor);
  }):[];
  return next;
}

function monitorStructurePersistBaseline(){
  const snapshot=monitorStructureBaselineSnapshot();
  monitorStructureBaseline=monitorStructureCloneDraftValue(snapshot);
  return chrome.storage.local.set({[MONITOR_STRUCTURE_BASELINE_KEY]:snapshot});
}

function monitorStructureApplyBaseline(){
  if(!monitorStructureBaseline)return false;
  return monitorStructureApplyHistorySnapshot(monitorStructureBaseline);
}

function monitorStructureRunAutoLayout(){

  const historyBefore=monitorStructureHistorySnapshot();
  monitorStructureSocketDraft={orchestrator:null,aux1:null,aux2:null,managers:{}};

  monitorStructureLinkOverrides={};monitorStructurePlacementExemptions={};monitorStructureDeskMembership={};monitorStructureBundleDesk={};monitorStructureDirty=true;

  const ids=monitorDesktopState.desktopIds.length?monitorDesktopState.desktopIds.slice():[...monitorDesktopThumbs.querySelectorAll('.monitor-desktop-thumb[data-desktop-id]')].map(x=>String(x.dataset.desktopId||'')).filter(Boolean);

  const commandDeskId=String(ids[0]||"");
  if(commandDeskId){
    const commandNodes=monitorStructureAvailableNodes()
      .filter(node=>String(node?.desktop_id||"")===commandDeskId)
      .sort((a,b)=>Number(a?.node_order||0)-Number(b?.node_order||0)||String(a?.label||"").localeCompare(String(b?.label||"")));
    monitorStructureSocketDraft.orchestrator=commandNodes[0]||null;
    monitorStructureSocketDraft.aux1=commandNodes[1]||null;
    monitorStructureSocketDraft.aux2=commandNodes[2]||null;
  }

  monitorStructureEnsureBundleDefaults(ids);
  const layout=monitorStructureAutoLayout();
  monitorStructureSyncLocalBundleManagerEdges(layout);
  monitorStructureHistoryCommit(historyBefore);
  renderMonitorStructure();

  const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="자동배치 완료 · 현재 실제 노드 위치 기준 · 아직 미저장";

}

function monitorStructureDetachAll(nodeKey){

  nodeKey=String(nodeKey||"");if(!nodeKey)return false;const historyBefore=monitorStructureHistorySnapshot();const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());let changed=false;

  if(Object.prototype.hasOwnProperty.call(parents,nodeKey)){monitorStructureLinkOverrides[nodeKey]=null;changed=true;}

  for(const [child,parent] of Object.entries(parents))if(String(parent||"")===nodeKey){monitorStructureLinkOverrides[child]=null;changed=true;}

  if(changed){monitorStructureDirty=true;monitorStructureHistoryCommit(historyBefore);renderMonitorStructure();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="노드 연결 해제됨 · 부모/자식 관리선 모두 끊김";}return changed;
}

function monitorStructureSetNodeExempt(nodeKey){
  nodeKey=String(nodeKey||"");if(!nodeKey)return false;
  const node=monitorStructureAvailableNodes().find(item=>String(item?.conversation_key||"")===nodeKey)||null;
  if(!node)return false;
  const historyBefore=monitorStructureHistorySnapshot();
  const nextExempt=!monitorStructureNodeIsPlacementExempt(node);
  monitorStructurePlacementExemptions[nodeKey]=nextExempt;
  monitorStructureDirty=true;
  monitorStructureHistoryCommit(historyBefore);
  renderMonitorStructure();
  const st=document.getElementById("monitorStructureStatus");
  if(st)st.textContent=nextExempt
    ?"열외 배치됨 · 위치 변경 확정 전까지 조직도에만 적용"
    :"일반 노드로 복귀함 · 위치 변경 확정 전까지 조직도에만 적용";
  return true;
}

function monitorStructureDetachBlankStep(nodeKey){
  nodeKey=String(nodeKey||"");if(!nodeKey)return false;
  const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());
  const parentKey=String(parents[nodeKey]||"");
  if(parentKey){
    const historyBefore=monitorStructureHistorySnapshot();
    monitorStructureLinkOverrides[nodeKey]=null;
    monitorStructureDirty=true;
    monitorStructureHistoryCommit(historyBefore);
    renderMonitorStructure();
    const st=document.getElementById("monitorStructureStatus");
    if(st)st.textContent="부모 연결 해제됨 · 자식 연결은 유지";
    return true;
  }
  const hasChildren=Object.entries(parents).some(([,parent])=>String(parent||"")===nodeKey);
  if(hasChildren)return monitorStructureDetachAll(nodeKey);
  const st=document.getElementById("monitorStructureStatus");
  if(st)st.textContent="열외 지정 중";
  return monitorStructureSetNodeExempt(nodeKey);

}

async function monitorStructureResetDraft(){

  const historyBefore=monitorStructureHistorySnapshot();
  const baseline=monitorStructureReconcileSnapshot(monitorStructureBaseline);
  if(baseline){
    monitorStructureBaseline=monitorStructureCloneDraftValue(baseline);
    monitorStructureApplyBaseline();
    monitorStructureHistoryCommit(historyBefore);
    const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="초기화 완료 · 마지막 확정 기준 상태로 되돌림";
    return;
  }
  monitorStructureRunAutoLayout();
  monitorStructureDirty=false;
  await monitorStructurePersistBaseline();
  await monitorStructurePersistWorkingDraft();
  monitorStructureHistoryReset();
  const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="초기화 완료 · 현재 실제 Desk 기준 자동배치를 새 기준 상태로 지정";

}

async function monitorStructureExecuteDeskMoves(){

  const requested=Object.entries(monitorStructureDeskMembership||{}).map(([nodeKey,desktopId])=>[String(nodeKey||""),String(desktopId||"")]).filter(([nodeKey,desktopId])=>nodeKey&&desktopId);

  if(!requested.length)return {moved:0,moves:[]};

  await refreshMonitorRoleAdmin();await refreshAiMonitor();

  const byKey=new Map(monitorStructureAvailableNodes().map(node=>[String(node?.conversation_key||""),node])),planned=[];

  const desktopIds=(monitorDesktopState.desktopIds.length?monitorDesktopState.desktopIds.slice():[...monitorDesktopThumbs.querySelectorAll('.monitor-desktop-thumb[data-desktop-id]')].map(x=>String(x.dataset.desktopId||'')).filter(Boolean)).map(String);

  for(const [nodeKey,targetDesktopId] of requested){const node=byKey.get(nodeKey);if(!node){delete monitorStructureDeskMembership[nodeKey];continue;}const sourceDesktopId=String(node?.desktop_id||"");if(sourceDesktopId===targetDesktopId){delete monitorStructureDeskMembership[nodeKey];continue;}const hwnd=String(node?.hwnd||"");if(!/^\d+$/.test(hwnd)||hwnd==="0"||!sourceDesktopId)throw new Error(`Desk 이동 준비 실패 · ${String(node?.label||nodeKey.slice(0,8))}`);const targetDeskIndex=desktopIds.indexOf(targetDesktopId);if(targetDeskIndex<0)throw new Error(`대상 Desk 확인 실패 · ${String(node?.label||nodeKey.slice(0,8))}`);planned.push({nodeKey,hwnd,sourceDesktopId,targetDesktopId,targetDeskNumber:targetDeskIndex+1,label:String(node?.label||nodeKey.slice(0,8))});}

  const moved=[];

  try{for(const item of planned){await moveMonitorWindowToDesktop(item.hwnd,item.sourceDesktopId,item.targetDesktopId);moved.push(item);}}

  catch(error){let rollbackError=null;for(const item of moved.slice().reverse()){try{await moveMonitorWindowToDesktop(item.hwnd,item.targetDesktopId,item.sourceDesktopId);}catch(e){rollbackError=e;break;}}await refreshMonitorRoleAdmin().catch(()=>{});await refreshAiMonitor().catch(()=>{});if(rollbackError)throw new Error(`Desk 이동 실패 · 자동 복구도 실패 · ${monitorDiagTextError(error)} / ${monitorDiagTextError(rollbackError)}`);throw new Error(`Desk 이동 실패 · 이전 위치로 복구됨 · ${monitorDiagTextError(error)}`);}

  if(planned.length){let confirmed=false;for(let attempt=0;attempt<8;attempt++){if(attempt)await new Promise(resolve=>setTimeout(resolve,250));await refreshMonitorRoleAdmin();await refreshAiMonitor();const after=new Map(monitorStructureAvailableNodes().map(node=>[String(node?.conversation_key||""),node]));confirmed=planned.every(item=>{const current=after.get(item.nodeKey);const physicalOk=String(current?.desktop_id||"")===item.targetDesktopId;const label=String(current?.label||"").trim().toUpperCase();const parts=label.split("-");const numberOk=parts.length===2&&parts[0]===`D${item.targetDeskNumber}`&&/^[0-9]+$/.test(parts[1]);return physicalOk&&numberOk;});if(confirmed)break;}if(!confirmed){await monitorStructureRollbackDeskMoves({moves:planned});throw new Error("Desk 이동 후 새 노드 번호 확정 실패 · 이전 Desk로 복구됨");}}

  return {moved:planned.length,moves:planned};

}

async function monitorStructureRollbackDeskMoves(moveResult){

  const moves=Array.isArray(moveResult?.moves)?moveResult.moves:[];

  if(!moves.length)return {rolledBack:0};

  let rolledBack=0,rollbackError=null;

  for(const item of moves.slice().reverse()){try{await moveMonitorWindowToDesktop(item.hwnd,item.targetDesktopId,item.sourceDesktopId);rolledBack++;}catch(error){rollbackError=error;break;}}

  await refreshMonitorRoleAdmin().catch(()=>{});await refreshAiMonitor().catch(()=>{});

  if(!rollbackError){const after=new Map(monitorStructureAvailableNodes().map(node=>[String(node?.conversation_key||""),node]));const failed=moves.find(item=>String(after.get(item.nodeKey)?.desktop_id||"")!==item.sourceDesktopId);if(failed)rollbackError=new Error(`Desk 자동 복구 확인 실패 · ${failed.label}`);}

  if(rollbackError)throw new Error(`ACT 저장 실패 후 Desk 자동 복구도 실패 · ${monitorDiagTextError(rollbackError)}`);

  return {rolledBack};

}

function monitorStructureFinalizeDeskMoves(moveResult){

  for(const item of (Array.isArray(moveResult?.moves)?moveResult.moves:[]))delete monitorStructureDeskMembership[item.nodeKey];

}

async function monitorStructureSavePlacement(){
  const button=document.getElementById("monitorStructurePlacementSave"),status=document.getElementById("monitorStructureStatus");
  if(button?.disabled)return;
  let moveResult=null;
  if(button)button.disabled=true;
  if(status)status.textContent="위치 변경 확정 중 · 실제 Desk 위치만 적용…";
  try{
    moveResult=await monitorStructureExecuteDeskMoves();
    monitorStructureFinalizeDeskMoves(moveResult);
    await refreshMonitorRoleAdmin().catch(()=>{});
    await refreshAiMonitor().catch(()=>{});
    monitorStructureDirty=false;
    await monitorStructurePersistBaseline();
    await monitorStructurePersistWorkingDraft();
    monitorStructureHistoryReset();
    renderMonitorStructure();
    if(status)status.textContent=`위치 변경 확정 완료 · Desk ${Number(moveResult?.moved||0)}개 이동 · 현재 상태를 새 초기화 기준으로 지정`;
  }catch(error){
    let rollbackError=null;
    if(Number(moveResult?.moved||0)>0){try{await monitorStructureRollbackDeskMoves(moveResult);}catch(e){rollbackError=e;}}
    if(status)status.textContent=rollbackError?`위치 변경 확정 실패 · Desk 복구도 실패 · ${monitorDiagTextError(error)} / ${monitorDiagTextError(rollbackError)}`:`위치 변경 확정 실패 · Desk 위치를 원복함 · ${monitorDiagTextError(error)}`;
    if(rollbackError)throw rollbackError;
    throw error;
  }finally{if(button)button.disabled=false;}
}

async function monitorStructureSave(){

  const button=document.getElementById("monitorStructureSave"),status=document.getElementById("monitorStructureStatus");if(button?.disabled)return;let movedCount=0,moveResult=null,actSaved=false;

  if(button)button.disabled=true;if(status)status.textContent="실행 중 · 실제 Desk 이동 및 역할 확정…";

  try{moveResult=await monitorStructureExecuteDeskMoves();movedCount=Number(moveResult?.moved||0);const payload=monitorStructureBuildSavePayload();const r=await actFetch(ORCHESTRATOR_LAYOUT_SAVE_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const d=await r.json().catch(()=>null);if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);actSaved=true;monitorStructureApplyActHierarchy(d);monitorStructureFinalizeDeskMoves(moveResult);monitorStructureDirty=false;await monitorStructurePersistBaseline();await monitorStructurePersistWorkingDraft();await chrome.storage.local.remove(MONITOR_STRUCTURE_LEGACY_DRAFT_KEY);monitorStructureHistoryReset();await refreshMonitorRoleAdmin().catch(()=>{});await refreshAiMonitor().catch(()=>{});renderMonitorStructure();if(status)status.textContent=`실행 완료 · Desk ${movedCount}개 이동 · ${payload.assignments.length}개 노드 역할 확정`;}

  catch(error){let rollbackError=null;if(!actSaved&&Number(moveResult?.moved||0)>0){try{await monitorStructureRollbackDeskMoves(moveResult);}catch(e){rollbackError=e;}}if(status)status.textContent=rollbackError?`실행 실패 · Desk 자동 복구도 실패 · ${monitorDiagTextError(error)} / ${monitorDiagTextError(rollbackError)}`:`실행 실패${movedCount&&!actSaved?` · Desk ${movedCount}개 원위치 복구됨`:""} · ${monitorDiagTextError(error)}`;if(rollbackError)throw rollbackError;throw error;}

  finally{if(button)button.disabled=false;}

}

function monitorStructureConnectNodesByPosition(firstKey,secondKey){
  firstKey=String(firstKey||"");secondKey=String(secondKey||"");
  if(!firstKey||!secondKey||firstKey===secondKey)return false;
  const first=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(firstKey)}"]`);
  const second=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(secondKey)}"]`);
  if(!first||!second)return false;
  const firstY=first.getBoundingClientRect().top+first.getBoundingClientRect().height/2;
  const secondY=second.getBoundingClientRect().top+second.getBoundingClientRect().height/2;
  const parent=firstY<=secondY?firstKey:secondKey;
  const child=firstY<=secondY?secondKey:firstKey;
  void monitorStructureSetParent(child,parent);
  return true;
}

function monitorStructureRestoreExemptForDirectLink(nodeKey){
  nodeKey=String(nodeKey||"");if(!nodeKey)return true;
  const node=monitorStructureAvailableNodes().find(item=>String(item?.conversation_key||"")===nodeKey)||null;
  if(!node||!monitorStructureNodeIsPlacementExempt(node))return true;
  monitorStructurePlacementExemptions[nodeKey]=false;
  return true;
}

async function monitorStructureSetParent(child,parent){

  child=String(child||"");parent=String(parent||"");if(!child)return;
  const historyBefore=monitorStructureHistorySnapshot();
  monitorStructureRestoreExemptForDirectLink(child);
  if(parent)monitorStructureRestoreExemptForDirectLink(parent);
  const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());
  if(parent===child||monitorStructureWouldCycle(child,parent,parents)){
    monitorStructurePlacementExemptions=monitorStructureCloneDraftValue(historyBefore.placementExemptions)||{};
    return;
  }

  monitorStructureLinkOverrides[child]=parent||null;monitorStructureDirty=true;monitorStructureHistoryCommit(historyBefore);renderMonitorStructure();

  const status=document.getElementById("monitorStructureStatus");if(status)status.textContent="일반 노드로 연결됨 · 위치 변경 확정 전까지 조직도에만 적용";

}

function monitorStructureDrawLinks(layout){requestAnimationFrame(()=>{if(!monitorStructureOpen)return;const svg=document.getElementById("monitorStructureLinks");if(!svg)return;const svgRect=svg.getBoundingClientRect();svg.setAttribute("viewBox",`0 0 ${svgRect.width} ${svgRect.height}`);svg.replaceChildren();for(const [childKey,parentKey] of Object.entries(monitorStructureEffectiveParents(layout))){const child=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(childKey)}"]`),parent=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(parentKey)}"]`);if(!child||!parent)continue;const a=parent.getBoundingClientRect(),b=child.getBoundingClientRect();const commandPair=Boolean(parent.closest(".monitor-org-command-orchestrator")&&child.closest(".monitor-org-command-aux1,.monitor-org-command-aux2"));let d="";if(commandPair){const childIsLeft=(b.left+b.width/2)<(a.left+a.width/2);const parentX=(childIsLeft?a.left:a.right)-svgRect.left;const parentY=a.top+a.height/2-svgRect.top;const childX=(childIsLeft?b.right:b.left)-svgRect.left;const childY=b.top+b.height/2-svgRect.top;d=`M ${parentX} ${parentY} L ${childX} ${childY}`;}else{const x1=a.left+a.width/2-svgRect.left,y1=a.bottom-svgRect.top,x2=b.left+b.width/2-svgRect.left,y2=b.top-svgRect.top;d=`M ${x1} ${y1} L ${x2} ${y2}`;}const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",d);path.setAttribute("class","monitor-org-link");path.dataset.childKey=String(childKey);path.dataset.parentKey=String(parentKey);svg.append(path);}});}

function monitorStructureDrawLiveLink(clientX,clientY){const svg=document.getElementById("monitorStructureLinks");if(!svg||!monitorStructureRelationDragKey)return;svg.querySelector(".monitor-org-link-live")?.remove();const source=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(monitorStructureRelationDragKey)}"]`);if(!source)return;const svgRect=svg.getBoundingClientRect(),a=source.getBoundingClientRect(),x1=a.left+a.width/2-svgRect.left,y1=a.top+a.height/2-svgRect.top,x2=clientX-svgRect.left,y2=clientY-svgRect.top;const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",`M ${x1} ${y1} L ${x2} ${y2}`);path.setAttribute("class","monitor-org-link monitor-org-link-live");svg.append(path);}

function monitorStructureFitViewport(layout){
  const pyramid=monitorStructurePanel?.querySelector(".monitor-org-pyramid");
  const managers=document.getElementById("monitorStructureManagers");
  if(!pyramid||!managers)return;

  monitorStructurePanel.classList.remove("is-height-scaled");
  monitorStructurePanel.style.setProperty("--org-height-scale","1");
  requestAnimationFrame(()=>{
    if(!monitorStructureOpen||!pyramid.isConnected||!managers.isConnected)return;
    const availableHeight=Math.max(1,pyramid.clientHeight-2);
    const contentHeight=Math.ceil(managers.scrollHeight);
    // Fit the whole organization projection instead of reintroducing a panel scrollbar.
    const scale=Math.min(1,availableHeight/contentHeight);
    monitorStructurePanel.classList.toggle("is-height-scaled",scale<.995);
    monitorStructurePanel.style.setProperty("--org-height-scale",String(scale));
    monitorStructureDrawLinks(layout);
  });
}

function monitorStructureAlignLowerDesksToOrchestrator(){
  requestAnimationFrame(()=>{
    const root=monitorStructurePanel;if(!root||!monitorStructureOpen)return;
    const apex=root.querySelector('.monitor-org-command-orchestrator .monitor-org-socket');
    const desks=[...root.querySelectorAll('.monitor-org-desk.is-lower-desk')];
    if(!apex||!desks.length)return;
    for(const desk of desks)desk.style.transform='';
    const apexRect=apex.getBoundingClientRect();
    const rects=desks.map(desk=>desk.getBoundingClientRect());
    const rowCenter=(Math.min(...rects.map(rect=>rect.left))+Math.max(...rects.map(rect=>rect.right)))/2;
    const offset=Math.round((apexRect.left+apexRect.width/2)-rowCenter);
    for(const desk of desks)desk.style.transform=`translateX(${offset}px)`;
  });
}

function renderMonitorStructure(){
  const layout=monitorStructureAutoLayout();
  const managers=document.getElementById("monitorStructureManagers");
  if(!managers)return;
  managers.replaceChildren();

  const desktopEntries=Object.entries(layout.desktops||{}).sort((a,b)=>Number(a[1]?.index||0)-Number(b[1]?.index||0));
  const desktopCount=desktopEntries.length;
  const lowerDeskCount=Math.max(1,desktopCount-1);
  monitorStructurePanel.style.setProperty("--org-desk-count",String(Math.max(1,desktopCount)));
  monitorStructurePanel.style.setProperty("--org-lower-desk-count",String(lowerDeskCount));

  const orgDeskWidth=desktopCount<=3?360:desktopCount<=5?320:desktopCount<=7?280:240;
  monitorStructurePanel.style.setProperty("--org-desk-width",orgDeskWidth+"px");
  monitorStructurePanel.dataset.deskCount=String(desktopCount);

  const monitorWidth=Math.round(monitorRoot?.getBoundingClientRect?.().width||0);
  const lowerWidth=(lowerDeskCount*orgDeskWidth)+Math.max(0,lowerDeskCount-1)*8+20;
  const desiredWidth=Math.max(monitorWidth||0,lowerWidth,window.innerWidth-16,760);
  const maxWidth=Math.max(760,window.innerWidth-16);
  monitorStructurePanel.style.setProperty("width",Math.min(desiredWidth,maxWidth)+"px","important");
  monitorStructurePanel.style.right="8px";
  const compactLowerDesks=desktopCount>=7;
  const compactGap=10;
  const compactAvailableWidth=Math.max(320,maxWidth-52);
  const compactNaturalWidth=(lowerDeskCount*160)+Math.max(0,lowerDeskCount-1)*compactGap;
  const lowerScale=compactLowerDesks?Math.min(1,compactAvailableWidth/compactNaturalWidth):1;
  monitorStructurePanel.classList.toggle("is-density-scaled",compactLowerDesks);
  monitorStructurePanel.style.setProperty("--org-lower-scale",String(lowerScale));

  const panelTop=Math.round(monitorStructurePanel.getBoundingClientRect().top||72);
  const thumbRect=monitorDesktopSwitcher?.getBoundingClientRect?.();
  const thumbTop=thumbRect&&thumbRect.height>0?Math.round(thumbRect.top):window.innerHeight;
  const panelBottomLimit=Math.min(window.innerHeight-8,thumbTop-8);
  const maxPanelHeight=Math.max(180,panelBottomLimit-panelTop);
  monitorStructurePanel.style.setProperty("height",maxPanelHeight+"px","important");
  monitorStructurePanel.style.setProperty("max-height",maxPanelHeight+"px","important");

  for(const [desktopId,group] of desktopEntries){
    const wrap=document.createElement("section");
    const isOrchestratorDesk=Number(group?.index||0)===0;
    const onlyLowerDesk=!isOrchestratorDesk&&lowerDeskCount===1;
    wrap.className="monitor-org-socket-wrap monitor-org-manager-wrap monitor-org-desk"+(isOrchestratorDesk?" is-orchestrator-desk":onlyLowerDesk?" is-lower-desk is-single-lower-desk":" is-lower-desk");
    if(!isOrchestratorDesk)wrap.classList.add(group.manager?"has-manager":"has-no-manager");
    wrap.dataset.desktopId=desktopId;

    const deskNo=Number(group?.index||0)+1;
    wrap.setAttribute("role","group");
    wrap.setAttribute("aria-label","D"+deskNo+" 작업장");

    const head=document.createElement("div");
    head.className="monitor-org-desk-head";
    const deskId=document.createElement("span");
    deskId.className="monitor-org-desk-id";
    deskId.textContent="D"+deskNo;
    deskId.title="Desktop "+deskNo;
    head.append(deskId);
    wrap.append(head);

    if(isOrchestratorDesk){
      const body=document.createElement("div");
      body.className="monitor-org-orchestrator-body";
      const roleRow=document.createElement("div");
      roleRow.className="monitor-org-command-canvas";
      const commandSlots=[
        ["O","orchestrator",layout.orchestrator],
        ["C1","aux1",layout.aux1],
        ["C2","aux2",layout.aux2]
      ];
      for(const [label,slotName,roleNode] of commandSlots){
        const roleWrap=document.createElement("div");
        roleWrap.className="monitor-org-command-node monitor-org-command-"+slotName;
        const roleLabel=document.createElement("span");
        roleLabel.className="monitor-org-command-role";
        roleLabel.textContent=label;
        const roleSocket=document.createElement("div");
        roleSocket.className="monitor-org-socket";
        roleSocket.dataset.hierarchySlot=slotName;
        roleSocket.dataset.desktopId=desktopId;
        monitorStructureRenderSocket(roleSocket,roleNode);
        roleWrap.append(roleLabel,roleSocket);
        roleRow.append(roleWrap);
      }
      const extra=document.createElement("div");
      extra.className="monitor-org-orchestrator-extra";
      const workers=monitorStructureDeskNodeGrid(group.workers||[],desktopId);
      if(workers.childElementCount)extra.append(workers);
      if(extra.childElementCount){
        const balance=document.createElement("div");
        balance.className="monitor-org-orchestrator-balance";
        body.classList.add("has-extra");
        body.append(balance,roleRow,extra);
      }else body.append(roleRow);

      wrap.append(body);
    }else{
      const managerRow=document.createElement("div");
      managerRow.className="monitor-org-manager-row";
      const managerCaption=document.createElement("span");
      managerCaption.className="monitor-org-manager-caption monitor-org-command-role";
      managerCaption.textContent="M";
      const socket=document.createElement("div");
      socket.className="monitor-org-socket monitor-org-manager-socket";
      socket.dataset.hierarchySlot="manager";
      socket.dataset.desktopId=desktopId;
      monitorStructureRenderSocket(socket,group.manager||null);
      const managerBundle=Object.entries(monitorStructureManagerBundleDesk).find(([,desk])=>String(desk)===String(desktopId));
      if(!group.manager&&managerBundle){socket.replaceChildren(monitorStructureBundleCard(managerBundle[0]));}
      socket.append(managerCaption);
      managerRow.append(socket);
      wrap.append(managerRow);

      const workers=monitorStructureDeskNodeGrid(group.workers||[],desktopId);
      if(workers.childElementCount)wrap.append(workers);
      if(!group.manager&&!workers.childElementCount)wrap.classList.add("is-empty");
    }

    managers.append(wrap);
  }

  monitorStructureRenderResourcePools();
  monitorStructurePanel.querySelector(".monitor-org-bundle-palette")?.remove();

  document.getElementById("monitorStructureLinkMode")?.classList.toggle("is-active",monitorStructureLinkMode);
  if(monitorStructureLinkSourceKey){
    monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(monitorStructureLinkSourceKey)}"]`)?.classList.add("monitor-org-link-source");
  }
  monitorStructureFitViewport(layout);
  monitorStructureAlignLowerDesksToOrchestrator();
}
function monitorStructureDropNode(slot,node,desktopId=""){
  if(!node?.conversation_key)return false;
  if(!["orchestrator","aux1","aux2","manager"].includes(slot)||(slot==="manager"&&!desktopId))return false;
  const historyBefore=monitorStructureHistorySnapshot();
  const key=String(node.conversation_key);monitorStructureRemoveNode(key);
  if(slot==="orchestrator")monitorStructureSocketDraft.orchestrator=node;
  else if(slot==="aux1")monitorStructureSocketDraft.aux1=node;
  else if(slot==="aux2")monitorStructureSocketDraft.aux2=node;
  else {monitorStructureSocketDraft.managers=monitorStructureSocketDraft.managers||{};monitorStructureSocketDraft.managers[desktopId]=node;monitorStructureDeskMembership[key]=desktopId;}
  monitorStructureDirty=true;
  monitorStructureHistoryCommit(historyBefore);
  renderMonitorStructure();
  const status=document.getElementById("monitorStructureStatus");
  if(status)status.textContent="배치 변경됨 · 위치 변경 확정 또는 실행으로 실제 Desk 위치를 적용하세요";
  return true;
}

function monitorHierarchyTargetAt(x,y){return document.elementsFromPoint(x,y).find(el=>el?.dataset?.hierarchySlot||el?.dataset?.orgDeskDrop)||null;}

function clearMonitorHierarchyTargets(){for(const el of monitorStructurePanel.querySelectorAll("[data-hierarchy-slot]"))el.classList.remove("monitor-org-socket-target");}

async function monitorHierarchyApplyDrop(target,hwnd){const node=monitorStructureNodeForHwnd(hwnd);if(!node)throw new Error("웹 노드를 찾지 못함");const desktopId=String(target?.dataset?.desktopId||"");if(target?.dataset?.orgDeskDrop&&desktopId)return monitorStructureMoveNodeToDesk(String(node.conversation_key||""),desktopId);return monitorStructureDropNode(String(target?.dataset?.hierarchySlot||""),node,desktopId);}

async function openMonitorStructure(){

  monitorStructureOpen=true;monitorStructurePanel.hidden=false;if(monitorLastAiState)renderWorkers(monitorLastAiState);
  monitorStructureHistoryReset();

  chrome.storage.local.get([MONITOR_STRUCTURE_BASELINE_KEY,MONITOR_STRUCTURE_WORKING_DRAFT_KEY,MONITOR_STRUCTURE_NODE_CONTROL_KEY],async data=>{

    const storedBaseline=data?.[MONITOR_STRUCTURE_BASELINE_KEY];
    const storedWorking=data?.[MONITOR_STRUCTURE_WORKING_DRAFT_KEY];
    const controls=data?.[MONITOR_STRUCTURE_NODE_CONTROL_KEY];monitorStructureNodeControls=controls&&typeof controls==="object"?controls:{};

    let authorityOk=false;
    try{await monitorStructureRefreshAuthority();monitorStructureAuthorityLoaded=true;authorityOk=true;}
    catch(_){monitorStructureAuthorityLoaded=false;}

    const baseline=monitorStructureReconcileSnapshot(storedBaseline);
    const working=monitorStructureReconcileSnapshot(storedWorking);
    monitorStructureBaseline=baseline?monitorStructureCloneDraftValue(baseline):null;

    if(working){
      monitorStructureApplyHistorySnapshot(working);
      monitorStructureHistoryReset();
      const status=document.getElementById("monitorStructureStatus");
      if(status)status.textContent=authorityOk?"마지막 작업 상태 복원":"마지막 작업 상태 복원 · ACT 구조 조회 실패";
      return;
    }

    if(baseline){
      monitorStructureApplyBaseline();
      monitorStructureHistoryReset();
      await monitorStructurePersistWorkingDraft();
      const status=document.getElementById("monitorStructureStatus");
      if(status)status.textContent=authorityOk?"마지막 확정 기준 상태 복원":"마지막 확정 기준 상태 복원 · ACT 구조 조회 실패";
      return;
    }

    monitorStructureRunAutoLayout();
    monitorStructureDirty=false;
    await monitorStructurePersistBaseline();
    await monitorStructurePersistWorkingDraft();
    monitorStructureHistoryReset();
    renderMonitorStructure();
    const status=document.getElementById("monitorStructureStatus");
    if(status)status.textContent=authorityOk?"현재 실제 Desk 기준 자동배치 · 최초 기준 상태 지정":"현재 실제 Desk 기준 자동배치 · 최초 기준 상태 지정 · ACT 구조 조회 실패";

  });

}

function closeMonitorStructure(){void monitorStructurePersistWorkingDraft();monitorStructureOpen=false;monitorStructurePanel.hidden=true;if(monitorLastAiState)renderWorkers(monitorLastAiState);}

function monitorDiagTextError(error){return String(error?.message||error||'unknown').slice(0,180);}

async function refreshMonitorAutoProcess(){

  try{const r=await actFetch(ORCHESTRATOR_AUTO_PROCESS_URL,{cache:'no-store'});const d=await r.json();if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);monitorAutoProcessEnabled=Boolean(d.enabled);monitorStructureActiveScopeKey=String(d.active_scope_key||"GLOBAL");monitorAutoProcessQuick.textContent=`AUTO: ${monitorAutoProcessEnabled?'ON':'OFF'}`;monitorAutoProcessQuick.title=`자동 처리 ${monitorAutoProcessEnabled?'ON':'OFF'} · 적용 구조: ${monitorStructureActiveScopeKey} · 클릭하여 ${monitorAutoProcessEnabled?'OFF':'ON'}`;monitorAutoProcessQuick.classList.toggle('is-on',monitorAutoProcessEnabled);monitorAutoProcessQuick.classList.toggle('is-off',!monitorAutoProcessEnabled);monitorAutoProcessQuick.classList.remove('is-unknown','is-error');}

  catch(e){monitorAutoProcessQuick.textContent='AUTO: ?';monitorAutoProcessQuick.title=monitorDiagTextError(e);monitorAutoProcessQuick.classList.remove('is-on','is-off');monitorAutoProcessQuick.classList.add('is-error');}

}

async function toggleMonitorAutoProcess(){

  const next=!monitorAutoProcessEnabled;

  const r=await actFetch(ORCHESTRATOR_AUTO_PROCESS_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:next,scope_key:monitorStructureActiveScopeKey})});

  const d=await r.json();if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);monitorAutoProcessEnabled=Boolean(d.enabled);await refreshMonitorAutoProcess();showMonitorDiagText(`자동 처리: ${monitorAutoProcessEnabled?'ON · 새 결과를 감지하면 ORCHESTRATOR에 확인해 처리해 전송':'OFF · 결과는 ACT에만 보관'}`,false);

}

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

function showMonitorDiagText(text){monitorDiagLog.textContent=String(text||'');monitorDiagLog.hidden=false;monitorDiagLogCopyState.textContent='';}
async function refreshMonitorCurrentDiagnosticView() {
  const button = document.getElementById("monitorDiagRefresh");
  const viewFeature = globalThis.MonitorDiagnosticsViewFeature.create({
    button,
    getActiveView: () => {
      const selected = monitorDiagnostics.querySelector("[data-monitor-diag-view].is-active");
      return { view: selected?.dataset?.monitorDiagView, label: selected?.textContent };
    },
    ports: {
      refreshOverview: () => Promise.allSettled([refreshMonitorActDiagnostic(), refreshMonitorAutoProcess()]),
      refreshAct: () => refreshMonitorActDiagnostic(),
      actStatus: () => monitorDiagAct.textContent,
      autoStatus: () => monitorAutoProcessQuick.textContent,
      renderMonitor: () => monitorRenderDiagnosticText(),
      show: text => showMonitorDiagText(text)
    }
  });
  return viewFeature.refresh();
}

document.getElementById('monitorDiagRefresh').addEventListener('click',()=>refreshMonitorCurrentDiagnosticView().catch(e=>showMonitorDiagText(`관제 새로고침 실패: ${monitorDiagTextError(e)}`)));

monitorDiagToggle?.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();monitorDiagnostics.open=!monitorDiagnostics.open;});
monitorDiagnostics.addEventListener('toggle',()=>{if(monitorDiagToggle){monitorDiagToggle.textContent=monitorDiagnostics.open?'접기':'펼치기';monitorDiagToggle.setAttribute('aria-label',monitorDiagnostics.open?'진단 상세 화면 접기':'진단 상세 화면 펼치기');}if(monitorDiagnostics.open){void refreshMonitorActDiagnostic();void refreshMonitorAutoProcess();}});
for(const button of monitorDiagnostics.querySelectorAll('[data-monitor-diag-view]')){
  button.addEventListener('click',async()=>{
    for(const peer of monitorDiagnostics.querySelectorAll('[data-monitor-diag-view]'))peer.classList.toggle('is-active',peer===button);
    const view=String(button.dataset.monitorDiagView||'overview');
    const label=String(button.textContent||view);
    if(view==='overview'){
      showMonitorDiagText(`종합 관제\n${monitorDiagAct.textContent} · ${monitorAutoProcessQuick.textContent}\n오른쪽 위 새로고침 아이콘은 현재 선택한 관제 정보만 다시 확인합니다.`);
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
  });
}

monitorStructureQuick.addEventListener("click",()=>{if(monitorStructureOpen)closeMonitorStructure();else void openMonitorStructure();});

document.getElementById("monitorStructureClose").addEventListener("click",closeMonitorStructure);

document.getElementById("monitorStructureSave").addEventListener("click",()=>{void monitorStructureSave().catch(()=>{});});
document.getElementById("monitorStructurePlacementSave").addEventListener("click",()=>{void monitorStructureSavePlacement().catch(()=>{});});
document.getElementById("monitorStructureUndo").addEventListener("click",monitorStructureUndoAction);
document.getElementById("monitorStructureRedo").addEventListener("click",monitorStructureRedoAction);

document.getElementById("monitorStructureAutoLayout").addEventListener("click",monitorStructureRunAutoLayout);

document.getElementById("monitorStructureLinkMode")?.addEventListener("click",()=>{if(!MONITOR_STRUCTURE_CONNECTIONS_ENABLED)return;monitorStructureLinkMode=!monitorStructureLinkMode;monitorStructureLinkSourceKey="";const button=document.getElementById("monitorStructureLinkMode");button?.classList.toggle("is-active",monitorStructureLinkMode);const status=document.getElementById("monitorStructureStatus");if(status)status.textContent=monitorStructureLinkMode?"선 연결 · 상위/하위 노드를 차례로 선택하세요":"선 연결 종료 · 노드 클릭은 AUTO 설정";renderMonitorStructure();});

monitorStructurePanel.addEventListener("click",event=>{

  if(Date.now()<monitorStructureSuppressNodeClickUntil)return;

  const card=event.target?.closest?.(".monitor-org-node-card[data-control-node='1'][data-node-key]");if(!card)return;
  if(monitorStructureLinkMode){const key=String(card.dataset.nodeKey||"");if(!key)return;if(!monitorStructureLinkSourceKey){monitorStructureLinkSourceKey=key;card.classList.add("monitor-org-link-source");const status=document.getElementById("monitorStructureStatus");if(status)status.textContent="선 연결 · 두 번째 노드를 선택하세요";return;}if(key===monitorStructureLinkSourceKey){monitorStructureLinkSourceKey="";card.classList.remove("monitor-org-link-source");return;}const sourceKey=monitorStructureLinkSourceKey;monitorStructureLinkSourceKey="";monitorStructureLinkMode=false;document.getElementById("monitorStructureLinkMode")?.classList.remove("is-active");monitorStructureConnectNodesByPosition(sourceKey,key);return;}

  void monitorStructureToggleNodeControl(String(card.dataset.nodeKey||"")).catch(error=>{const status=document.getElementById("monitorStructureStatus");if(status)status.textContent=`AUTO 변경 실패 · ${monitorDiagTextError(error)}`;});

});

function monitorStructureClearDragFeedback(removeGhost=true){if(removeGhost){monitorStructurePointerGhost?.remove();monitorStructurePointerGhost=null;}for(const el of monitorStructurePanel.querySelectorAll(".is-desk-drop,.is-socket-drop,.monitor-org-link-target,.monitor-org-link-dragging"))el.classList.remove("is-desk-drop","is-socket-drop","monitor-org-link-target","monitor-org-link-dragging");}

function monitorStructureUpdateDragGhost(nodeKey,clientX,clientY){if(!monitorStructurePointerGhost){const source=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(nodeKey)}"]`);if(!source)return;monitorStructurePointerGhost=createMonitorNodeDragGhost(source);monitorStructurePointerGhost.classList.add("monitor-org-drag-ghost");}moveMonitorNodeDragGhost(monitorStructurePointerGhost,clientX,clientY);}

function monitorStructurePointerTargetAt(x,y,sourceKey){const elements=document.elementsFromPoint(x,y);const node=elements.map(el=>el?.closest?.(".monitor-org-node-card[data-node-key]")).find(el=>el&&String(el.dataset.nodeKey||"")!==sourceKey)||null;if(node)return {kind:"node",element:node};const socket=elements.map(el=>el?.closest?.(".monitor-org-socket[data-hierarchy-slot]")).find(el=>el&&!el.querySelector(".monitor-org-node-card[data-node-key]"))||null;if(socket)return {kind:"socket",element:socket};const desk=monitorStructureSlotAtPoint(x,y);if(desk)return {kind:"desk",element:desk};const canvas=elements.map(el=>el?.closest?.(".monitor-org-pyramid")).find(Boolean)||null;return canvas?{kind:"blank",element:canvas}:null;}

monitorStructurePanel.addEventListener("pointerdown",event=>{

  if(monitorStructureLinkMode)return;
  const mover=event.target?.closest?.('.monitor-org-node-card[data-org-move-node="1"][data-node-key]');

  if(!mover||event.button!==0)return;

  const key=String(mover.dataset.nodeKey||"");if(!key)return;

  if(!MONITOR_STRUCTURE_CONNECTIONS_ENABLED&&mover.closest?.(".monitor-org-manager-socket")){

    const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());

    const linked=Boolean(parents[key]||Object.values(parents).some(parent=>String(parent||"")===key));

    if(linked){const status=document.getElementById("monitorStructureStatus");if(status)status.textContent="Manager 이동 불가 · 먼저 빈 공간에 놓아 관리선을 끊어주세요";return;}

  }

  monitorStructureNodePointer={nodeKey:key,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,moved:false};

  try{monitorStructurePanel.setPointerCapture(event.pointerId);}catch(_){}

  event.preventDefault();event.stopPropagation();

});

function monitorStructureSlotAtPoint(x,y){

  const selector='.monitor-org-node-slot[data-desktop-id]';

  const layered=document.elementsFromPoint(x,y).map(el=>el?.closest?.(selector)).find(Boolean)||null;

  if(layered)return layered;

  for(const desk of monitorStructurePanel.querySelectorAll(selector)){

    const r=desk.getBoundingClientRect();

    if(x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom)return desk;

  }

  return null;

}

monitorStructurePanel.addEventListener("pointermove",event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  if(!state.moved&&Math.hypot(event.clientX-state.startX,event.clientY-state.startY)>=7)state.moved=true;

  if(!state.moved)return;

  monitorStructureClearDragFeedback(false);monitorStructureUpdateDragGhost(state.nodeKey,event.clientX,event.clientY);monitorStructureRelationDragKey=state.nodeKey;monitorStructureDrawLiveLink(event.clientX,event.clientY);

  const target=monitorStructurePointerTargetAt(event.clientX,event.clientY,state.nodeKey);

  if(target?.kind==="desk")target.element.classList.add("is-desk-drop");else if(target?.kind==="socket")target.element.classList.add("is-socket-drop");else if(target?.kind==="node")target.element.classList.add("monitor-org-link-target");

  event.preventDefault();event.stopPropagation();

});

const monitorStructureFinishNodePointer=event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  const nodeKey=state.nodeKey,moved=state.moved;

  const target=moved?monitorStructurePointerTargetAt(event.clientX,event.clientY,nodeKey):null;

  monitorStructureNodePointer={nodeKey:"",pointerId:null,startX:0,startY:0,moved:false};

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  monitorStructureClearDragFeedback();monitorStructureRelationDragKey="";

  if(!moved)return;

  monitorStructureSuppressNodeClickUntil=Date.now()+500;

  if(target?.kind==="desk"){const desktopId=String(target.element.dataset.desktopId||"");if(desktopId)monitorStructureMoveNodeToDesk(nodeKey,desktopId);}else if(target?.kind==="socket"){const node=monitorStructureAvailableNodes().find(item=>String(item.conversation_key||"")===nodeKey)||null;const slot=String(target.element.dataset.hierarchySlot||""),desktopId=String(target.element.dataset.desktopId||"");if(node&&slot)monitorStructureDropNode(slot,node,desktopId);}else if(target?.kind==="node"){monitorStructureConnectNodesByPosition(nodeKey,String(target.element.dataset.nodeKey||""));}else if(target?.kind==="blank"){monitorStructureDetachBlankStep(nodeKey);}else monitorStructureDrawLinks(monitorStructureAutoLayout());

  event.preventDefault();event.stopPropagation();

};

monitorStructurePanel.addEventListener("pointerup",monitorStructureFinishNodePointer);

monitorStructurePanel.addEventListener("pointercancel",event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  monitorStructureNodePointer={nodeKey:"",pointerId:null,startX:0,startY:0,moved:false};

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  monitorStructureRelationDragKey="";monitorStructureClearDragFeedback();monitorStructureDrawLinks(monitorStructureAutoLayout());

});

monitorStructurePanel.addEventListener("pointerdown",event=>{

  const path=event.target?.closest?.(".monitor-org-link[data-child-key]");if(!path||path.classList.contains("monitor-org-link-live"))return;

  const child=String(path.dataset.childKey||"");if(!child)return;

  monitorStructureEdgePointer={child,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,moved:false};monitorStructureRelationDragKey=child;path.classList.add("is-edge-dragging");

  try{monitorStructurePanel.setPointerCapture(event.pointerId);}catch(_){}event.preventDefault();event.stopPropagation();

});

monitorStructurePanel.addEventListener("pointermove",event=>{

  const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;

  if(!state.moved&&Math.hypot(event.clientX-state.startX,event.clientY-state.startY)>=7)state.moved=true;

  if(state.moved)monitorStructureDrawLiveLink(event.clientX,event.clientY);

});

const monitorStructureFinishEdgePointer=event=>{

  const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;

  const child=state.child,moved=state.moved;monitorStructureEdgePointer={child:"",pointerId:null,startX:0,startY:0,moved:false};monitorStructureRelationDragKey="";

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-link.is-edge-dragging"))el.classList.remove("is-edge-dragging");

  if(!moved){monitorStructureDrawLinks(monitorStructureAutoLayout());return;}

  const target=document.elementsFromPoint(event.clientX,event.clientY).find(el=>el?.closest?.(".monitor-org-node-card[data-node-key]"))?.closest?.(".monitor-org-node-card[data-node-key]")||null;

  const parent=target&&String(target.dataset.nodeKey||"")!==child?String(target.dataset.nodeKey||""):"";

  void monitorStructureSetParent(child,parent);

};

monitorStructurePanel.addEventListener("pointerup",monitorStructureFinishEdgePointer);

monitorStructurePanel.addEventListener("pointercancel",event=>{const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;monitorStructureEdgePointer={child:"",pointerId:null,startX:0,startY:0,moved:false};monitorStructureRelationDragKey="";monitorStructureDrawLinks(monitorStructureAutoLayout());});

monitorStructurePanel.addEventListener("dragstart",event=>{

  const bundle=event.target?.closest?.(".monitor-org-bundle[data-bundle-kind]");if(bundle){monitorStructureUseNodeDragGhost(event);event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("application/x-dwm-org-bundle",String(bundle.dataset.bundleKind||""));return;}

  const mover=event.target?.closest?.('.monitor-org-node-card[data-org-move-node="1"]');if(mover){monitorStructureUseNodeDragGhost(event);const key=String(mover.dataset.nodeKey||"");const inManager=Boolean(mover.closest?.(".monitor-org-manager-socket"));if(inManager){const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());const linked=Boolean(parents[key]||Object.values(parents).some(parent=>String(parent||"")===key));if(linked)event.dataTransfer.setData("application/x-dwm-org-manager-linked","1");}event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("application/x-dwm-org-node",key);return;}

  const resource=event.target?.closest?.(".monitor-org-resource-card[data-resource-id]");if(resource){monitorStructureResourceDragId=String(resource.dataset.resourceId||"");resource.classList.add("is-dragging");event.dataTransfer.effectAllowed="link";event.dataTransfer.setData("application/x-dwm-llm-resource",monitorStructureResourceDragId);return;}

  const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");if(!card)return;

  monitorStructureRelationDragKey=String(card.dataset.nodeKey||"");event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("text/plain",monitorStructureRelationDragKey);card.classList.add("monitor-org-link-dragging");

  requestAnimationFrame(()=>monitorStructureDrawLiveLink(event.clientX,event.clientY));

});

monitorStructurePanel.addEventListener("dragover",event=>{

  const types=[...(event.dataTransfer?.types||[])];const carriesNode=types.includes("application/x-dwm-org-node")||types.includes("application/x-dwm-structure-node");const carriesBundle=types.includes("application/x-dwm-org-bundle");const socket=event.target?.closest?.('.monitor-org-socket[data-hierarchy-slot][data-desktop-id]');const emptySocket=socket?.matches?.(':not(:has(.monitor-org-node-card[data-node-key]))')?socket:null;if(socket&&carriesBundle){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);socket.classList.add("is-socket-drop");return;}if(emptySocket&&carriesNode){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);emptySocket.classList.add("is-socket-drop");return;}
  const desk=event.target?.closest?.('.monitor-org-node-slot[data-desktop-id]');const linkedManager=types.includes("application/x-dwm-org-manager-linked");if(desk&&(carriesNode||types.includes("application/x-dwm-org-bundle"))){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);if(!linkedManager)desk.classList.add("is-desk-drop");return;}

  if(monitorStructureResourceDragId){const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");const supervisors=monitorStructureSupervisorKeys(monitorStructureAutoLayout());if(card&&supervisors.has(String(card.dataset.nodeKey||""))){event.preventDefault();event.dataTransfer.dropEffect="link";card.classList.add("monitor-org-link-target");}return;}

  if(!monitorStructureRelationDragKey)return;event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureDrawLiveLink(event.clientX,event.clientY);

  const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");

  for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-link-target"))el.classList.remove("monitor-org-link-target");

  if(card&&card.dataset.nodeKey!==monitorStructureRelationDragKey)card.classList.add("monitor-org-link-target");

});

monitorStructurePanel.addEventListener("drop",event=>{

  const socket=event.target?.closest?.('.monitor-org-socket[data-hierarchy-slot][data-desktop-id]');const kind=String(event.dataTransfer?.getData("application/x-dwm-org-bundle")||"");if(socket&&monitorStructureBundleOrder().includes(kind)){event.preventDefault();monitorStructureClearDragFeedback();monitorStructureMoveBundleToDesk(kind,String(socket.dataset.desktopId||""),String(socket.dataset.hierarchySlot||"")==="manager");return;}const emptySocket=socket?.matches?.(':not(:has(.monitor-org-node-card[data-node-key]))')?socket:null;if(emptySocket){const nodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");const raw=String(event.dataTransfer?.getData("application/x-dwm-structure-node")||"");let node=nodeKey?monitorStructureAvailableNodes().find(item=>String(item.conversation_key||"")===nodeKey)||null:null;if(!node&&raw){try{node=JSON.parse(raw);}catch(_){}}if(node?.conversation_key){event.preventDefault();monitorStructureClearDragFeedback();monitorStructureDropNode(String(emptySocket.dataset.hierarchySlot||""),node,String(emptySocket.dataset.desktopId||""));return;}}
  const desk=event.target?.closest?.('.monitor-org-node-slot[data-desktop-id]');if(desk){const desktopId=String(desk.dataset.desktopId||"");const nodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");const linkedManager=String(event.dataTransfer?.getData("application/x-dwm-org-manager-linked")||"")==="1";const kind=String(event.dataTransfer?.getData("application/x-dwm-org-bundle")||"");const raw=String(event.dataTransfer?.getData("application/x-dwm-structure-node")||"");if(nodeKey&&linkedManager){event.preventDefault();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="Manager 이동 불가 · 먼저 연결을 해제하세요";return;}if(nodeKey){event.preventDefault();monitorStructureMoveNodeToDesk(nodeKey,desktopId);return;}if(kind){event.preventDefault();monitorStructureMoveBundleToDesk(kind,desktopId);return;}if(raw){try{const node=JSON.parse(raw);if(node?.conversation_key){event.preventDefault();monitorStructureMoveNodeToDesk(String(node.conversation_key),desktopId);return;}}catch(_){}}}

  const blankNodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");if(blankNodeKey){event.preventDefault();monitorStructureDetachBlankStep(blankNodeKey);return;}

  if(monitorStructureResourceDragId){event.preventDefault();const target=event.target?.closest?.(".monitor-org-node-card[data-node-key]");const supervisors=monitorStructureSupervisorKeys(monitorStructureAutoLayout());if(target&&supervisors.has(String(target.dataset.nodeKey||"")))monitorStructureToggleResourceEdge(String(target.dataset.nodeKey||""),monitorStructureResourceDragId);monitorStructureResourceDragId="";return;}

  if(!monitorStructureRelationDragKey)return;event.preventDefault();

  const child=monitorStructureRelationDragKey,target=event.target?.closest?.(".monitor-org-node-card[data-node-key]");

  if(target&&target.dataset.nodeKey!==child)void monitorStructureSetParent(child,String(target.dataset.nodeKey||""));else monitorStructureDetachBlankStep(child);monitorStructureRelationDragKey="";

});

monitorStructurePanel.addEventListener("dragend",()=>{monitorStructureClearDragFeedback();monitorStructureRelationDragKey="";monitorStructureResourceDragId="";for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-resource-card.is-dragging"))el.classList.remove("is-dragging");monitorStructureDrawLinks(monitorStructureAutoLayout());});

document.getElementById("monitorStructureClear").addEventListener("click",()=>{void monitorStructureResetDraft();});

monitorAutoProcessQuick.addEventListener('click',()=>toggleMonitorAutoProcess().catch(e=>showMonitorDiagText(`자동 처리 변경 실패: ${monitorDiagTextError(e)}`,false)));

document.getElementById('monitorDiagLogCopy').addEventListener('click',async()=>{const text=String(monitorDiagLog.textContent||'');try{await navigator.clipboard.writeText(text);monitorDiagLogCopyState.textContent='복사됨';}catch(_){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.append(ta);ta.select();document.execCommand('copy');ta.remove();monitorDiagLogCopyState.textContent='복사됨';}setTimeout(()=>{monitorDiagLogCopyState.textContent='';},1600);});

refreshMonitorAutoProcess();

/* HIERARCHY_DISABLED_FOR_STABILITY */
