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

  const direct = monitorDirectEndpointGenerationState(endpoint);

  if (direct !== null) return direct;

  const metadata = endpoint?.metadata || {};

  if (metadata.generating === true || endpoint?.generating === true) return true;
  if (metadata.generating === false || endpoint?.generating === false) return false;

  const generationState = String(metadata.generation_state || endpoint?.generation_state || "").trim().toUpperCase();

  if (["GENERATING", "RUNNING", "WORKING", "ACTIVE"].includes(generationState)) return true;
  if (generationState) return false;

  const interactionState = String(metadata.interaction_state || endpoint?.interaction_state || "").trim().toUpperCase();

  return interactionState === "WORKING";

}

function monitorConversationIsGenerating(conversationKey, state) {

  const key = String(conversationKey || "").trim();

  if (!key) return false;

  const directState = monitorDirectConversationGenerationState(key);

  const actActive = (Array.isArray(state?.endpoints) ? state.endpoints : []).some((endpoint) => {

    if (String(endpoint?.conversation_key || "").trim() !== key || String(endpoint?.presence_state || "").toUpperCase() !== "OPEN") return false;

    return monitorEndpointGenerationIsActive(endpoint);

  });

  return directState === true || actActive;

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

  const endpoint=monitorOpenEndpointForHwnd(hwnd,state);

  if(!endpoint)return false;

  return monitorEndpointGenerationIsActive(endpoint);

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

let monitorBctSelectedNodeKey = "";

const monitorSelectedHwnds = new Set();

let monitorSharedSelectionRevision = "";

let monitorSharedSelectionSyncBusy = false;

let monitorSharedSelectionWriteSerial = Promise.resolve();

let monitorSharedSelectionWritePending = 0;

function compareMonitorSharedSelectionRevision(leftValue, rightValue) {

  const left = String(leftValue || "").trim();

  const right = String(rightValue || "").trim();

  if (left === right) return 0;

  if (!left) return -1;

  if (!right) return 1;

  if (/^\d+$/.test(left) && /^\d+$/.test(right)) {

    const a = left.replace(/^0+/, "") || "0";

    const b = right.replace(/^0+/, "") || "0";

    if (a.length !== b.length) return a.length > b.length ? 1 : -1;

    return a > b ? 1 : -1;

  }

  return left > right ? 1 : -1;

}

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
    const selected = Boolean(monitorBctSelectedNodeKey)
      && monitorBctNodeSelectionKey(row.dataset) === monitorBctSelectedNodeKey;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");
  }
}

function monitorBctNodeSelectionKey(value) {
  const instanceId = String(value?.instanceId || "").trim();
  const sessionId = String(value?.sessionId || "").trim();
  const windowId = String(value?.windowId || "").trim();
  const tabId = String(value?.tabId || "").trim();
  return instanceId && sessionId && windowId && tabId
    ? `${instanceId}:${sessionId}:${windowId}:${tabId}`
    : "";
}

function applyMonitorBctNodeHighlight(hwnd) {
  monitorBctNodeHighlightedHwnd = String(hwnd || "");
  applyMonitorWindowHighlight(hwnd, { bctNode: true });
  syncMonitorBctNodeTargetHighlight();
}

