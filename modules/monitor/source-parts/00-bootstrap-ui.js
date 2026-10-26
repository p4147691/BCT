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

function monitorRecordRefreshTiming(startedAt, stages) {
  const totalMs = Math.max(0, performance.now() - startedAt);
  monitorRenderDiagnostics.refreshRuns += 1;
  monitorRenderDiagnostics.refreshLastMs = totalMs;
  monitorRenderDiagnostics.refreshSlowestMs = Math.max(monitorRenderDiagnostics.refreshSlowestMs, totalMs);
  monitorRenderDiagnostics.refreshLastStages = { ...stages, total: totalMs };
}

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

function monitorSketchHideTextSizeMenu() {
  monitorSketchTextSizeMenu.hidden = true;
  monitorSketchText.setAttribute("aria-expanded", "false");
}

function monitorSketchSetTool(tool) {
  monitorSketchTool = ["pen", "eraser", "line", "rect", "text"].includes(tool) ? tool : "pen";
  monitorSketchPen.classList.toggle("active", monitorSketchTool === "pen");
  monitorSketchEraser.classList.toggle("active", monitorSketchTool === "eraser");
  monitorSketchLine.classList.toggle("active", monitorSketchTool === "line");
  monitorSketchRect.classList.toggle("active", monitorSketchTool === "rect");
  monitorSketchText.classList.toggle("active", monitorSketchTool === "text");
  monitorSketchCursor.classList.toggle("pen", monitorSketchTool === "pen");
  monitorSketchCursor.classList.toggle("eraser", monitorSketchTool === "eraser");
  monitorSketchCursor.classList.toggle("shape", monitorSketchTool === "line" || monitorSketchTool === "rect");
  monitorSketchCursor.classList.toggle("text", monitorSketchTool === "text");
  if (monitorSketchTool !== "text") monitorSketchHideTextSizeMenu();
}

function monitorSketchSetTextSize(size) {
  monitorSketchTextSize = MONITOR_SKETCH_TEXT_SIZES[size] ? size : "medium";
  monitorSketchTextSmall.classList.toggle("active", monitorSketchTextSize === "small");
  monitorSketchTextMedium.classList.toggle("active", monitorSketchTextSize === "medium");
  monitorSketchTextLarge.classList.toggle("active", monitorSketchTextSize === "large");
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  monitorSketchCursor.style.setProperty("--monitor-sketch-text-caret-height", `${cssSize}px`);
  if (!monitorSketchTextInput.hidden) monitorSketchTextInput.style.fontSize = `${cssSize}px`;
}

function monitorSketchShowTextSizeMenu() {
  monitorSketchSetTool("text");
  monitorSketchTextSizeMenu.hidden = false;
  monitorSketchText.setAttribute("aria-expanded", "true");
}

function monitorSketchStartTextLongPress(event) {
  if (event.button !== 0) return;
  if (monitorSketchTextLongPressTimer) clearTimeout(monitorSketchTextLongPressTimer);
  monitorSketchSuppressTextClick = false;
  monitorSketchTextLongPressTimer = setTimeout(() => {
    monitorSketchTextLongPressTimer = null;
    monitorSketchSuppressTextClick = true;
    monitorSketchShowTextSizeMenu();
  }, MONITOR_SKETCH_TEXT_LONG_PRESS_MS);
}

function monitorSketchStopTextLongPress() {
  if (!monitorSketchTextLongPressTimer) return;
  clearTimeout(monitorSketchTextLongPressTimer);
  monitorSketchTextLongPressTimer = null;
}

function monitorSketchPoint(event) {
  const rect = monitorSketchCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: (event.clientX - rect.left) * monitorSketchCanvas.width / rect.width,
    y: (event.clientY - rect.top) * monitorSketchCanvas.height / rect.height,
    scale: monitorSketchCanvas.width / rect.width
  };
}

function monitorSketchCssPoint(point) {
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const wrapRect = monitorSketchCanvas.parentElement.getBoundingClientRect();
  if (!point || !canvasRect.width || !canvasRect.height) return null;
  return {
    left: canvasRect.left - wrapRect.left + point.x * canvasRect.width / monitorSketchCanvas.width,
    top: canvasRect.top - wrapRect.top + point.y * canvasRect.height / monitorSketchCanvas.height
  };
}

function monitorSketchUpdateCursor(event) {
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const point = monitorSketchPoint(event);
  const cssPoint = monitorSketchCssPoint(point);
  if (!cssPoint || !canvasRect.width || !canvasRect.height) return;
  monitorSketchCursor.style.left = `${cssPoint.left}px`;
  monitorSketchCursor.style.top = `${cssPoint.top}px`;
  if (monitorSketchTool === "eraser") {
    const scale = monitorSketchCanvas.width / canvasRect.width;
    const eraseCssPx = Math.max(12, 4 / Math.max(scale, 0.001));
    monitorSketchCursor.style.width = `${eraseCssPx}px`;
    monitorSketchCursor.style.height = `${eraseCssPx}px`;
  } else {
    monitorSketchCursor.style.width = "";
    monitorSketchCursor.style.height = "";
  }
  if (monitorSketchTool === "text") {
    monitorSketchCursor.style.setProperty("--monitor-sketch-text-caret-height", `${MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize]}px`);
  }
  monitorSketchCursor.classList.add("visible");
}

