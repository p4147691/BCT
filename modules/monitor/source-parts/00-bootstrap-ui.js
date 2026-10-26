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
const MONITOR_FEATURE_SKETCH_ENABLED = true;
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

const monitorNote = document.createElement("aside");

monitorNote.className = "monitor-side-note";

monitorNote.setAttribute("aria-label", "할 일 메모");

monitorNote.innerHTML = `<div class="monitor-side-note-title"><span class="monitor-note-title-left"><button id="monitorNoteBack" type="button" title="메모 목록" aria-label="메모 목록" hidden>‹</button><span id="monitorNoteHeaderTitle">메모</span><button id="monitorNoteAdd" type="button" title="새 메모" aria-label="새 메모">＋</button></span><span class="monitor-note-actions"><button id="monitorNoteUndo" type="button" title="실행 취소 (Ctrl+Z)" aria-label="실행 취소" hidden>↶</button><button id="monitorNoteRedo" type="button" title="다시 실행 (Ctrl+Y / Ctrl+Shift+Z)" aria-label="다시 실행" hidden>↷</button><button id="monitorNoteAi" type="button" title="작업하지 않는 유휴 워커로 메모 정리" aria-label="AI로 메모 정리" hidden>AI</button><button id="monitorNoteDelete" type="button" title="현재 메모 삭제" aria-label="현재 메모 삭제" hidden>×</button><button id="monitorNoteCollapse" type="button" title="메모 접기" aria-label="메모 접기">−</button></span></div><div id="monitorNoteList" class="monitor-note-list"></div><div id="monitorNoteEditor" class="monitor-note-editor" hidden><textarea id="monitorSideNoteText" spellcheck="false" placeholder="첫 줄이 목록 제목으로 표시됩니다.\n해야 할 일..."></textarea></div>`;

const MONITOR_NOTE_BUNDLE_PREFIX = "DWM_NOTES_V1:";

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

