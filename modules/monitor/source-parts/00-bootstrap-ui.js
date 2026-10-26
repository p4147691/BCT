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

/*@@MONITOR_FUNCTION:monitorExtensionVersion@@*/

/*@@MONITOR_FUNCTION:monitorWindowTitle@@*/

/*@@MONITOR_FUNCTION:monitorIsOwnWindowTitle@@*/

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

/*@@MONITOR_FUNCTION:monitorRecordRefreshTiming@@*/

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
/*@@MONITOR_FUNCTION:syncMonitorPanelToDesktopSwitcher@@*/
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

/*@@MONITOR_FUNCTION:syncMonitorTitle@@*/

syncMonitorTitle();

const monitorTitleResizeObserver = new ResizeObserver(syncMonitorTitle);

monitorTitleResizeObserver.observe(monitorRoot);

requestAnimationFrame(syncMonitorTitle);

/* Recovery owns deleted-note storage; Notes receives it through one callback. */
/*@@MONITOR_FUNCTION:persistMonitorTrashedNotes@@*/

/*@@MONITOR_FUNCTION:trashMonitorNote@@*/

/*@@MONITOR_FUNCTION:restoreMonitorTrashedNote@@*/

/*@@MONITOR_FUNCTION:deleteMonitorTrashedNote@@*/

/*@@MONITOR_FUNCTION:clearMonitorTrashedNotes@@*/

/* Composition only: place Notes, then place Sketch to its left. */
/*@@MONITOR_FUNCTION:syncMonitorSideNote@@*/

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

/*@@MONITOR_FUNCTION:monitorDesktopScrollStep@@*/
