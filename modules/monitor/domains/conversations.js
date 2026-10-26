//@@FN_START:applyMonitorConversationGroupVisual
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
//@@FN_END:applyMonitorConversationGroupVisual

//@@FN_START:classifyMonitorWorker
function classifyMonitorWorker(worker) { return globalThis.MonitorDomainAPIs["conversations"]["classifyMonitorWorker"].apply(this, arguments); }
//@@FN_END:classifyMonitorWorker

//@@FN_START:cleanMonitorWorkerName
function cleanMonitorWorkerName(worker) { return globalThis.MonitorDomainAPIs["conversations"]["cleanMonitorWorkerName"].apply(this, arguments); }
//@@FN_END:cleanMonitorWorkerName

//@@FN_START:clearMonitorWorkerOrderTargets
function clearMonitorWorkerOrderTargets() {

  for(const row of monitorWorkers.querySelectorAll(".monitor-worker-row.monitor-worker-order-target-before,.monitor-worker-row.monitor-worker-order-target-after")) row.classList.remove("monitor-worker-order-target-before","monitor-worker-order-target-after");

}
//@@FN_END:clearMonitorWorkerOrderTargets

//@@FN_START:closeMonitorBctRenameEditor
function closeMonitorBctRenameEditor() {
  if (!monitorBctRenameEditor || monitorBctRenameEditor.busy) return;
  monitorBctRenameEditor.overlay.remove();
  monitorBctRenameEditor = null;
}
//@@FN_END:closeMonitorBctRenameEditor

//@@FN_START:compareMonitorWorkers
function compareMonitorWorkers(a, b, state) {

  const ak = monitorWorkerSortKey(a, state), bk = monitorWorkerSortKey(b, state);

  for (let i = 0; i < ak.length; i += 1) {

    if (ak[i] < bk[i]) return -1;

    if (ak[i] > bk[i]) return 1;

  }

  return 0;

}
//@@FN_END:compareMonitorWorkers

//@@FN_START:flushDeferredMonitorWorkerRender
function flushDeferredMonitorWorkerRender() {

  if (monitorWorkerPointerInteractionActive || !monitorDeferredWorkerRenderState) return;

  const deferred = monitorDeferredWorkerRenderState;

  monitorDeferredWorkerRenderState = null;

  renderWorkers(deferred);

}
//@@FN_END:flushDeferredMonitorWorkerRender

//@@FN_START:initializeMonitorWorkerOrderStorage
function initializeMonitorWorkerOrderStorage() { chrome.storage.local.get([MONITOR_WORKER_ORDER_KEY],(data)=>{const raw=data?.[MONITOR_WORKER_ORDER_KEY]||{};for(const [id,keys] of Object.entries(raw))monitorWorkerOrderByDesktop.set(id,Array.isArray(keys)?keys.map(String):[]);monitorWorkerOrderReady=true;if(monitorLastAiState)renderWorkers(monitorLastAiState);}); }
//@@FN_END:initializeMonitorWorkerOrderStorage

//@@FN_START:installMonitorBctManagerLongPress
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
//@@FN_END:installMonitorBctManagerLongPress

//@@FN_START:isMonitorVisibleWorker
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
//@@FN_END:isMonitorVisibleWorker

//@@FN_START:monitorAuthoritativeConversationForTask
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
//@@FN_END:monitorAuthoritativeConversationForTask

//@@FN_START:monitorBctCurrentSessionHwnd
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
//@@FN_END:monitorBctCurrentSessionHwnd

//@@FN_START:monitorBctDisplaySessionHwnd
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
//@@FN_END:monitorBctDisplaySessionHwnd

//@@FN_START:monitorBctPointInsideScopeHeading
function monitorBctPointInsideScopeHeading(clientX, clientY) {
  return [...(monitorWorkers?.querySelectorAll?.(".monitor-bct-scope-heading") || [])].some((heading) => {
    const rect = heading.getBoundingClientRect();
    return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
  });
}
//@@FN_END:monitorBctPointInsideScopeHeading

//@@FN_START:monitorBctProjectionHasUnresolvedLineage
function monitorBctProjectionHasUnresolvedLineage() {
  return Array.isArray(monitorBctWindowNodesCache) && monitorBctWindowNodesCache.some((node) =>
    !monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId)
  );
}
//@@FN_END:monitorBctProjectionHasUnresolvedLineage