const monitorSketchpad = document.createElement("aside");
monitorSketchpad.className = "monitor-sketchpad";
monitorSketchpad.setAttribute("aria-label", "간단 그림판");
monitorSketchpad.innerHTML = `<div class="monitor-sketch-title"><span>그림</span><button id="monitorSketchCollapse" type="button" class="monitor-sketch-icon-btn monitor-sketch-collapse" title="그림판 접기" aria-label="그림판 접기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg></button></div><div class="monitor-sketch-tools" role="toolbar" aria-label="그림판 도구"><div class="monitor-sketch-tool-row"><button id="monitorSketchPen" type="button" class="monitor-sketch-icon-btn active" title="펜" aria-label="펜"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4.5-1 10-10-3.5-3.5-10 10L4 20zM13.8 6.7l3.5 3.5"/></svg></button><button id="monitorSketchEraser" type="button" class="monitor-sketch-icon-btn" title="지우개" aria-label="지우개"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17l-3-3 8.5-8.5a2 2 0 012.8 0l3.2 3.2a2 2 0 010 2.8L12 18H8l-1-1zM10 18h10"/></svg></button><button id="monitorSketchLine" type="button" class="monitor-sketch-icon-btn" title="직선" aria-label="직선"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19L19 5"/></svg></button><button id="monitorSketchRect" type="button" class="monitor-sketch-icon-btn" title="사각형" aria-label="사각형"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="6" width="14" height="12" rx="1"/></svg></button></div><div class="monitor-sketch-tool-row monitor-sketch-history-row"><button id="monitorSketchText" type="button" class="monitor-sketch-icon-btn" title="글자 · 길게 눌러 크기 선택" aria-label="글자" aria-haspopup="menu" aria-expanded="false"><span class="monitor-sketch-text-tool-label">가</span></button><button id="monitorSketchUndo" type="button" class="monitor-sketch-icon-btn" title="되돌리기" aria-label="되돌리기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7L4 12l5 5M5 12h8a6 6 0 016 6"/></svg></button><button id="monitorSketchRedo" type="button" class="monitor-sketch-icon-btn" title="다시하기" aria-label="다시하기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 7l5 5-5 5M19 12h-8a6 6 0 00-6 6"/></svg></button><button id="monitorSketchClear" type="button" class="monitor-sketch-icon-btn monitor-sketch-danger" title="전체 지우기" aria-label="전체 지우기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 10v8M12 10v8M16 10v8M7 7l1 13h8l1-13"/></svg></button></div><div id="monitorSketchTextSizeMenu" class="monitor-sketch-text-size-menu" role="menu" aria-label="글자 크기" hidden><button id="monitorSketchTextSmall" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn" role="menuitem" title="작은 글자" aria-label="작은 글자"><span class="monitor-sketch-text-size-label small">가</span></button><button id="monitorSketchTextMedium" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn active" role="menuitem" title="보통 글자" aria-label="보통 글자"><span class="monitor-sketch-text-size-label medium">가</span></button><button id="monitorSketchTextLarge" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn" role="menuitem" title="큰 글자" aria-label="큰 글자"><span class="monitor-sketch-text-size-label large">가</span></button></div></div><div class="monitor-sketch-canvas-wrap"><canvas id="monitorSketchCanvas" width="900" height="1200" aria-label="자유 낙서 영역"></canvas><canvas id="monitorSketchOverlay" width="900" height="1200" aria-hidden="true"></canvas><div id="monitorSketchCursor" class="monitor-sketch-cursor pen" aria-hidden="true"></div><input id="monitorSketchTextInput" class="monitor-sketch-text-input" type="text" maxlength="120" autocomplete="off" spellcheck="false" aria-label="그림판 글자 입력" hidden></div>`;
document.body.append(monitorDesktopSwitcher, monitorSketchpad, monitorNote, monitorRoot);
if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED && !MONITOR_FEATURE_RECOVERY_ENABLED) monitorDesktopSwitcher.style.setProperty("display", "none", "important");
if (!MONITOR_FEATURE_MEMO_ENABLED) monitorNote.style.setProperty("display", "none", "important");
if (!MONITOR_FEATURE_SKETCH_ENABLED) monitorSketchpad.style.setProperty("display", "none", "important");