function monitorSketchClearOverlay() {
  monitorSketchOverlayContext.clearRect(0, 0, monitorSketchOverlay.width, monitorSketchOverlay.height);
}

function monitorSketchPrepareShapeContext(context, point) {
  context.globalCompositeOperation = "source-over";
  context.strokeStyle = "#000000";
  context.lineCap = "round";
  context.lineJoin = "round";
  context.lineWidth = Math.max(4, point.scale * 2.5);
}

function monitorSketchDrawShape(context, point) {
  if (!monitorSketchStartPoint) return;
  const start = monitorSketchStartPoint;
  if (monitorSketchTool === "line") {
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(point.x, point.y);
    context.stroke();
    context.closePath();
    return;
  }
  if (monitorSketchTool === "rect") {
    const x = Math.min(start.x, point.x);
    const y = Math.min(start.y, point.y);
    const width = Math.abs(point.x - start.x);
    const height = Math.abs(point.y - start.y);
    context.strokeRect(x, y, width, height);
  }
}

function monitorSketchDrawPreview(point) {
  monitorSketchClearOverlay();
  monitorSketchPrepareShapeContext(monitorSketchOverlayContext, point);
  monitorSketchDrawShape(monitorSketchOverlayContext, point);
}

function monitorSketchCommitShape(point) {
  monitorSketchPrepareShapeContext(monitorSketchContext, point);
  monitorSketchDrawShape(monitorSketchContext, point);
  monitorSketchClearOverlay();
}

function monitorSketchSnapshot() {
  try { return monitorSketchCanvas.toDataURL("image/png"); } catch (_) { return ""; }
}

function monitorSketchUpdateHistoryButtons() {
  monitorSketchUndo.disabled = monitorSketchUndoStack.length === 0;
  monitorSketchRedo.disabled = monitorSketchRedoStack.length === 0;
}