//@@FN_START:monitorBctRenameErrorText
function monitorBctRenameErrorText(error) { return globalThis.MonitorDomainAPIs["conversations"]["monitorBctRenameErrorText"].apply(this, arguments); }
//@@FN_END:monitorBctRenameErrorText

//@@FN_START:monitorBctRoleTagsFromText
function monitorBctRoleTagsFromText(value) { return globalThis.MonitorDomainAPIs["conversations"]["monitorBctRoleTagsFromText"].apply(this, arguments); }
//@@FN_END:monitorBctRoleTagsFromText

//@@FN_START:monitorClosedConversationContextTitle
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
//@@FN_END:monitorClosedConversationContextTitle

//@@FN_START:monitorClosedConversationPreviousLocation
function monitorClosedConversationPreviousLocation(ghost) {

  const d=Number(ghost?.desktop), s=Number(ghost?.slot);

  return Number.isInteger(d)&&d>0&&Number.isInteger(s)&&s>0 ? `D${d}-${s}` : "알 수 없음";

}
//@@FN_END:monitorClosedConversationPreviousLocation

//@@FN_START:monitorCodexWorkersFromState
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
//@@FN_END:monitorCodexWorkersFromState

//@@FN_START:monitorConversationGroupVisual
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
//@@FN_END:monitorConversationGroupVisual

//@@FN_START:monitorConversationKeysForHwnd
function monitorConversationKeysForHwnd(hwnd,state=monitorLastAiState) {

  const target=String(hwnd||""); if(!target||!state)return [];

  return monitorWorkersForState(state).filter((worker)=>String(endpointOsWindowHandle(endpointForMonitorWorker(worker,state))||"")===target).map((worker)=>String(worker?.conversation_key||"").trim()).filter(Boolean);

}
//@@FN_END:monitorConversationKeysForHwnd

//@@FN_START:monitorConversationStateSignature
function monitorConversationStateSignature(state) { return globalThis.MonitorDomainAPIs["conversations"]["monitorConversationStateSignature"].apply(this, arguments); }
//@@FN_END:monitorConversationStateSignature

//@@FN_START:monitorDirectConversationGenerationState
function monitorDirectConversationGenerationState(conversationKey, now = Date.now()) {

  const key=String(conversationKey||"").trim();

  const tabStates=[...monitorDirectGenerationByTab.values()].filter((item)=>item.conversationKey===key&&now-Number(item.at||0)<=MONITOR_DIRECT_GENERATION_TTL_MS);

  if(tabStates.length) return tabStates.some((item)=>item.generating===true);

  const item=monitorDirectGenerationByConversation.get(key);

  if (!item || now-Number(item.at||0)>MONITOR_DIRECT_GENERATION_TTL_MS) return null;

  return item.generating===true;

}
//@@FN_END:monitorDirectConversationGenerationState

//@@FN_START:monitorExactConversationWindow
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
//@@FN_END:monitorExactConversationWindow

//@@FN_START:monitorGhostAgeing
function monitorGhostAgeing(ghost, now = Date.now()) {

  const u = ghost?.usage || {}; let score = 0;

  // Conversation handoff readiness heuristic, not browser performance and not actual model context %.

  // rendered_chars is an incremental cumulative estimate; turns is a low-cost secondary signal.

  if (u.rendered_chars != null) score += Math.min(70, Math.sqrt(Math.max(0, u.rendered_chars) / 100000) * 70);

  if (u.turns != null) score += Math.min(30, Math.sqrt(Math.max(0, u.turns) / 120) * 30);

  return Math.max(0, Math.min(100, Math.round(score)));

}
//@@FN_END:monitorGhostAgeing

//@@FN_START:monitorGhostArchiveAgeing
function monitorGhostArchiveAgeing(ghost) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostArchiveAgeing"].apply(this, arguments); }
//@@FN_END:monitorGhostArchiveAgeing

//@@FN_START:monitorGhostAuthoritativeLocation
function monitorGhostAuthoritativeLocation(worker, state, endpoint = null, previous = {}) {

  const station = stationForMonitorWorker(worker, state); const meta = monitorStationMetadata(station); const em = endpoint?.metadata || {};

  const d = Number(station?.desktop_id ?? station?.desktop_index ?? meta.desktop_id ?? meta.desktop_index ?? em.desktop_id ?? em.desktop_index);

  const sl = Number(station?.slot_index ?? meta.slot_index ?? em.slot_index);

  return { desktop:Number.isInteger(d)&&d>0?d:(previous?.desktop ?? null), slot:Number.isInteger(sl)&&sl>0?sl:(previous?.slot ?? null) };

}
//@@FN_END:monitorGhostAuthoritativeLocation