const MONITOR_SKETCH_STORAGE_KEY = "desktopWindowMonitorSketchV1";
const monitorSketchCanvas = document.getElementById("monitorSketchCanvas");
const monitorSketchPen = document.getElementById("monitorSketchPen");
const monitorSketchEraser = document.getElementById("monitorSketchEraser");
const monitorSketchLine = document.getElementById("monitorSketchLine");
const monitorSketchRect = document.getElementById("monitorSketchRect");
const monitorSketchText = document.getElementById("monitorSketchText");
const monitorSketchTextSmall = document.getElementById("monitorSketchTextSmall");
const monitorSketchTextMedium = document.getElementById("monitorSketchTextMedium");
const monitorSketchTextLarge = document.getElementById("monitorSketchTextLarge");
const monitorSketchTextSizeMenu = document.getElementById("monitorSketchTextSizeMenu");
const monitorSketchUndo = document.getElementById("monitorSketchUndo");
const monitorSketchRedo = document.getElementById("monitorSketchRedo");
const monitorSketchClear = document.getElementById("monitorSketchClear");
const monitorSketchCollapse = document.getElementById("monitorSketchCollapse");
const monitorSketchTextInput = document.getElementById("monitorSketchTextInput");
if (!MONITOR_FEATURE_SKETCH_ENABLED) {
  monitorSketchCanvas.width = 1;
  monitorSketchCanvas.height = 1;
  const startupOverlay = monitorSketchpad.querySelector("#monitorSketchOverlay");
  if (startupOverlay) { startupOverlay.width = 1; startupOverlay.height = 1; }
}
const monitorSketchNoopContext = {
  clearRect(){}, save(){}, restore(){}, drawImage(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, closePath(){}, strokeRect(){}, fillText(){},
  globalCompositeOperation:"source-over", strokeStyle:"#000", fillStyle:"#000", font:"16px sans-serif", textBaseline:"top", lineCap:"round", lineJoin:"round", lineWidth:1
};
const monitorSketchContext = MONITOR_FEATURE_SKETCH_ENABLED ? monitorSketchCanvas.getContext("2d") : monitorSketchNoopContext;
const monitorSketchOverlay = document.getElementById("monitorSketchOverlay");
const monitorSketchOverlayContext = monitorSketchOverlay.getContext("2d");
const monitorSketchCursor = document.getElementById("monitorSketchCursor");
let monitorSketchTool = "pen";
let monitorSketchDrawing = false;
let monitorSketchCollapsed = false;
let monitorSketchStartPoint = null;
let monitorSketchTextSize = "medium";
let monitorSketchTextPoint = null;
let monitorSketchTextLongPressTimer = null;
let monitorSketchSuppressTextClick = false;
const MONITOR_SKETCH_TEXT_SIZES = Object.freeze({ small: 14, medium: 20, large: 28 });
const MONITOR_SKETCH_TEXT_LONG_PRESS_MS = 450;
const MONITOR_SKETCH_HISTORY_LIMIT = 24;
const monitorSketchUndoStack = [];
const monitorSketchRedoStack = [];

/*@@MONITOR_FUNCTION:monitorSketchHideTextSizeMenu@@*/

/*@@MONITOR_FUNCTION:monitorSketchSetTool@@*/

/*@@MONITOR_FUNCTION:monitorSketchSetTextSize@@*/

/*@@MONITOR_FUNCTION:monitorSketchShowTextSizeMenu@@*/

/*@@MONITOR_FUNCTION:monitorSketchStartTextLongPress@@*/

/*@@MONITOR_FUNCTION:monitorSketchStopTextLongPress@@*/

/*@@MONITOR_FUNCTION:monitorSketchPoint@@*/

/*@@MONITOR_FUNCTION:monitorSketchCssPoint@@*/

/*@@MONITOR_FUNCTION:monitorSketchUpdateCursor@@*/

/*@@MONITOR_FUNCTION:monitorSketchClearOverlay@@*/

/*@@MONITOR_FUNCTION:monitorSketchPrepareShapeContext@@*/

/*@@MONITOR_FUNCTION:monitorSketchDrawShape@@*/

/*@@MONITOR_FUNCTION:monitorSketchDrawPreview@@*/

/*@@MONITOR_FUNCTION:monitorSketchCommitShape@@*/

/*@@MONITOR_FUNCTION:monitorSketchSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorSketchUpdateHistoryButtons@@*/

/*@@MONITOR_FUNCTION:monitorSketchRemember@@*/

/*@@MONITOR_FUNCTION:monitorSketchApplySnapshot@@*/

/*@@MONITOR_FUNCTION:monitorSketchUndoAction@@*/

/*@@MONITOR_FUNCTION:monitorSketchRedoAction@@*/

/*@@MONITOR_FUNCTION:monitorSketchSave@@*/

/*@@MONITOR_FUNCTION:monitorSketchRestore@@*/

/*@@MONITOR_FUNCTION:monitorSketchCancelText@@*/

/*@@MONITOR_FUNCTION:monitorSketchCommitText@@*/

/*@@MONITOR_FUNCTION:monitorSketchTextLeftBearing@@*/

/*@@MONITOR_FUNCTION:monitorSketchSyncTextInputBearing@@*/

/*@@MONITOR_FUNCTION:monitorSketchBeginText@@*/

/*@@MONITOR_FUNCTION:monitorSketchStop@@*/

monitorSketchCanvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  const point = monitorSketchPoint(event);
  if (!point) return;
  event.preventDefault();
  if (monitorSketchTool === "text") {
    monitorSketchHideTextSizeMenu();
    monitorSketchBeginText(event, point);
    return;
  }
  monitorSketchRemember();
  monitorSketchDrawing = true;
  monitorSketchStartPoint = point;
  monitorSketchCanvas.setPointerCapture(event.pointerId);
  if (monitorSketchTool === "line" || monitorSketchTool === "rect") {
    monitorSketchClearOverlay();
    return;
  }
  monitorSketchContext.beginPath();
  monitorSketchContext.moveTo(point.x, point.y);
  monitorSketchContext.lineCap = "round";
  monitorSketchContext.lineJoin = "round";
  monitorSketchContext.lineWidth = Math.max(4, point.scale * (monitorSketchTool === "eraser" ? 12 : 2.5));
  monitorSketchContext.globalCompositeOperation = monitorSketchTool === "eraser" ? "destination-out" : "source-over";
  monitorSketchContext.strokeStyle = "#000000";
});