function applyMonitorWindowHighlight(hwnd, options = {}) {

  const nextHwnd = String(hwnd || "");

  const changed = nextHwnd !== monitorHighlightedHwnd;

  if (!options.bctNode && !options.preserve && !options.remote) {
    monitorBctNodeHighlightedHwnd = "";
    monitorBctSelectedNodeKey = "";
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

function monitorEndpointFreshnessState(endpoint) {

  if (String(endpoint?.presence_state || "").toUpperCase() !== "OPEN") return "disconnected";

  return "connected";

}

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

function monitorWorkSymbol(work, connection, alertDetail = null) {

  const value = String(work || "").toLowerCase();

  if (alertDetail) return { symbol: "", label: alertDetail.label, tone: alertDetail.tone };

  if (["running", "working", "busy", "executing", "in_progress"].includes(value)) return { symbol: "", label: "실행" };

  if (["waiting_resource", "waiting", "paused", "queued", "pending"].includes(value)) return { symbol: "", label: "대기" };

  if (connection === "disconnected" || ["offline", "stopped", "cancelled", "canceled"].includes(value)) return { symbol: "", label: "사용자 조치 필요" };

  if (["succeeded", "completed", "complete", "done"].includes(value)) return { symbol: "", label: "완료" };

  return { symbol: "", label: "유휴" };

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

const MONITOR_GHOST_TAIL_MAX = 5;

const MONITOR_GHOST_TEXT_MAX = 1200;

const monitorGhostCache = new Map();

const monitorHiddenGhosts = new Set();

let monitorGhostStorageReady = false;

let monitorClosedConversationPickerOpen = false;

let monitorRebootSnapshot = { captured_at_ms:0, items:[] };

let monitorRebootSnapshotReady = false;

let monitorRebootRestoreActive = false;

const monitorRebootRestorePendingKeys = new Set();

function monitorGhostBoundText(value, max = MONITOR_GHOST_TEXT_MAX) { return String(value || "").slice(0, max); }

function monitorGhostTime(value) { const ms = Date.parse(String(value || "")); return Number.isFinite(ms) ? ms : 0; }

function monitorGhostWorkerId(worker) { return `CHATGPT:${String(worker?.profile_id || "").toUpperCase()}:${String(worker?.role || "").toUpperCase()}`; }

function monitorGhostUsage(metadata = {}, previous = {}) {

  const src = { ...(metadata || {}), ...(metadata?.telemetry || {}), ...(metadata?.usage || {}), ...(metadata?.usage_telemetry || {}) };

  const num = (...keys) => { for (const key of keys) { const n = Number(src?.[key]); if (Number.isFinite(n) && n >= 0) return n; } return null; };

  const next = { user_count:num("user_count","user_message_count","userMessages"), assistant_count:num("assistant_count","assistant_message_count","assistantMessages"), turns:num("turns","turn_count","message_turns"), rendered_chars:num("rendered_chars","rendered_text_chars","renderedChars"), scroll_height:num("scroll_height","scrollHeight"), viewport_height:num("viewport_height","viewportHeight"), screen_lengths:num("screen_lengths","screenLength","screen_lengths_count"), js_heap_used_mb:num("js_heap_used_mb","jsHeapUsedMb"), js_heap_limit_mb:num("js_heap_limit_mb","jsHeapLimitMb"), event_loop_lag_ms:num("event_loop_lag_ms","eventLoopLagMs") };

  if (next.turns == null && next.user_count != null && next.assistant_count != null) next.turns = Math.min(next.user_count, next.assistant_count);

  if (next.screen_lengths == null && next.scroll_height != null && next.viewport_height > 0) next.screen_lengths = next.scroll_height / next.viewport_height;

  for (const key of Object.keys(next)) if (next[key] == null && previous?.[key] != null) next[key] = previous[key];

  return next;

}

function monitorGhostTail(metadata = {}, previous = []) {

  const source = Array.isArray(metadata?.conversation_tail) ? metadata.conversation_tail : previous;

  return (Array.isArray(source) ? source : []).slice(-MONITOR_GHOST_TAIL_MAX).map((item) => ({ role:String(item?.role || "").slice(0,16), text:monitorGhostBoundText(item?.text) }));

}

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

function monitorGhostNumericTime(value) {

  const n = Number(value); if (Number.isFinite(n) && n > 0) return n < 1e12 ? n * 1000 : n;

  return monitorGhostTime(value);

}

function monitorGhostConversationTime(metadata = {}, previous = 0) {

  const values = [metadata?.last_conversation_at, metadata?.last_message_at, metadata?.conversation_updated_at, metadata?.last_message_timestamp].map(monitorGhostNumericTime).filter(Boolean);

  const tail = Array.isArray(metadata?.conversation_tail) ? metadata.conversation_tail : [];

  for (const item of tail) for (const key of ["created_at","timestamp","time","at"]) { const ms = monitorGhostNumericTime(item?.[key]); if (ms) values.push(ms); }

  return values.length ? Math.max(...values) : Number(previous || 0);

}

function monitorGhostObservationTime(endpoint = {}, metadata = {}, previous = 0) {

  const values = [monitorGhostTime(endpoint?.last_seen_at), monitorGhostNumericTime(metadata?.reported_observed_at), Number(previous || 0)].filter(Boolean);

  return values.length ? Math.max(...values) : 0;

}

function monitorGhostTaskHistory(worker, state, previous = []) {

  const owner = monitorGhostWorkerId(worker); const tasks = Array.isArray(state?.tasks) ? state.tasks : [];

  const current = tasks.filter((task) => String(task?.assigned_agent || "").trim().toUpperCase() === owner).map((task) => {

    const at = Math.max(monitorGhostTime(task?.completed_at), monitorGhostTime(task?.finished_at), monitorGhostTime(task?.verified_at), monitorGhostTime(task?.updated_at), monitorGhostTime(task?.created_at));

    const title = monitorGhostMeaningfulTitle(task?.title, ""); if (!title) return null;

    const status = String(task?.status || "").toUpperCase(); const result = monitorGhostBoundText(task?.result ?? task?.completion_report?.result ?? "", 180).replace(/\s+/g," ").trim();

    return { id:String(task?.id || ""), at, text:`${title}${status ? ` [${status}]` : ""}${result ? ` · ${result}` : ""}` };

  }).filter(Boolean);

  const merged = [...(Array.isArray(previous) ? previous : []), ...current].filter((item) => item?.text);

  const dedup = new Map(); for (const item of merged) dedup.set(`${item.id || "event"}:${item.at || 0}:${item.text}`, item);

  return [...dedup.values()].sort((a,b) => Number(a.at||0)-Number(b.at||0)).slice(-5);

}

function monitorContextTitleRecord(key) { return key ? (monitorContextTitles.get(String(key)) || {}) : {}; }

function monitorTitlesEquivalent(observed, requested){

  const a=String(observed||"").replace(/\s+/g," ").trim(), b=String(requested||"").replace(/\s+/g," ").trim();

  return a===b||[" - ChatGPT"," | ChatGPT"," — ChatGPT"].some((suffix)=>a===b+suffix);

}

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

function monitorContextTitleSignature(input){return JSON.stringify([input.browser_title,input.task_title,input.project_name,input.history.slice(-3)]);}

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

function monitorGhostAuthoritativeLocation(worker, state, endpoint = null, previous = {}) {

  const station = stationForMonitorWorker(worker, state); const meta = monitorStationMetadata(station); const em = endpoint?.metadata || {};

  const d = Number(station?.desktop_id ?? station?.desktop_index ?? meta.desktop_id ?? meta.desktop_index ?? em.desktop_id ?? em.desktop_index);

  const sl = Number(station?.slot_index ?? meta.slot_index ?? em.slot_index);

  return { desktop:Number.isInteger(d)&&d>0?d:(previous?.desktop ?? null), slot:Number.isInteger(sl)&&sl>0?sl:(previous?.slot ?? null) };

}

function monitorGhostAgeing(ghost, now = Date.now()) {

  const u = ghost?.usage || {}; let score = 0;

  // Conversation handoff readiness heuristic, not browser performance and not actual model context %.

  // rendered_chars is an incremental cumulative estimate; turns is a low-cost secondary signal.

  if (u.rendered_chars != null) score += Math.min(70, Math.sqrt(Math.max(0, u.rendered_chars) / 100000) * 70);

  if (u.turns != null) score += Math.min(30, Math.sqrt(Math.max(0, u.turns) / 120) * 30);

  return Math.max(0, Math.min(100, Math.round(score)));

}

function monitorGhostArchiveAgeing(ghost) {

  const u = ghost?.usage || {}; let score = 0;

  // Preserve the previous ghost auto-hide behavior independently from handoff readiness.

  if (u.turns != null) score += Math.min(45, Math.sqrt(Math.max(0, u.turns) / 45) * 45);

  if (u.rendered_chars != null) score += Math.min(35, Math.sqrt(Math.max(0, u.rendered_chars) / 150000) * 35);

  if (u.screen_lengths != null) score += Math.min(20, Math.sqrt(Math.max(0, u.screen_lengths) / 35) * 20);

  return Math.max(0, Math.min(100, Math.round(score)));

}