//@@FN_START:monitorGhostBoundText
function monitorGhostBoundText(value, max = MONITOR_GHOST_TEXT_MAX) { return String(value || "").slice(0, max); }
//@@FN_END:monitorGhostBoundText

//@@FN_START:monitorGhostCanAutoHide
function monitorGhostCanAutoHide(ghost, state, now = Date.now()) {

  if (monitorGhostProtected(ghost) || monitorGhostValidLease(ghost,state,now) || monitorGhostArchiveAgeing(ghost) < 80) return false;

  const status=String(ghost?.task_status || ghost?.work_status || "").toUpperCase(); if (!["SUCCEEDED","COMPLETED","COMPLETE","DONE","IDLE","AVAILABLE"].includes(status)) return false;

  const idleSince=Number(ghost?.completed_or_idle_ms || 0); return idleSince > 0 && now-idleSince >= 24*60*60*1000;

}
//@@FN_END:monitorGhostCanAutoHide

//@@FN_START:monitorGhostConversationTime
function monitorGhostConversationTime(metadata = {}, previous = 0) {

  const values = [metadata?.last_conversation_at, metadata?.last_message_at, metadata?.conversation_updated_at, metadata?.last_message_timestamp].map(monitorGhostNumericTime).filter(Boolean);

  const tail = Array.isArray(metadata?.conversation_tail) ? metadata.conversation_tail : [];

  for (const item of tail) for (const key of ["created_at","timestamp","time","at"]) { const ms = monitorGhostNumericTime(item?.[key]); if (ms) values.push(ms); }

  return values.length ? Math.max(...values) : Number(previous || 0);

}
//@@FN_END:monitorGhostConversationTime

//@@FN_START:monitorGhostMeaningfulTitle
function monitorGhostMeaningfulTitle(value, previous = "") {

  const text = monitorGhostBoundText(value, 500).trim();

  if (!text) return previous || "";

  if (/^(?:waiting|available|idle|paused|pending|queued|대기|유휴)$/i.test(text)) return previous || "";

  return text;

}
//@@FN_END:monitorGhostMeaningfulTitle

//@@FN_START:monitorGhostNumericTime
function monitorGhostNumericTime(value) {

  const n = Number(value); if (Number.isFinite(n) && n > 0) return n < 1e12 ? n * 1000 : n;

  return monitorGhostTime(value);

}
//@@FN_END:monitorGhostNumericTime

//@@FN_START:monitorGhostObservationTime
function monitorGhostObservationTime(endpoint = {}, metadata = {}, previous = 0) {

  const values = [monitorGhostTime(endpoint?.last_seen_at), monitorGhostNumericTime(metadata?.reported_observed_at), Number(previous || 0)].filter(Boolean);

  return values.length ? Math.max(...values) : 0;

}
//@@FN_END:monitorGhostObservationTime