function monitorSketchRemember() {
  const snapshot = monitorSketchSnapshot();
  if (!snapshot) return;
  if (monitorSketchUndoStack[monitorSketchUndoStack.length - 1] !== snapshot) {
    monitorSketchUndoStack.push(snapshot);
    if (monitorSketchUndoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchUndoStack.shift();
  }
  monitorSketchRedoStack.length = 0;
  monitorSketchUpdateHistoryButtons();
}

function monitorSketchApplySnapshot(snapshot) {
  if (!snapshot) return;
  const image = new Image();
  image.onload = () => {
    monitorSketchContext.save();
    monitorSketchContext.globalCompositeOperation = "source-over";
    monitorSketchContext.clearRect(0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
    monitorSketchContext.drawImage(image, 0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
    monitorSketchContext.restore();
    monitorSketchClearOverlay();
    monitorSketchSave();
  };
  image.src = snapshot;
}

function monitorSketchUndoAction() {
  if (!monitorSketchUndoStack.length) return;
  const current = monitorSketchSnapshot();
  const previous = monitorSketchUndoStack.pop();
  if (current) {
    monitorSketchRedoStack.push(current);
    if (monitorSketchRedoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchRedoStack.shift();
  }
  monitorSketchApplySnapshot(previous);
  monitorSketchUpdateHistoryButtons();
}

function monitorSketchRedoAction() {
  if (!monitorSketchRedoStack.length) return;
  const current = monitorSketchSnapshot();
  const next = monitorSketchRedoStack.pop();
  if (current) {
    monitorSketchUndoStack.push(current);
    if (monitorSketchUndoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchUndoStack.shift();
  }
  monitorSketchApplySnapshot(next);
  monitorSketchUpdateHistoryButtons();
}

function monitorSketchSave() {
  try { localStorage.setItem(MONITOR_SKETCH_STORAGE_KEY, monitorSketchCanvas.toDataURL("image/png")); } catch (_) {}
}

function monitorSketchRestore() {
  let saved = "";
  try { saved = localStorage.getItem(MONITOR_SKETCH_STORAGE_KEY) || ""; } catch (_) {}
  if (!saved) return;
  const image = new Image();
  image.onload = () => monitorSketchContext.drawImage(image, 0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
  image.src = saved;
}

function monitorSketchCancelText() {
  monitorSketchTextInput.hidden = true;
  monitorSketchTextInput.value = "";
  monitorSketchTextPoint = null;
}

function monitorSketchCommitText() {
  if (monitorSketchTextInput.hidden || !monitorSketchTextPoint) return;
  const text = monitorSketchTextInput.value;
  const point = monitorSketchTextPoint;
  monitorSketchTextInput.hidden = true;
  monitorSketchTextInput.value = "";
  monitorSketchTextPoint = null;
  if (!text) return;
  monitorSketchRemember();
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  const fontSize = Math.max(1, point.scale * cssSize);
  monitorSketchContext.save();
  monitorSketchContext.globalCompositeOperation = "source-over";
  monitorSketchContext.fillStyle = "#000000";
  monitorSketchContext.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
  monitorSketchContext.textBaseline = "alphabetic";
  const metrics = monitorSketchContext.measureText(text);
  const fontAscent = Number(metrics.fontBoundingBoxAscent) || fontSize * 0.8;
  const fontDescent = Number(metrics.fontBoundingBoxDescent) || fontSize * 0.2;
  const lineBoxOffset = (fontSize - (fontAscent + fontDescent)) / 2;
  const leftBearing = Number(metrics.actualBoundingBoxLeft) || 0;
  monitorSketchContext.fillText(text, point.x + leftBearing, point.y + fontAscent + lineBoxOffset);
  monitorSketchContext.restore();
  monitorSketchSave();
}

function monitorSketchTextLeftBearing(text, point) {
  if (!text || !point) return 0;
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  const fontSize = Math.max(1, point.scale * cssSize);
  monitorSketchContext.save();
  monitorSketchContext.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
  const metrics = monitorSketchContext.measureText(text);
  monitorSketchContext.restore();
  return Number(metrics.actualBoundingBoxLeft) || 0;
}

function monitorSketchSyncTextInputBearing() {
  if (monitorSketchTextInput.hidden || !monitorSketchTextPoint) return;
  const cssPoint = monitorSketchCssPoint(monitorSketchTextPoint);
  if (!cssPoint) return;
  const bearing = monitorSketchTextLeftBearing(monitorSketchTextInput.value, monitorSketchTextPoint);
  const bearingCss = bearing / Math.max(monitorSketchTextPoint.scale, 0.001);
  monitorSketchTextInput.style.left = `${cssPoint.left + bearingCss}px`;
}

function monitorSketchBeginText(event, point) {
  monitorSketchCommitText();
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const wrapRect = monitorSketchCanvas.parentElement.getBoundingClientRect();
  const cssPoint = monitorSketchCssPoint(point);
  if (!cssPoint) return;
  monitorSketchTextPoint = point;
  monitorSketchTextInput.value = "";
  monitorSketchTextInput.style.left = `${cssPoint.left}px`;
  monitorSketchTextInput.style.top = `${cssPoint.top}px`;
  monitorSketchTextInput.style.width = `${Math.max(32, Math.min(180, canvasRect.right - (wrapRect.left + cssPoint.left)))}px`;
  monitorSketchTextInput.style.fontSize = `${MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize]}px`;
  monitorSketchTextInput.hidden = false;
  requestAnimationFrame(() => {
    try { monitorSketchTextInput.focus({ preventScroll: true }); } catch (_) { monitorSketchTextInput.focus(); }
  });
}

function monitorSketchStop(event) {
  if (!monitorSketchDrawing) return;
  const point = event?.type === "pointercancel" ? null : monitorSketchPoint(event);
  if (point && (monitorSketchTool === "line" || monitorSketchTool === "rect")) {
    monitorSketchCommitShape(point);
  } else {
    monitorSketchClearOverlay();
  }
  monitorSketchDrawing = false;
  monitorSketchStartPoint = null;
  try { if (event?.pointerId != null) monitorSketchCanvas.releasePointerCapture(event.pointerId); } catch (_) {}
  monitorSketchContext.closePath();
  monitorSketchContext.globalCompositeOperation = "source-over";
  monitorSketchSave();
}

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

function monitorNoteId() { return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2,7)}`; }

function monitorNoteTitleFromText(text) { return String(text||"").split(/\r?\n/).map(v=>v.trim()).find(Boolean)?.slice(0,42) || "새 메모"; }

function monitorParseNoteBundle(raw) {

  const text = String(raw || "");

  if (text.startsWith(MONITOR_NOTE_BUNDLE_PREFIX)) {

    try { const data = JSON.parse(text.slice(MONITOR_NOTE_BUNDLE_PREFIX.length)); return Array.isArray(data?.notes) ? data.notes.filter(n=>n&&n.id).map(n=>{ const body=String(n.body||""); return {id:String(n.id),title:monitorNoteTitleFromText(body),body,updatedAt:Number(n.updatedAt)||0}; }) : []; } catch (_) { return []; }

  }

  return text.trim() ? [{ id:monitorNoteId(), title:monitorNoteTitleFromText(text), body:text, updatedAt:Date.now() }] : [];

}

function monitorSerializeNotes() { return MONITOR_NOTE_BUNDLE_PREFIX + JSON.stringify({ notes:monitorNotes }); }

function monitorActiveNote() { return monitorNotes.find(n=>n.id===monitorActiveNoteId) || null; }

const monitorNoteHistory = new Map();

const monitorNoteListUndo = [];

const monitorNoteListRedo = [];

function monitorNoteSnapshot(note=monitorActiveNote()) { return note ? { title:String(note.title||""), body:String(note.body||"") } : null; }

function monitorNoteHistoryState(id=monitorActiveNoteId) { if(!id)return null; if(!monitorNoteHistory.has(id)) monitorNoteHistory.set(id,{undo:[],redo:[]}); return monitorNoteHistory.get(id); }

function monitorSyncHistoryButtons() {

  if (monitorNoteListMode) {

    monitorNoteUndo.hidden = false;

    monitorNoteUndo.disabled = !monitorNoteListUndo.length;

    monitorNoteUndo.title = "목록 변경 되돌리기 (Ctrl+Z)";

    monitorNoteUndo.setAttribute("aria-label", "목록 변경 되돌리기");

    monitorNoteRedo.hidden = false;

    monitorNoteRedo.disabled = !monitorNoteListRedo.length;

    monitorNoteRedo.title = "목록 변경 다시 실행 (Ctrl+Y / Ctrl+Shift+Z)";

    monitorNoteRedo.setAttribute("aria-label", "목록 변경 다시 실행");

    return;

  }

  const h=monitorNoteHistoryState();

  const editing=!!monitorActiveNoteId;

  monitorNoteUndo.hidden=!editing; monitorNoteRedo.hidden=!editing;

  monitorNoteUndo.disabled=!h?.undo?.length; monitorNoteRedo.disabled=!h?.redo?.length;

  monitorNoteUndo.title = "실행 취소 (Ctrl+Z)";

  monitorNoteUndo.setAttribute("aria-label", "실행 취소");

}

function monitorRecordUndoBeforeEdit() { const note=monitorActiveNote(); const h=monitorNoteHistoryState(); if(!note||!h)return; const prev=monitorNoteSnapshot(note); const next={title:monitorNoteTitleFromText(monitorSideNoteText.value),body:String(monitorSideNoteText.value||"")}; if(prev.body===next.body)return; const last=h.undo[h.undo.length-1]; if(!last||last.body!==prev.body) h.undo.push(prev); if(h.undo.length>100)h.undo.shift(); h.redo.length=0; }

function monitorApplyHistorySnapshot(snapshot) { const note=monitorActiveNote(); if(!note||!snapshot)return; note.body=String(snapshot.body||""); note.title=monitorNoteTitleFromText(note.body); note.updatedAt=Date.now(); monitorSideNoteText.value=note.body; monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorSyncHistoryButtons(); }

function monitorUndoNote() { const note=monitorActiveNote(); const h=monitorNoteHistoryState(); if(!note||!h?.undo?.length)return; h.redo.push(monitorNoteSnapshot(note)); monitorApplyHistorySnapshot(h.undo.pop()); }

function monitorRedoNote() { const note=monitorActiveNote(); const h=monitorNoteHistoryState(); if(!note||!h?.redo?.length)return; h.undo.push(monitorNoteSnapshot(note)); monitorApplyHistorySnapshot(h.redo.pop()); }

function monitorUndoListDelete() { const action=monitorNoteListUndo.pop(); if(!action)return; let note=action.note||action; if(action.type==="create"){ const current=monitorNotes.find(n=>n.id===note.id); if(current) note={...current}; monitorNotes=monitorNotes.filter(n=>n.id!==note.id); monitorNoteHistory.delete(note.id); } else if(!monitorNotes.some(n=>n.id===note.id)) monitorNotes.push(note); monitorNoteListRedo.push({type:action.type||"delete",note:{...note}}); if(monitorNoteListRedo.length>50)monitorNoteListRedo.shift(); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorSyncHistoryButtons(); }

function monitorRedoListDelete() { const action=monitorNoteListRedo.pop(); if(!action)return; const note=action.note||action; if((action.type||"delete")==="create"){ if(!monitorNotes.some(n=>n.id===note.id)) monitorNotes.push(note); } else { monitorNotes=monitorNotes.filter(n=>n.id!==note.id); monitorNoteHistory.delete(note.id); } monitorNoteListUndo.push({type:action.type||"delete",note:{...note}}); if(monitorNoteListUndo.length>50)monitorNoteListUndo.shift(); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorSyncHistoryButtons(); }

let monitorNoteSuppressOpenUntil=0;

let monitorNoteDragState=null;

let monitorNoteDragRaf=0;

function monitorUpdateNoteInsertLine(clientY) {

  const st=monitorNoteDragState; if(!st?.active)return;

  const rows=[...monitorNoteList.querySelectorAll(".monitor-note-item")];

  let beforeId=null, lineY=null;

  for(const row of rows){

    const r=row.getBoundingClientRect();

    if(clientY < r.top + r.height/2){ beforeId=row.dataset.noteId; lineY=r.top; break; }

  }

  if(lineY==null){

    const last=rows[rows.length-1];

    lineY=last ? last.getBoundingClientRect().bottom : monitorNoteList.getBoundingClientRect().top+7;

  }

  st.beforeId=beforeId;

  const listRect=monitorNoteList.getBoundingClientRect();

  st.insertLine.style.top=`${lineY-listRect.top+monitorNoteList.scrollTop}px`;

}

function monitorNoteDragScrollTick() {

  const st=monitorNoteDragState; if(!st?.active){monitorNoteDragRaf=0;return;}

  if(st.scrollVelocity){ monitorNoteList.scrollTop+=st.scrollVelocity; monitorUpdateNoteInsertLine(st.lastClientY); }

  monitorNoteDragRaf=requestAnimationFrame(monitorNoteDragScrollTick);

}

function monitorBindNoteDrag(row,noteId) {

  row.addEventListener("pointerdown",ev=>{

    if(ev.button!==0||ev.target.closest(".monitor-note-item-delete")||monitorNoteDragState)return;

    const startX=ev.clientX,startY=ev.clientY;

    const state={row,noteId,pointerId:ev.pointerId,startX,startY,lastClientY:startY,active:false,scrollVelocity:0,offsetY:0,height:0,ghost:null,insertLine:null,beforeId:noteId};

    monitorNoteDragState=state;

    const onMove=e=>{

      if(e.pointerId!==state.pointerId)return;

      state.lastClientY=e.clientY;

      if(!state.active&&Math.hypot(e.clientX-startX,e.clientY-startY)<6)return;

      if(!state.active){

        state.active=true; monitorNoteSuppressOpenUntil=Date.now()+500;

        const r=row.getBoundingClientRect(); state.offsetY=startY-r.top; state.height=r.height;

        const ghost=row.cloneNode(true); ghost.classList.add("monitor-note-drag-ghost"); ghost.removeAttribute("data-note-id");

        Object.assign(ghost.style,{position:"fixed",left:`${r.left}px`,top:`${r.top}px`,width:`${r.width}px`,height:`${r.height}px`,margin:"0",zIndex:"2147483646",pointerEvents:"none"});

        state.ghost=ghost; document.body.appendChild(ghost); row.classList.add("monitor-note-drag-source");

        const line=document.createElement("div"); line.className="monitor-note-insert-line"; state.insertLine=line; monitorNoteList.appendChild(line);

        monitorNoteList.classList.add("monitor-note-reordering"); monitorUpdateNoteInsertLine(startY);

        if(!monitorNoteDragRaf)monitorNoteDragRaf=requestAnimationFrame(monitorNoteDragScrollTick);

      }

      e.preventDefault();

      const listRect=monitorNoteList.getBoundingClientRect();

      const top=Math.max(listRect.top,Math.min(e.clientY-state.offsetY,listRect.bottom-state.height));

      state.ghost.style.top=`${top}px`;

      const edge=Math.min(48,Math.max(30,listRect.height*.16));

      if(e.clientY<listRect.top+edge) state.scrollVelocity=-Math.min(14,Math.max(2,(listRect.top+edge-e.clientY)*.34));

      else if(e.clientY>listRect.bottom-edge) state.scrollVelocity=Math.min(14,Math.max(2,(e.clientY-(listRect.bottom-edge))*.34));

      else state.scrollVelocity=0;

      monitorUpdateNoteInsertLine(e.clientY);

    };

    const finish=e=>{

      if(e.pointerId!==state.pointerId)return;

      document.removeEventListener("pointermove",onMove); document.removeEventListener("pointerup",finish); document.removeEventListener("pointercancel",finish);

      if(state.active){

        state.scrollVelocity=0; if(monitorNoteDragRaf){cancelAnimationFrame(monitorNoteDragRaf);monitorNoteDragRaf=0;}

        state.ghost?.remove(); state.insertLine?.remove(); row.classList.remove("monitor-note-drag-source"); monitorNoteList.classList.remove("monitor-note-reordering");

        const currentIds=monitorNotes.map(n=>n.id); const filtered=currentIds.filter(id=>id!==state.noteId);

        let insertAt=state.beforeId ? filtered.indexOf(state.beforeId) : filtered.length;

        if(insertAt<0)insertAt=filtered.length; filtered.splice(insertAt,0,state.noteId);

        const byId=new Map(monitorNotes.map(note=>[note.id,note]));

        if(filtered.length===monitorNotes.length&&filtered.every(id=>byId.has(id))){ monitorNotes=filtered.map(id=>byId.get(id)); monitorLastViewedNoteId=state.noteId; monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorHighlightLastViewedNote(); }

        monitorNoteSuppressOpenUntil=Date.now()+350;

      }

      monitorNoteDragState=null;

    };

    document.addEventListener("pointermove",onMove,{passive:false}); document.addEventListener("pointerup",finish); document.addEventListener("pointercancel",finish);

  });

}

function persistMonitorTrashedNotes(){

  chrome.storage.local.set({[MONITOR_TRASHED_NOTES_KEY]:[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,100)});

}

function trashMonitorNote(note){

  if(!note?.id)return; monitorTrashedNotes.set(String(note.id),{...note,trashed_at_ms:Date.now()}); persistMonitorTrashedNotes(); refreshMonitorRecoveryMenu();

}

function restoreMonitorTrashedNote(id){

  const note=monitorTrashedNotes.get(String(id)); if(!note)return; monitorTrashedNotes.delete(String(id)); const restored={...note}; delete restored.trashed_at_ms; if(!monitorNotes.some((x)=>x.id===restored.id))monitorNotes.push(restored); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); persistMonitorTrashedNotes(); monitorRenderNoteList(); refreshMonitorRecoveryMenu();

}

function deleteMonitorTrashedNote(id){monitorTrashedNotes.delete(String(id));persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}

function clearMonitorTrashedNotes(){monitorTrashedNotes.clear();persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}

function monitorRenderNoteList() {
  if (!MONITOR_FEATURE_MEMO_ENABLED) { monitorNoteList.replaceChildren(); return; }

  monitorNoteList.innerHTML = "";

  const sorted = [...monitorNotes];

  if (!sorted.length) { const empty=document.createElement("div"); empty.className="monitor-note-empty"; empty.textContent="메모가 없습니다. 위 + 버튼을 눌러 시작하세요."; monitorNoteList.appendChild(empty); return; }

  for (const note of sorted) {

    const row=document.createElement("div"); row.className="monitor-note-item"; row.dataset.noteId=note.id; if(note.id===monitorLastViewedNoteId) row.classList.add("is-last-viewed");

    const open=document.createElement("button"); open.type="button"; open.className="monitor-note-item-open";

    const title=document.createElement("strong"); title.textContent=note.title||"새 메모";

    const preview=document.createElement("span"); preview.textContent=String(note.body||"").replace(/\s+/g," ").trim().slice(0,72)||"내용 없음";

    open.append(title,preview); open.addEventListener("click",event=>{ if(Date.now()<monitorNoteSuppressOpenUntil){event.preventDefault();return;} monitorOpenNote(note.id); });

    const del=document.createElement("button"); del.type="button"; del.className="monitor-note-item-delete"; del.title="메모 삭제"; del.setAttribute("aria-label",`${note.title||"새 메모"} 삭제`); del.textContent="🗑";

    del.addEventListener("click",()=>{ trashMonitorNote(note); monitorNotes=monitorNotes.filter(n=>n.id!==note.id); monitorNoteHistory.delete(note.id); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorSyncHistoryButtons(); });

    row.append(open,del); monitorBindNoteDrag(row,note.id); monitorNoteList.appendChild(row);

  }

}

function monitorHighlightLastViewedNote() {

  const id=String(monitorLastViewedNoteId||""); if(!id)return;

  requestAnimationFrame(()=>{

    const row=[...monitorNoteList.querySelectorAll(".monitor-note-item")].find(el=>el.dataset.noteId===id);

    if(!row)return;

    row.scrollIntoView({block:"nearest",inline:"nearest"});

    row.classList.remove("monitor-note-return-highlight");

    void row.offsetWidth;

    row.classList.add("monitor-note-return-highlight");

    setTimeout(()=>row.classList.remove("monitor-note-return-highlight"),1200);

  });

}

function monitorShowNoteList() { monitorNoteListMode=true; monitorActiveNoteId=""; monitorNoteList.hidden=false; monitorNoteEditor.hidden=true; monitorNoteBack.hidden=true; monitorNoteAi.hidden=false; monitorNoteDelete.hidden=true; monitorNoteAdd.hidden=false; monitorNoteHeaderTitle.textContent="메모"; monitorRenderNoteList(); monitorSyncHistoryButtons(); }

function monitorOpenNote(id, focusEditor=true) { const note=monitorNotes.find(n=>n.id===id); if(!note)return; monitorNoteListMode=false; monitorActiveNoteId=id; monitorLastViewedNoteId=id; monitorNoteHistoryState(id); monitorNoteList.hidden=true; monitorNoteEditor.hidden=false; monitorNoteBack.hidden=false; monitorNoteAi.hidden=false; monitorNoteAdd.hidden=true; monitorNoteHeaderTitle.textContent="메모 편집"; monitorNoteDelete.textContent="🗑"; monitorNoteDelete.hidden=false; monitorSideNoteText.value=note.body||""; monitorSyncHistoryButtons(); if(focusEditor) requestAnimationFrame(()=>monitorSideNoteText.focus()); }

function monitorCreateNote() {

  const note={id:monitorNoteId(),title:"새 메모",body:"",updatedAt:Date.now()};

  monitorNoteListUndo.push({type:"create",note:{...note}});

  if(monitorNoteListUndo.length>50)monitorNoteListUndo.shift();

  monitorNoteListRedo.length=0;

  monitorNotes.unshift(note);

  monitorNoteLocalDirty=true;

  monitorQueueNoteBundleSave();

  monitorShowNoteList();

  requestAnimationFrame(()=>{

    const row=[...monitorNoteList.querySelectorAll(".monitor-note-item")].find(el=>el.dataset.noteId===note.id);

    if(row) row.scrollIntoView({block:"start",inline:"nearest"});

  });

}

function monitorUpdateActiveFromEditor() { const note=monitorActiveNote(); if(!note)return; note.body=String(monitorSideNoteText.value||""); note.title=monitorNoteTitleFromText(note.body); note.updatedAt=Date.now(); monitorNoteLocalDirty=true; }

function monitorQueueNoteBundleSave() { clearTimeout(monitorNoteSaveTimer); monitorNoteSaveTimer=setTimeout(async()=>{ const text=monitorSerializeNotes(); const result=await monitorNoteNative({type:"setSharedNote",text}).catch(()=>null); if(result?.ok){monitorNoteLastSharedText=text;monitorNoteLocalDirty=false;} },180); }

let monitorNoteCollapsed = false;

let monitorNoteSaveTimer = 0;

function syncMonitorSideNote() {

  const boardCollapsed = monitorRoot.classList.contains("collapsed");

  monitorNote.hidden = boardCollapsed;
  monitorSketchpad.hidden = boardCollapsed;

  if (boardCollapsed) return;

  const rect = monitorRoot.getBoundingClientRect();

  const width = Math.min(300, Math.max(220, rect.left - 24));

  const effectiveWidth = monitorNoteCollapsed ? 50 : width;

  monitorNote.style.width = `${Math.round(width)}px`;

  monitorNote.style.top = `${Math.round(rect.top)}px`;

  monitorNote.style.left = `${Math.max(8, Math.round(rect.left - effectiveWidth - 8))}px`;

  const noteLeft = Number.parseFloat(monitorNote.style.left) || 8;
  const sketchWidth = Math.min(280, Math.max(180, noteLeft - 16));
  const sketchEffectiveWidth = monitorSketchCollapsed ? 50 : sketchWidth;
  monitorSketchpad.style.width = `${Math.round(sketchWidth)}px`;
  monitorSketchpad.style.top = `${Math.round(rect.top)}px`;
  monitorSketchpad.style.left = `${Math.max(8, Math.round(noteLeft - sketchEffectiveWidth - 8))}px`;
  monitorSketchpad.style.height = monitorSketchCollapsed ? "40px" : `${Math.round(rect.height)}px`;
  monitorSketchpad.style.minWidth = monitorSketchCollapsed ? "50px" : "180px";
  monitorSketchpad.style.minHeight = monitorSketchCollapsed ? "40px" : "180px";
  monitorSketchpad.classList.toggle("collapsed", monitorSketchCollapsed);
  monitorSketchCollapse.classList.toggle("is-collapsed", monitorSketchCollapsed);
  monitorSketchCollapse.title = monitorSketchCollapsed ? "그림판 펼치기" : "그림판 접기";
  monitorSketchCollapse.setAttribute("aria-label", monitorSketchCollapse.title);

  monitorNote.classList.toggle("collapsed", monitorNoteCollapsed);

  monitorNoteCollapse.classList.toggle("is-collapsed", monitorNoteCollapsed);

  monitorNoteCollapse.title = monitorNoteCollapsed ? "메모 펼치기" : "메모 접기";

  monitorNoteCollapse.setAttribute("aria-label", monitorNoteCollapse.title);

  if (monitorNoteCollapsed) {

    monitorNote.style.width = "50px";

    monitorNote.style.minWidth = "50px";

    monitorNote.style.height = "40px";

    monitorNote.style.minHeight = "40px";

    return;

  }

  monitorNote.style.minWidth = "220px";

  monitorNote.style.minHeight = "180px";

  monitorNote.style.height = `${Math.round(rect.height)}px`;

}

monitorNoteCollapse.addEventListener("click", () => { monitorNoteCollapsed = !monitorNoteCollapsed; syncMonitorSideNote(); });

monitorNoteAdd.addEventListener("click", monitorCreateNote);

monitorNoteBack.addEventListener("click", () => { monitorUpdateActiveFromEditor(); monitorQueueNoteBundleSave(); monitorShowNoteList(); monitorHighlightLastViewedNote(); });

monitorNoteDelete.addEventListener("click", () => { const id=monitorActiveNoteId; if(!id)return; const note=monitorNotes.find(n=>n.id===id); if(note)trashMonitorNote(note); monitorNotes=monitorNotes.filter(n=>n.id!==id); monitorNoteHistory.delete(id); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorShowNoteList(); });

monitorNoteUndo.addEventListener("click", () => { if(monitorNoteListMode) monitorUndoListDelete(); else monitorUndoNote(); });

monitorNoteRedo.addEventListener("click", () => { if(monitorNoteListMode) monitorRedoListDelete(); else monitorRedoNote(); });

monitorNoteEditor.addEventListener("keydown", (event) => { if(!event.ctrlKey||event.altKey||event.metaKey)return; const key=String(event.key||"").toLowerCase(); if(key==="z"){event.preventDefault(); if(event.shiftKey)monitorRedoNote(); else monitorUndoNote();} else if(key==="y"){event.preventDefault(); monitorRedoNote();} });

monitorNote.addEventListener("keydown", (event) => { if(!monitorNoteListMode||!event.ctrlKey||event.altKey||event.metaKey)return; const key=String(event.key||"").toLowerCase(); if(key==="z"){event.preventDefault(); if(event.shiftKey)monitorRedoListDelete(); else monitorUndoListDelete();} else if(key==="y"){event.preventDefault(); monitorRedoListDelete();} });

let monitorNoteAiBusy = false;

async function organizeMonitorNoteWithAi() {

  if (monitorNoteAiBusy) return;

  monitorNoteAiBusy = true; monitorNoteAi.disabled = true; monitorNoteAi.textContent = "...";

  try {

    if (monitorNoteListMode) {

      const baseline = monitorSerializeNotes();

      const targets = monitorNotes.filter(note => String(note.body || "").trim());

      if (!targets.length) { setMonitorStatus("AI 정리할 메모가 없음", false); return; }

      const response = await actFetch(ORCHESTRATOR_NOTE_AI_URL, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({notes:targets.map(note=>({id:note.id,text:String(note.body||"").trim()}))}) });

      const data = await response.json().catch(() => null);

      if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);

      const cleanedById = new Map((Array.isArray(data.notes)?data.notes:[]).map(item=>[String(item?.id||""),String(item?.text||"").trim()]));

      if (cleanedById.size !== targets.length || targets.some(note=>!cleanedById.get(note.id))) throw new Error("NOTE_AI_BUNDLE_INCOMPLETE");

      if (!monitorNoteListMode || monitorSerializeNotes() !== baseline) { setMonitorStatus("메모 목록이 바뀌어 AI 결과는 적용하지 않음", false); return; }

      const now = Date.now();

      monitorNotes = monitorNotes.map(note => cleanedById.has(note.id) ? {...note, body:cleanedById.get(note.id), title:monitorNoteTitleFromText(cleanedById.get(note.id)), updatedAt:now} : note);

      monitorNoteLocalDirty = true;

      const bundle = monitorSerializeNotes();

      const saved = await monitorNoteNative({ type:"setSharedNote", text:bundle });

      if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");

      monitorNoteLastSharedText = bundle; monitorNoteLocalDirty = false; monitorRenderNoteList();

      setMonitorStatus(`전체 메모 AI 정리 완료 ${targets.length}개${data.profile_id ? ` - ${String(data.profile_id)}` : ""}`, true);

      return;

    }

    const source = String(monitorSideNoteText.value || "").trim();

    if (!source) { setMonitorStatus("AI 정리할 메모가 없음", false); return; }

    const response = await actFetch(ORCHESTRATOR_NOTE_AI_URL, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({text:source}) });

    const data = await response.json().catch(() => null);

    if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);

    if (String(monitorSideNoteText.value || "").trim() !== source) { setMonitorStatus("메모가 바뀌어 AI 결과는 적용하지 않음", false); return; }

    const cleaned = String(data.text || "").trim(); if (!cleaned) throw new Error("NOTE_AI_EMPTY_RESULT");

    monitorRecordUndoBeforeEdit(); monitorSideNoteText.value = cleaned; monitorUpdateActiveFromEditor(); monitorSyncHistoryButtons(); syncMonitorSideNote();

    const bundle = monitorSerializeNotes();

    const saved = await monitorNoteNative({ type:"setSharedNote", text:bundle });

    if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");

    monitorNoteLastSharedText = bundle; monitorNoteLocalDirty = false;

    setMonitorStatus(`메모 AI 정리 완료 - ${String(data.profile_id||"")}`, true);

  } catch (error) { setMonitorStatus(`메모 AI 실패 - ${monitorRoleAdminErrorText(error?.message || error)}`, false); }

  finally { monitorNoteAiBusy = false; monitorNoteAi.disabled = false; monitorNoteAi.textContent = "AI"; }

}

monitorNoteAi.addEventListener("click", organizeMonitorNoteWithAi);

function monitorNoteNative(message) {

  return monitorNative(message);

}

let monitorNoteLastSharedText = "";

let monitorNoteLocalDirty = false;

let monitorNoteReady = false;

let monitorNoteViewRevision = "";

let monitorNoteViewRemoteApplying = false;

let monitorNoteViewSaveTimer = 0;

let monitorNoteViewSyncBusy = false;

function monitorNoteScrollRatio() {

  const maxScroll = Math.max(0, monitorSideNoteText.scrollHeight - monitorSideNoteText.clientHeight);

  return maxScroll > 0 ? Math.max(0, Math.min(1, monitorSideNoteText.scrollTop / maxScroll)) : 0;

}

async function refreshMonitorSharedNoteView() {

  if (monitorNoteViewSyncBusy) return;

  if (document.activeElement === monitorSideNoteText) return;

  monitorNoteViewSyncBusy = true;

  try {

    const result = await monitorNoteNative({ type: "getSharedMonitorNoteView" }).catch(() => null);

    const revision = String(result?.revision || "");

    if (!result?.ok || !revision || revision === monitorNoteViewRevision) return;

    monitorNoteViewRevision = revision;

    const ratio = Math.max(0, Math.min(1, Number(result.ratio) || 0));

    const maxScroll = Math.max(0, monitorSideNoteText.scrollHeight - monitorSideNoteText.clientHeight);

    const target = maxScroll * ratio;

    if (Math.abs(monitorSideNoteText.scrollTop - target) > 2) {

      monitorNoteViewRemoteApplying = true;

      monitorSideNoteText.scrollTop = target;

      requestAnimationFrame(() => { monitorNoteViewRemoteApplying = false; });

    }

  } finally { monitorNoteViewSyncBusy = false; }

}

monitorSideNoteText.addEventListener("scroll", (event) => {

  if (monitorNoteViewRemoteApplying || !event.isTrusted) return;

  clearTimeout(monitorNoteViewSaveTimer);

  monitorNoteViewSaveTimer = setTimeout(async () => {

    const result = await monitorNoteNative({ type: "setSharedMonitorNoteView", ratio: String(monitorNoteScrollRatio()) }).catch(() => null);

    if (result?.ok && result.revision) monitorNoteViewRevision = String(result.revision);

  }, 80);

});

async function refreshMonitorSharedNote() {

  if (monitorNoteDragState?.active) return;

  const result = await monitorNoteNative({ type: "getSharedNote" }).catch(() => null);

  if (!result?.ok) return;

  const text = String(result.text || "");

  if (monitorNoteReady && text === monitorSerializeNotes()) { monitorNoteLastSharedText = text; monitorNoteLocalDirty = false; return; }

  const editorActive = document.activeElement === monitorSideNoteText;

  if (monitorNoteReady && editorActive && text !== monitorSerializeNotes()) return;

  const safeToReplace = !monitorNoteLocalDirty || monitorSerializeNotes() === monitorNoteLastSharedText;

  if (!monitorNoteReady || safeToReplace) {

    const previousActive = monitorActiveNoteId;

    monitorNotes = monitorParseNoteBundle(text);

    monitorNoteLastSharedText = text;

    monitorNoteLocalDirty = false;

    if (!monitorNoteReady || monitorNoteListMode || !monitorNotes.some(n=>n.id===previousActive)) monitorShowNoteList();

    else { monitorOpenNote(previousActive, false); }

    syncMonitorSideNote();

    if (text && !text.startsWith(MONITOR_NOTE_BUNDLE_PREFIX)) { monitorNoteLocalDirty = true; monitorQueueNoteBundleSave(); }

  }

  monitorNoteReady = true;

}

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