monitorSketchCanvas.addEventListener("pointermove", (event) => {
  monitorSketchUpdateCursor(event);
  if (!monitorSketchDrawing) return;
  const point = monitorSketchPoint(event);
  if (!point) return;
  event.preventDefault();
  if (monitorSketchTool === "line" || monitorSketchTool === "rect") {
    monitorSketchDrawPreview(point);
    return;
  }
  monitorSketchContext.lineTo(point.x, point.y);
  monitorSketchContext.stroke();
});

monitorSketchCanvas.addEventListener("pointerenter", monitorSketchUpdateCursor);
monitorSketchCanvas.addEventListener("pointerleave", () => monitorSketchCursor.classList.remove("visible"));
monitorSketchCanvas.addEventListener("pointerup", monitorSketchStop);
monitorSketchCanvas.addEventListener("pointercancel", monitorSketchStop);
monitorSketchPen.addEventListener("click", () => monitorSketchSetTool("pen"));
monitorSketchEraser.addEventListener("click", () => monitorSketchSetTool("eraser"));
monitorSketchLine.addEventListener("click", () => monitorSketchSetTool("line"));
monitorSketchRect.addEventListener("click", () => monitorSketchSetTool("rect"));
monitorSketchText.addEventListener("pointerdown", monitorSketchStartTextLongPress);
monitorSketchText.addEventListener("pointerup", monitorSketchStopTextLongPress);
monitorSketchText.addEventListener("pointercancel", monitorSketchStopTextLongPress);
monitorSketchText.addEventListener("pointerleave", monitorSketchStopTextLongPress);
monitorSketchText.addEventListener("click", (event) => {
  if (monitorSketchSuppressTextClick) {
    monitorSketchSuppressTextClick = false;
    event.preventDefault();
    return;
  }
  monitorSketchHideTextSizeMenu();
  monitorSketchSetTool("text");
});
[
  [monitorSketchTextSmall, "small"],
  [monitorSketchTextMedium, "medium"],
  [monitorSketchTextLarge, "large"]
].forEach(([button, size]) => {
  button.addEventListener("pointerdown", (event) => event.preventDefault());
  button.addEventListener("click", () => {
    monitorSketchSetTextSize(size);
    monitorSketchSetTool("text");
    monitorSketchHideTextSizeMenu();
  });
});
document.addEventListener("pointerdown", (event) => {
  if (monitorSketchTextSizeMenu.hidden) return;
  if (monitorSketchTextSizeMenu.contains(event.target) || monitorSketchText.contains(event.target)) return;
  monitorSketchHideTextSizeMenu();
}, true);
monitorSketchTextInput.addEventListener("input", monitorSketchSyncTextInputBearing);
monitorSketchTextInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    monitorSketchCommitText();
  } else if (event.key === "Escape") {
    event.preventDefault();
    monitorSketchCancelText();
  }
});
monitorSketchTextInput.addEventListener("blur", monitorSketchCommitText);
monitorSketchUndo.addEventListener("click", monitorSketchUndoAction);
monitorSketchRedo.addEventListener("click", monitorSketchRedoAction);
monitorSketchClear.addEventListener("click", () => {
  monitorSketchRemember();
  monitorSketchContext.clearRect(0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
  monitorSketchClearOverlay();
  try { localStorage.removeItem(MONITOR_SKETCH_STORAGE_KEY); } catch (_) {}
});
monitorSketchCollapse.addEventListener("click", () => {
  monitorSketchCollapsed = !monitorSketchCollapsed;
  syncMonitorSideNote();
});
if (MONITOR_FEATURE_SKETCH_ENABLED) monitorSketchRestore();
monitorSketchUpdateHistoryButtons();

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

const monitorSideNoteText = document.getElementById("monitorSideNoteText");

const monitorNoteAi = document.getElementById("monitorNoteAi");

const monitorNoteCollapse = document.getElementById("monitorNoteCollapse");
monitorNoteCollapse.classList.add("monitor-collapse-chevron");
monitorNoteCollapse.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg>';

const monitorNoteBack = document.getElementById("monitorNoteBack");

const monitorNoteAdd = document.getElementById("monitorNoteAdd");

const monitorNoteDelete = document.getElementById("monitorNoteDelete");

const monitorNoteUndo = document.getElementById("monitorNoteUndo");

const monitorNoteRedo = document.getElementById("monitorNoteRedo");

const monitorNoteList = document.getElementById("monitorNoteList");

const monitorNoteEditor = document.getElementById("monitorNoteEditor");

const monitorNoteHeaderTitle = document.getElementById("monitorNoteHeaderTitle");

let monitorNotes = [];

let monitorActiveNoteId = "";

let monitorLastViewedNoteId = "";

let monitorNoteListMode = true;

/*@@MONITOR_FUNCTION:monitorNoteId@@*/

/*@@MONITOR_FUNCTION:monitorNoteTitleFromText@@*/

/*@@MONITOR_FUNCTION:monitorParseNoteBundle@@*/

/*@@MONITOR_FUNCTION:monitorSerializeNotes@@*/

/*@@MONITOR_FUNCTION:monitorActiveNote@@*/

const monitorNoteHistory = new Map();

const monitorNoteListUndo = [];

const monitorNoteListRedo = [];

/*@@MONITOR_FUNCTION:monitorNoteSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorNoteHistoryState@@*/

/*@@MONITOR_FUNCTION:monitorSyncHistoryButtons@@*/

/*@@MONITOR_FUNCTION:monitorRecordUndoBeforeEdit@@*/

/*@@MONITOR_FUNCTION:monitorApplyHistorySnapshot@@*/

/*@@MONITOR_FUNCTION:monitorUndoNote@@*/

/*@@MONITOR_FUNCTION:monitorRedoNote@@*/

/*@@MONITOR_FUNCTION:monitorUndoListDelete@@*/

/*@@MONITOR_FUNCTION:monitorRedoListDelete@@*/

let monitorNoteSuppressOpenUntil=0;

let monitorNoteDragState=null;

let monitorNoteDragRaf=0;

/*@@MONITOR_FUNCTION:monitorUpdateNoteInsertLine@@*/

/*@@MONITOR_FUNCTION:monitorNoteDragScrollTick@@*/

/*@@MONITOR_FUNCTION:monitorBindNoteDrag@@*/

/*@@MONITOR_FUNCTION:persistMonitorTrashedNotes@@*/

/*@@MONITOR_FUNCTION:trashMonitorNote@@*/

/*@@MONITOR_FUNCTION:restoreMonitorTrashedNote@@*/

/*@@MONITOR_FUNCTION:deleteMonitorTrashedNote@@*/

/*@@MONITOR_FUNCTION:clearMonitorTrashedNotes@@*/

/*@@MONITOR_FUNCTION:monitorRenderNoteList@@*/

/*@@MONITOR_FUNCTION:monitorHighlightLastViewedNote@@*/

/*@@MONITOR_FUNCTION:monitorShowNoteList@@*/

/*@@MONITOR_FUNCTION:monitorOpenNote@@*/

/*@@MONITOR_FUNCTION:monitorCreateNote@@*/

/*@@MONITOR_FUNCTION:monitorUpdateActiveFromEditor@@*/

/*@@MONITOR_FUNCTION:monitorQueueNoteBundleSave@@*/

let monitorNoteCollapsed = false;

let monitorNoteSaveTimer = 0;

/*@@MONITOR_FUNCTION:syncMonitorSideNote@@*/

monitorNoteCollapse.addEventListener("click", () => { monitorNoteCollapsed = !monitorNoteCollapsed; syncMonitorSideNote(); });

monitorNoteAdd.addEventListener("click", monitorCreateNote);

monitorNoteBack.addEventListener("click", () => { monitorUpdateActiveFromEditor(); monitorQueueNoteBundleSave(); monitorShowNoteList(); monitorHighlightLastViewedNote(); });

monitorNoteDelete.addEventListener("click", () => { const id=monitorActiveNoteId; if(!id)return; const note=monitorNotes.find(n=>n.id===id); if(note)trashMonitorNote(note); monitorNotes=monitorNotes.filter(n=>n.id!==id); monitorNoteHistory.delete(id); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorShowNoteList(); });

monitorNoteUndo.addEventListener("click", () => { if(monitorNoteListMode) monitorUndoListDelete(); else monitorUndoNote(); });

monitorNoteRedo.addEventListener("click", () => { if(monitorNoteListMode) monitorRedoListDelete(); else monitorRedoNote(); });

monitorNoteEditor.addEventListener("keydown", (event) => { if(!event.ctrlKey||event.altKey||event.metaKey)return; const key=String(event.key||"").toLowerCase(); if(key==="z"){event.preventDefault(); if(event.shiftKey)monitorRedoNote(); else monitorUndoNote();} else if(key==="y"){event.preventDefault(); monitorRedoNote();} });

monitorNote.addEventListener("keydown", (event) => { if(!monitorNoteListMode||!event.ctrlKey||event.altKey||event.metaKey)return; const key=String(event.key||"").toLowerCase(); if(key==="z"){event.preventDefault(); if(event.shiftKey)monitorRedoListDelete(); else monitorUndoListDelete();} else if(key==="y"){event.preventDefault(); monitorRedoListDelete();} });

let monitorNoteAiBusy = false;

/*@@MONITOR_FUNCTION:organizeMonitorNoteWithAi@@*/

monitorNoteAi.addEventListener("click", organizeMonitorNoteWithAi);

/*@@MONITOR_FUNCTION:monitorNoteNative@@*/

let monitorNoteLastSharedText = "";

let monitorNoteLocalDirty = false;

let monitorNoteReady = false;

let monitorNoteViewRevision = "";

let monitorNoteViewRemoteApplying = false;

let monitorNoteViewSaveTimer = 0;

let monitorNoteViewSyncBusy = false;

/*@@MONITOR_FUNCTION:monitorNoteScrollRatio@@*/

/*@@MONITOR_FUNCTION:refreshMonitorSharedNoteView@@*/

monitorSideNoteText.addEventListener("scroll", (event) => {

  if (monitorNoteViewRemoteApplying || !event.isTrusted) return;

  clearTimeout(monitorNoteViewSaveTimer);

  monitorNoteViewSaveTimer = setTimeout(async () => {

    const result = await monitorNoteNative({ type: "setSharedMonitorNoteView", ratio: String(monitorNoteScrollRatio()) }).catch(() => null);

    if (result?.ok && result.revision) monitorNoteViewRevision = String(result.revision);

  }, 80);

});

/*@@MONITOR_FUNCTION:refreshMonitorSharedNote@@*/

monitorSideNoteText.addEventListener("input", (event) => {

  syncMonitorSideNote();

  if (!event.isTrusted || !monitorNoteReady || monitorNoteListMode) return;

  monitorRecordUndoBeforeEdit();

  monitorUpdateActiveFromEditor();

  monitorQueueNoteBundleSave();

  monitorSyncHistoryButtons();

});

// Shared note reads are event-driven: startup/focus.

if (MONITOR_FEATURE_MEMO_ENABLED) {
  setTimeout(refreshMonitorSharedNote, 250);
  setTimeout(refreshMonitorSharedNoteView, 320);
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