//@@FN_START:monitorGhostPersist
function monitorGhostPersist(immediate = false) {

  if (!monitorGhostStorageReady) return;

  const write = () => { monitorGhostPersistTimer = 0; const cache=[...monitorGhostCache.values()].sort((a,b)=>Number(b?.last_activity_ms||0)-Number(a?.last_activity_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX); chrome.storage.local.set({ [MONITOR_GHOST_CACHE_KEY]:cache, [MONITOR_GHOST_HIDDEN_KEY]:[...monitorHiddenGhosts].slice(0,MONITOR_GHOST_CACHE_MAX) }); };

  if (immediate) { if (monitorGhostPersistTimer) clearTimeout(monitorGhostPersistTimer); write(); return; }

  if (!monitorGhostPersistTimer) monitorGhostPersistTimer = setTimeout(write, 5000);

}
//@@FN_END:monitorGhostPersist

//@@FN_START:monitorGhostProtected
function monitorGhostProtected(ghost) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostProtected"].apply(this, arguments); }
//@@FN_END:monitorGhostProtected

//@@FN_START:monitorGhostTail
function monitorGhostTail(metadata = {}, previous = []) {

  const source = Array.isArray(metadata?.conversation_tail) ? metadata.conversation_tail : previous;

  return (Array.isArray(source) ? source : []).slice(-MONITOR_GHOST_TAIL_MAX).map((item) => ({ role:String(item?.role || "").slice(0,16), text:monitorGhostBoundText(item?.text) }));

}
//@@FN_END:monitorGhostTail

//@@FN_START:monitorGhostTaskForWorker
function monitorGhostTaskForWorker(worker, state) {

  const tasks = Array.isArray(state?.tasks) ? state.tasks : []; const station = stationForMonitorWorker(worker, state);

  const currentId = String(station?.current_task_id || worker?.current_task_id || "");

  if (currentId) { const exact = tasks.find((task) => String(task?.id || "") === currentId); if (exact) return exact; }

  const owner = monitorGhostWorkerId(worker);

  return tasks.filter((task) => String(task?.assigned_agent || "").trim().toUpperCase() === owner).sort((a,b) => Math.max(monitorGhostTime(b?.completed_at),monitorGhostTime(b?.updated_at),monitorGhostTime(b?.created_at)) - Math.max(monitorGhostTime(a?.completed_at),monitorGhostTime(a?.updated_at),monitorGhostTime(a?.created_at)))[0] || null;

}
//@@FN_END:monitorGhostTaskForWorker

//@@FN_START:monitorGhostTaskHistory
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
//@@FN_END:monitorGhostTaskHistory

//@@FN_START:monitorGhostTime
function monitorGhostTime(value) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostTime"].apply(this, arguments); }
//@@FN_END:monitorGhostTime

//@@FN_START:monitorGhostUsage
function monitorGhostUsage(metadata = {}, previous = {}) {

  const src = { ...(metadata || {}), ...(metadata?.telemetry || {}), ...(metadata?.usage || {}), ...(metadata?.usage_telemetry || {}) };

  const num = (...keys) => { for (const key of keys) { const n = Number(src?.[key]); if (Number.isFinite(n) && n >= 0) return n; } return null; };

  const next = { user_count:num("user_count","user_message_count","userMessages"), assistant_count:num("assistant_count","assistant_message_count","assistantMessages"), turns:num("turns","turn_count","message_turns"), rendered_chars:num("rendered_chars","rendered_text_chars","renderedChars"), scroll_height:num("scroll_height","scrollHeight"), viewport_height:num("viewport_height","viewportHeight"), screen_lengths:num("screen_lengths","screenLength","screen_lengths_count"), js_heap_used_mb:num("js_heap_used_mb","jsHeapUsedMb"), js_heap_limit_mb:num("js_heap_limit_mb","jsHeapLimitMb"), event_loop_lag_ms:num("event_loop_lag_ms","eventLoopLagMs") };

  if (next.turns == null && next.user_count != null && next.assistant_count != null) next.turns = Math.min(next.user_count, next.assistant_count);

  if (next.screen_lengths == null && next.scroll_height != null && next.viewport_height > 0) next.screen_lengths = next.scroll_height / next.viewport_height;

  for (const key of Object.keys(next)) if (next[key] == null && previous?.[key] != null) next[key] = previous[key];

  return next;

}
//@@FN_END:monitorGhostUsage

//@@FN_START:monitorGhostValidLease
function monitorGhostValidLease(ghost, state, now = Date.now()) {

  const leases = Array.isArray(state?.task_leases) ? state.task_leases : []; const taskId = String(ghost?.task_id || ""); const workerId = String(ghost?.worker_id || "").trim().toUpperCase();

  return leases.some((lease) => monitorGhostTime(lease?.expires_at) > now && (taskId ? String(lease?.task_id || "") === taskId : Boolean(workerId) && String(lease?.owner || "").trim().toUpperCase() === workerId));

}
//@@FN_END:monitorGhostValidLease

//@@FN_START:monitorGhostWorkerId
function monitorGhostWorkerId(worker) { return globalThis.MonitorDomainAPIs["conversations"]["monitorGhostWorkerId"].apply(this, arguments); }
//@@FN_END:monitorGhostWorkerId

//@@FN_START:monitorLiveRoleForConversation
function monitorLiveRoleForConversation(conversationKey, state, hwnd = "") {

  const key = String(conversationKey || "").trim();

  const physicalHwnd=String(hwnd||"").trim();

  if (!key || String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return "";

  const nodes=(Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[]).filter((node)=>String(node?.current_conversation_key||"").trim()===key&&String(node?.identity_authority||"")==="ACT_TAB_CHAT"&&String(node?.location_authority||"")==="ACT_NATIVE_OBSERVER"&&(!physicalHwnd||String(node?.hwnd||"").trim()===physicalHwnd));

  const roles=[...new Set(nodes.map((node)=>String(node?.role||"").toUpperCase()).filter(Boolean))];

  return roles.length===1?roles[0]:"";

}
//@@FN_END:monitorLiveRoleForConversation

//@@FN_START:monitorLlmWorkersFromState
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
//@@FN_END:monitorLlmWorkersFromState

//@@FN_START:monitorMoveWorkerOrderKey
function monitorMoveWorkerOrderKey(key, sourceDesktopId, targetDesktopId) {

  const k=String(key||"").trim(), target=String(targetDesktopId||"").trim(); if(!k||!target)return;

  monitorRemoveWorkerOrderKey(k); const next=[...(monitorWorkerOrderByDesktop.get(target)||[])]; next.push(k); monitorWorkerOrderByDesktop.set(target,[...new Set(next)]); monitorPersistWorkerOrder();

}
//@@FN_END:monitorMoveWorkerOrderKey

//@@FN_START:monitorPersistWorkerOrder
function monitorPersistWorkerOrder() {

  if (!monitorWorkerOrderReady) return;

  const data={}; for(const [desktopId,keys] of monitorWorkerOrderByDesktop) data[desktopId]=[...new Set((Array.isArray(keys)?keys:[]).filter(Boolean))].slice(0,80);

  chrome.storage.local.set({[MONITOR_WORKER_ORDER_KEY]:data});

}
//@@FN_END:monitorPersistWorkerOrder

//@@FN_START:monitorRemoveWorkerOrderKey
function monitorRemoveWorkerOrderKey(key) {

  const k=String(key||"").trim(); if(!k)return;

  for(const [id,keys] of monitorWorkerOrderByDesktop){const next=(keys||[]).filter(x=>String(x)!==k); if(next.length!==(keys||[]).length)monitorWorkerOrderByDesktop.set(id,next);}

}
//@@FN_END:monitorRemoveWorkerOrderKey

//@@FN_START:monitorReorderWorkerKey
function monitorReorderWorkerKey(desktopId, key, targetKey, after=false) {

  const id=String(desktopId||"").trim(), k=String(key||"").trim(), t=String(targetKey||"").trim(); if(!id||!k||!t||k===t)return false;

  const current=[...(monitorWorkerOrderByDesktop.get(id)||[])].filter(x=>x!==k); let index=current.indexOf(t); if(index<0)return false; if(after)index+=1; current.splice(index,0,k); monitorSetWorkerOrder(id,current); return true;

}
//@@FN_END:monitorReorderWorkerKey

//@@FN_START:monitorResolvedWorkerHwnd
function monitorResolvedWorkerHwnd(worker, state, resolvedLocation = null) {

  const canonical = monitorCanonicalPhysicalLocation(worker, state);

  const value = String(canonical?.hwnd || resolvedLocation?.hwnd || "").trim();

  return /^\d+$/.test(value) && value !== "0" ? value : "";

}
//@@FN_END:monitorResolvedWorkerHwnd

//@@FN_START:monitorSelectedRoleWorker
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
//@@FN_END:monitorSelectedRoleWorker

//@@FN_START:monitorSetWorkerOrder
function monitorSetWorkerOrder(desktopId, keys) {

  const id=String(desktopId||"").trim(); if(!id)return;

  monitorWorkerOrderByDesktop.set(id,[...new Set((Array.isArray(keys)?keys:[]).map(String).filter(Boolean))]);

  monitorPersistWorkerOrder();

}
//@@FN_END:monitorSetWorkerOrder

//@@FN_START:monitorTurnWorkerOff
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
//@@FN_END:monitorTurnWorkerOff

//@@FN_START:monitorVisualConversationForHwnd
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
//@@FN_END:monitorVisualConversationForHwnd

//@@FN_START:monitorWindowGroupKeyForWorker
function monitorWindowGroupKeyForWorker(worker,state) {

  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return "";

  const projected=monitorActBrowserNode(worker,state);

  const hwnd=String(projected?.hwnd||"").trim();

  const desktopId=String(projected?.desktop_id||"").trim();

  if(String(projected?.location_authority||"")!=="ACT_NATIVE_OBSERVER"||!desktopId) return "";

  return /^\d+$/.test(hwnd)&&hwnd!=="0" ? `desktop:${desktopId}:hwnd:${hwnd}` : "";

}
//@@FN_END:monitorWindowGroupKeyForWorker

//@@FN_START:monitorWorkerContextTitle
function monitorWorkerContextTitle(worker, state, endpoint = null) {

  const current=monitorWorkerMeaningfulTitle(worker,state,endpoint);

  const key=String(worker?.conversation_key||"").trim(), cached=key?monitorGhostCache.get(key):null;

  const previous=(Array.isArray(cached?.history)?cached.history:[]).map((item)=>String(item?.text||"").split(" [")[0].split(" · ")[0].trim()).filter(Boolean).reverse();

  const parts=[]; if(current)parts.push(current); for(const title of previous){if(!parts.includes(title))parts.push(title);if(parts.length>=3)break;}

  return normalizeMonitorWindowTitle(parts.join(" · ").slice(0,72));

}
//@@FN_END:monitorWorkerContextTitle

//@@FN_START:monitorWorkerMeaningfulTitle
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
//@@FN_END:monitorWorkerMeaningfulTitle

//@@FN_START:monitorWorkerReadyForUse
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
//@@FN_END:monitorWorkerReadyForUse

//@@FN_START:monitorWorkerRowOrderTargetAt
function monitorWorkerRowOrderTargetAt(clientX, clientY) {

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.(".monitor-worker-row[data-conversation-key][data-desktop-id]") || null;

}
//@@FN_END:monitorWorkerRowOrderTargetAt

//@@FN_START:monitorWorkerSortKey
function monitorWorkerSortKey(worker, state) {

  const { desktop, slot } = monitorSortLocationParts(worker, state);

  const desktopSort = desktop ?? Number.MAX_SAFE_INTEGER;

  const slotSort = desktop ? (slot ?? Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER;

  const role = String(worker?.role || "").toUpperCase();

  const roleIndex = MONITOR_ROLE_ORDER.includes(role) ? MONITOR_ROLE_ORDER.indexOf(role) : MONITOR_ROLE_ORDER.length;

  return [desktopSort, slotSort, roleIndex, cleanMonitorWorkerName(worker).toUpperCase()];

}
//@@FN_END:monitorWorkerSortKey

//@@FN_START:monitorWorkersForState
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
//@@FN_END:monitorWorkersForState

//@@FN_START:monitorWorkersProjectionForState
function monitorWorkersProjectionForState(state) {
  if (!state || typeof state !== "object") return monitorWorkersForState(state);
  const cached = monitorWorkersProjectionCache.get(state);
  if (cached) return cached;
  const workers = monitorWorkersForState(state);
  monitorWorkersProjectionCache.set(state, workers);
  return workers;
}
//@@FN_END:monitorWorkersProjectionForState

//@@FN_START:openMonitorBctRenameEditor
function openMonitorBctRenameEditor(node, row) {
  if (!monitorBctShell?.renameConversation || !node?.conversationKey || !node?.sessionId) {
    setMonitorStatus("이 창의 정확한 RCC 대화 신원을 확인할 수 없어 이름을 바꾸지 않았습니다.", false, 5000);
    return;
  }
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
  dialog.append(head, facts, titleField.label, scopeField.label, rolesField.label, roleHint, error, actions);
  overlay.append(dialog);
  document.body.append(overlay);
  monitorBctRenameEditor = {
    overlay, dialog, input: titleField.control, scopeInput: scopeField.control,
    rolesInput: rolesField.control, error, recovery, cancel, close, confirm, busy: false,
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
    const title = editor.input.value.trim();
    const scopeName = editor.scopeInput.value.trim();
    const roleTags = monitorBctRoleTagsFromText(editor.rolesInput.value);
    if (!title) {
      editor.error.textContent = "이름을 입력하세요.";
      editor.input.focus();
      return;
    }
    const titleChanged = title !== currentTitle;
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
        displayName: title,
        scopeName,
        roleTags,
      });
      editor.overlay.remove();
      monitorBctRenameEditor = null;
      setMonitorStatus(`대화 정보${titleChanged ? "와 실제 ChatGPT 이름" : ""}을 저장했습니다.`, true, 3500);
      globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 600);
    } catch (renameError) {
      editor.busy = false;
      editor.input.disabled = false;
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
      (titleApplied ? editor.scopeInput : editor.input).focus();
    }
  });
  titleField.control.focus();
  titleField.control.select();
}
//@@FN_END:openMonitorBctRenameEditor

//@@FN_START:performMonitorWorkerRender
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

  if(monitorClosedRecoveryMenu){monitorClosedRecoveryMenu.hidden=!monitorClosedConversationPickerOpen;if(monitorClosedConversationPickerOpen)monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(state));}

}
//@@FN_END:performMonitorWorkerRender

//@@FN_START:refreshMonitorBctBrowserWindowGeometry
async function refreshMonitorBctBrowserWindowGeometry() {
  const ids = [...new Set((Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [])
    .map((node) => Number(node?.windowId)).filter(Number.isInteger))];
  const observedAt = Date.now();
  const rows = await Promise.all(ids.map(async (windowId) => {
    try {
      const browserWindow = await chrome.windows.get(windowId, { populate: false });
      return {
        windowId, observedAt,
        left: Number(browserWindow?.left), top: Number(browserWindow?.top),
        width: Number(browserWindow?.width), height: Number(browserWindow?.height),
        state: String(browserWindow?.state || "normal"), focused: browserWindow?.focused === true,
      };
    } catch (_) { return null; }
  }));
  monitorBctBrowserWindows = new Map(rows.filter(Boolean).map((row) => [String(row.windowId), row]));
  return monitorBctBrowserWindows;
}
//@@FN_END:refreshMonitorBctBrowserWindowGeometry

//@@FN_START:refreshMonitorBctCurrentSessionWindowHwnd
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
//@@FN_END:refreshMonitorBctCurrentSessionWindowHwnd

//@@FN_START:refreshMonitorBctDisplayWindowHwnd
function refreshMonitorBctDisplayWindowHwnd() {
  const display = monitorWindowHwndContract?.resolveDisplay?.({
    nodes: monitorBctWindowNodesCache || [], locations: monitorWindowDesktopLocations,
    browserWindows: monitorBctBrowserWindows, now: Date.now(),
  });
  monitorBctDisplayWindowHwnd = new Map((display?.bindings || []).map((binding) => [String(binding.lineage || ""), binding]));
  return display || null;
}
//@@FN_END:refreshMonitorBctDisplayWindowHwnd

//@@FN_START:refreshMonitorBctStatus
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
//@@FN_END:refreshMonitorBctStatus

//@@FN_START:refreshMonitorConversationStateFast
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
//@@FN_END:refreshMonitorConversationStateFast

//@@FN_START:rememberMonitorWorkerPlacement
function rememberMonitorWorkerPlacement(worker, state, location) {

  const key = String(worker?.conversation_key || "").trim();

  if (!key || !location?.desktop) return;

  const desktopIndex = Number(location.desktop) - 1;

  const desktopId = monitorDesktopState.desktopIds[desktopIndex] || "";

  if (!desktopId) return;

  monitorLastPlacementByConversation.set(key, { desktopId, desktop: Number(location.desktop), profileId: String(worker?.profile_id || "").trim().toUpperCase(), at: Date.now() });

}
//@@FN_END:rememberMonitorWorkerPlacement

//@@FN_START:renderWorkers
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
//@@FN_END:renderWorkers

//@@FN_START:requestMonitorConversationRename
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
//@@FN_END:requestMonitorConversationRename

//@@FN_START:resetMonitorBctProjectionConvergence
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
//@@FN_END:resetMonitorBctProjectionConvergence

//@@FN_START:resolveWorkerConnectionState
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
//@@FN_END:resolveWorkerConnectionState

//@@FN_START:resolveWorkerWorkState
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
//@@FN_END:resolveWorkerWorkState

//@@FN_START:scheduleMonitorBctProjectionConvergence
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
//@@FN_END:scheduleMonitorBctProjectionConvergence

//@@FN_START:settleMonitorWorkerPointerInteraction
function settleMonitorWorkerPointerInteraction(delay = MONITOR_WORKER_CLICK_SETTLE_MS) {

  clearTimeout(monitorWorkerPointerReleaseTimer);

  monitorWorkerPointerReleaseTimer = setTimeout(() => {

    monitorWorkerPointerInteractionActive = false;

    flushDeferredMonitorWorkerRender();

  }, delay);

}
//@@FN_END:settleMonitorWorkerPointerInteraction

//@@FN_START:stationForMonitorWorker
function stationForMonitorWorker(worker, state) { return globalThis.MonitorDomainAPIs["conversations"]["stationForMonitorWorker"].apply(this, arguments); }
//@@FN_END:stationForMonitorWorker

