"use strict";
(function installMonitorDomainAPIs(root) {

function classifyMonitorWorker(worker) {
  const profileId = String(worker?.profile_id || "").trim().toUpperCase();
  const provider = String(worker?.provider || worker?.provider_type || "").trim().toLowerCase();

  if (provider === "codex" || profileId === "CODEX") return "chatgpt";
  if (["GOOGLE", "NAVER"].includes(profileId)) return "chatgpt";
  if (provider.includes("local") || profileId === "LOCAL" || profileId.startsWith("L:")) return "local-llm";
  return "external-llm";
}

function cleanMonitorWorkerName(worker) {

  const raw = String(worker?.display_name || worker?.name || worker?.role || "").trim().replace(/^(?:G|N|E|L):\s*/i, "");

  const role = String(worker?.role || raw).trim().toUpperCase();

  const abbreviations = { ORCHESTRATOR: "O", COORDINATOR_1: "C1", COORDINATOR_2: "C2", WORKER: "W" };

  return abbreviations[role] || raw || "Agent";

}

function compareMonitorBctNodeDisplayOrder(left, right) {
  const leftOrder = Number(left.displayOrder || 0);
  const rightOrder = Number(right.displayOrder || 0);
  if (leftOrder > 0 || rightOrder > 0) {
    if (leftOrder <= 0) return 1;
    if (rightOrder <= 0) return -1;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  }
  return (left.tabIndex ?? Number.MAX_SAFE_INTEGER) - (right.tabIndex ?? Number.MAX_SAFE_INTEGER)
    || left.tabId - right.tabId;
}

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

function monitorBctNodeRoleSummary(node) {
  const tags = Array.isArray(node?.roleTags)
    ? node.roleTags.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  if (!tags.length) return "";
  const shown = tags.slice(0, 3);
  return `${shown.join(" · ")}${tags.length > shown.length ? ` · +${tags.length - shown.length}` : ""}`;
}

function monitorBctRenameErrorText(error) {
  const raw = String(error?.message || error || "").trim();
  if (/RESOURCE_ALREADY_CLAIMED|UNKNOWN|OUTCOME_UNVERIFIED/i.test(raw)) {
    return "이 대화의 이전 이름 변경 결과가 아직 미확정이라 안전상 다시 바꾸지 않았습니다.";
  }
  return raw ? `변경되지 않았습니다 · ${raw}` : "이름을 변경하지 못했습니다.";
}

function monitorBctRoleTagsFromText(value) {
  return [...new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean))].slice(0, 24);
}

function monitorBrowserLineageKey(endpoint) {

  if (!endpoint) return "";

  const transport = String(endpoint?.transport_instance_id || "").trim();

  const windowId = String(endpoint?.window_id ?? "").trim();

  if (!transport || !windowId) return "";

  return `${transport}:${windowId}`;

}

function monitorBrowserWindowIdForEndpoint(endpoint) {
  const metadata = endpoint?.metadata && typeof endpoint.metadata === "object" ? endpoint.metadata : {};
  return String(endpoint?.window_id ?? endpoint?.browser_window_id ?? metadata.window_id ?? metadata.browser_window_id ?? "").trim();
}

function monitorChatTransitionKey(nodeIdentityKey, profileId, oldKey, newKey) {

  const node=String(nodeIdentityKey||"").trim(), profile=String(profileId||"").toUpperCase(), from=String(oldKey||"").trim(), to=String(newKey||"").trim();

  return node&&profile&&from&&to&&from!==to ? `${node}|${profile}:${from}>${to}` : "";

}

function monitorCodexResourceProfile(worker) {
  return String(worker?.codex_profile_id || "").trim().toUpperCase();
}

function monitorContextTitleSignature(input){return JSON.stringify([input.browser_title,input.task_title,input.project_name,input.history.slice(-3)]);}

function monitorConversationStateSignature(state) {
  const endpoints=(Array.isArray(state?.endpoints)?state.endpoints:[])
    .filter((endpoint)=>String(endpoint?.presence_state||"").toUpperCase()==="OPEN")
    .map((endpoint)=>[
      String(endpoint?.profile_id||"").toUpperCase(),
      String(endpoint?.transport_instance_id||""),
      String(endpoint?.tab_id??""),
      String(endpoint?.conversation_key||""),
      String(endpoint?.window_id??""),
      String(endpoint?.metadata?.tab_active===true),
      String(endpoint?.metadata?.window_bounds?.state||"").toLowerCase()
    ].join(":"))
    .sort()
    .join("|");
  const nodes=(Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[])
    .map((node)=>[
      String(node?.node_label||"").toUpperCase(),
      String(node?.browser_node_id||""),
      String(node?.hwnd||""),
      String(node?.desktop_id||""),
      String(node?.location_authority||"")
    ].join(":"))
    .sort()
    .join("|");
  const windows=(Array.isArray(state?.node_state?.observer?.windows)?state.node_state.observer.windows:[])
    .map((row)=>[
      String(row?.hwnd||""),
      String(row?.desktop_id||""),
      String(row?.conversation_key||"")
    ].join(":"))
    .sort()
    .join("|");
  return `e:${endpoints}||n:${nodes}||w:${windows}`;
}

function monitorEndpointFreshnessState(endpoint) {

  if (String(endpoint?.presence_state || "").toUpperCase() !== "OPEN") return "disconnected";

  return "connected";

}

function monitorEndpointGeometry(endpoint) {

  const b = endpoint?.metadata?.window_bounds || {};

  return { left:Number(b.left), top:Number(b.top), width:Number(b.width), height:Number(b.height) };

}

function monitorEndpointInstanceId(endpoint) {

  if (!endpoint) return "";

  return [endpoint.transport_instance_id, endpoint.session_id, endpoint.tab_id].map((v)=>String(v ?? "")).join(":");

}

function monitorEndpointWindowKey(endpoint) {

  if (!endpoint) return "";

  return [endpoint.transport_instance_id, endpoint.window_id].map((v)=>String(v ?? "")).join(":");

}

function monitorExactOpenEndpoint(state, conversationKey) {

  const key=String(conversationKey||"").trim();

  const rows=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((ep)=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===key);

  return rows.length===1?rows[0]:null;

}

function monitorGhostArchiveAgeing(ghost) {

  const u = ghost?.usage || {}; let score = 0;

  // Preserve the previous ghost auto-hide behavior independently from handoff readiness.

  if (u.turns != null) score += Math.min(45, Math.sqrt(Math.max(0, u.turns) / 45) * 45);

  if (u.rendered_chars != null) score += Math.min(35, Math.sqrt(Math.max(0, u.rendered_chars) / 150000) * 35);

  if (u.screen_lengths != null) score += Math.min(20, Math.sqrt(Math.max(0, u.screen_lengths) / 35) * 20);

  return Math.max(0, Math.min(100, Math.round(score)));

}

function monitorGhostProtected(ghost) {

  const role=String(ghost?.role || "").toUpperCase(), status=String(ghost?.task_status || ghost?.work_status || "").toUpperCase();

  return ["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"].includes(role) || ["RUNNING","NEEDS_REVIEW","FAILED","FAILURE","RECOVERY","RECOVERY_PENDING","BLOCKED"].includes(status);

}

function monitorGhostTime(value) { const ms = Date.parse(String(value || "")); return Number.isFinite(ms) ? ms : 0; }

function monitorGhostWorkerId(worker) { return `CHATGPT:${String(worker?.profile_id || "").toUpperCase()}:${String(worker?.role || "").toUpperCase()}`; }

function monitorIsActivelyWorking(work) {

  return ["running", "working", "busy", "executing", "in_progress"].includes(String(work || "").toLowerCase());

}

function monitorIsExplicitCodexResource(node) {
  const provider = String(node?.provider || node?.provider_type || "").trim().toLowerCase();
  const kind = String(node?.kind || node?.provider_kind || node?.node_type || "").trim().toLowerCase();
  const endpoint = node?.__endpoint || {};
  const urlText = [
    node?.url, endpoint?.url, endpoint?.href, endpoint?.pathname,
    endpoint?.metadata?.url, endpoint?.metadata?.href, endpoint?.metadata?.pathname,
  ].filter(Boolean).join(" ").toLowerCase();
  return provider === "codex" || kind.includes("codex") || /(?:^|[\/:])codex(?:[\/?#:\s]|$)/.test(urlText);
}

function monitorLlmRuntimePresentation(worker, ready) {
  const runtime = worker?.llm_runtime && typeof worker.llm_runtime === "object" ? worker.llm_runtime : {};
  const runtimeState = String(worker?.llm_runtime_state || worker?.status || "UNAVAILABLE").toUpperCase();
  const loaded = runtime.loaded === true || runtimeState === "LOADED";
  const loading = runtime.loading === true || runtimeState === "LOADING";
  const busy = runtime.busy === true || runtimeState === "BUSY";
  const label = busy ? "사용 중" : (loading ? "로딩 중" : (loaded ? "로드됨" : (ready ? "준비됨" : "꺼짐")));
  const vram = Number(runtime.size_vram);
  return {
    label,
    vramText: Number.isFinite(vram) && vram > 0 ? ` · VRAM ${(vram / 1024 / 1024 / 1024).toFixed(1)} GB` : "",
  };
}

function monitorLocalModelIsLoaded(node) {
  const runtime = node?.runtime && typeof node.runtime === "object" ? node.runtime : {};
  const state = String(node?.runtime_state || runtime.state || "").toUpperCase();
  return runtime.loaded === true || runtime.busy === true || ["LOADED", "BUSY"].includes(state);
}

function monitorOpenEndpointsForConversation(state, conversationKey) {

  const key = String(conversationKey || "").trim();

  if (!key) return [];

  return (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((endpoint) =>

    String(endpoint?.conversation_key || "").trim() === key

    && String(endpoint?.presence_state || "").toUpperCase() === "OPEN"

  );

}

function monitorReportMatchesTask(report, task) {

  const taskId = String(task?.id || "").trim();

  if (!taskId || String(report?.task_id || "").trim() !== taskId) return false;

  if (String(report?.review_state || "").toUpperCase() !== "PENDING_REVIEW" || report?.stale_attempt === true) return false;

  const taskAttempt = String(task?.attempt_id || task?.current_attempt_id || "").trim();

  const currentAttempt = String(report?.current_attempt_id || "").trim();

  const reportAttempt = String(report?.attempt_id || "").trim();

  if (taskAttempt && reportAttempt !== taskAttempt) return false;

  if (currentAttempt && reportAttempt !== currentAttempt) return false;

  return true;

}

function monitorRoleAdminErrorText(value) { const text=String(value||"ROLE_ADMIN_FAILED"); return text.replace(/^.*?(STALE_GENERATION|ROLE_OCCUPIED|ROLE_USER_RESERVED|ACTIVE_TASK_CONFLICT|ENDPOINT_[A-Z_]+)[: ]?/,'$1: ').slice(0,120); }

function monitorRoleAdminShort(role) { return role==="ORCHESTRATOR"?"O":role==="COORDINATOR_1"?"C1":"C2"; }

function monitorStableBrowserNodeKey(worker) {

  const ep=worker?.__endpoint||null;

  const tabId=String(ep?.tab_id??"").trim();

  const conversationKey=String(worker?.conversation_key||ep?.conversation_key||"").trim();

  return tabId&&conversationKey ? `tab:${tabId}:chat:${conversationKey}` : "";

}

function monitorStationMetadata(station) {

  if (!station) return {};

  if (station.metadata && typeof station.metadata === "object") return station.metadata;

  try { return JSON.parse(String(station.metadata_json || "{}")); }

  catch (_) { return {}; }

}

function monitorStructureBundleName(kind){
  return kind==="local"?"L-LLM":kind==="external"?"E-LLM":"G-CODEX";
}

function monitorStructureBundleOrder(){return ["local","external","codex-google"];}

function monitorStructureHistoryKey(snapshot){return JSON.stringify(snapshot||{});}

function monitorStructureNodeDisplayName(node){
  const number=String(node?.label||"").trim();
  const title=String(node?.title||"").trim();
  if(title&&title!==number)return title;
  const role=String(node?.role||"").trim().toUpperCase();
  if(role&&!["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2","MANAGER","WORKER"].includes(role))return role;
  const profile=String(node?.profile_id||"").trim().toUpperCase();
  return profile?("ChatGPT · "+profile):"ChatGPT";
}

function monitorStructureNodeIdentityTokens(node){
  const label=String(node?.label||"").trim().toUpperCase();
  if(/^D\d+[-_]\d+$/.test(label))return [`act:${label}`];
  const tabId=String(node?.tab_id??"").trim();
  const conversationKey=String(node?.conversation_key||"").trim();
  if(tabId&&conversationKey)return [`tab:${tabId}:conversation:${conversationKey}`];
  return [`conversation:${conversationKey}`];
}

function monitorStructureNodeIsActive(node,kind){
  const status=String(node?.status||node?.availability||node?.connection_status||"").trim().toLowerCase();
  const runtime=String(node?.runtime_state||node?.runtime?.state||node?.llm_runtime_state||"").trim().toLowerCase();
  const activeStates=["available","ready","loaded","busy","working","running","generating","connected","online","healthy"];
  if(kind==="local")return node?.loaded===true||["loaded","busy","working","running","generating"].includes(runtime)
    || ["loaded","busy","working","running","generating"].includes(status);
  return activeStates.includes(runtime)||activeStates.includes(status)
    ||node?.loaded===true||node?.active===true||node?.connected===true||node?.available===true;
}

function monitorStructureNodeShortNumber(node){
  const label=String(node?.label||"").trim();
  const match=label.match(/^D\d+[-_](\d+)$/i);
  return match?match[1]:(label||"NODE");
}

function monitorTabBindingKey(endpoint) {

  const transport=String(endpoint?.transport_instance_id||"").trim();

  const tabId=String(endpoint?.tab_id??"").trim();

  return transport&&tabId ? `tab:${transport}:${tabId}` : "";

}

function monitorTitlesEquivalent(observed, requested){

  const a=String(observed||"").replace(/\s+/g," ").trim(), b=String(requested||"").replace(/\s+/g," ").trim();

  return a===b||[" - ChatGPT"," | ChatGPT"," — ChatGPT"].some((suffix)=>a===b+suffix);

}

function profileForMonitorWorker(worker, state) {

  const profileId = String(worker?.profile_id || "").toUpperCase();

  return (Array.isArray(state?.profiles) ? state.profiles : [])

    .find((item) => String(item?.profile_id || "").toUpperCase() === profileId) || null;

}

function stationForMonitorWorker(worker, state) {

  const workerId = `chatgpt:${String(worker?.profile_id || "").toUpperCase()}:${String(worker?.role || "").toUpperCase()}`;

  const stations = Array.isArray(state?.stations) ? state.stations : [];

  return stations.find((station) => String(station?.worker_id || "").toUpperCase() === workerId.toUpperCase()) || null;

}

root.MonitorDomainAPIs = Object.freeze({
  "conversations": Object.freeze({
    classifyMonitorWorker: classifyMonitorWorker,
    cleanMonitorWorkerName: cleanMonitorWorkerName,
    monitorBctRenameErrorText: monitorBctRenameErrorText,
    monitorBctRoleTagsFromText: monitorBctRoleTagsFromText,
    monitorConversationStateSignature: monitorConversationStateSignature,
    monitorGhostArchiveAgeing: monitorGhostArchiveAgeing,
    monitorGhostProtected: monitorGhostProtected,
    monitorGhostTime: monitorGhostTime,
    monitorGhostWorkerId: monitorGhostWorkerId,
    stationForMonitorWorker: stationForMonitorWorker,
  }),
  "node-identity": Object.freeze({
    compareMonitorBctNodeDisplayOrder: compareMonitorBctNodeDisplayOrder,
    monitorBctNodeRoleSummary: monitorBctNodeRoleSummary,
    monitorBrowserWindowIdForEndpoint: monitorBrowserWindowIdForEndpoint,
    monitorCodexResourceProfile: monitorCodexResourceProfile,
    monitorEndpointFreshnessState: monitorEndpointFreshnessState,
    monitorEndpointGeometry: monitorEndpointGeometry,
    monitorEndpointInstanceId: monitorEndpointInstanceId,
    monitorEndpointWindowKey: monitorEndpointWindowKey,
    monitorExactOpenEndpoint: monitorExactOpenEndpoint,
    monitorOpenEndpointsForConversation: monitorOpenEndpointsForConversation,
    monitorStableBrowserNodeKey: monitorStableBrowserNodeKey,
    profileForMonitorWorker: profileForMonitorWorker,
  }),
  "organization": Object.freeze({
    monitorStructureBundleName: monitorStructureBundleName,
    monitorStructureBundleOrder: monitorStructureBundleOrder,
    monitorStructureHistoryKey: monitorStructureHistoryKey,
    monitorStructureNodeDisplayName: monitorStructureNodeDisplayName,
    monitorStructureNodeIdentityTokens: monitorStructureNodeIdentityTokens,
    monitorStructureNodeIsActive: monitorStructureNodeIsActive,
    monitorStructureNodeShortNumber: monitorStructureNodeShortNumber,
  }),
  "shared-ui": Object.freeze({
    compareMonitorSharedSelectionRevision: compareMonitorSharedSelectionRevision,
    monitorBrowserLineageKey: monitorBrowserLineageKey,
    monitorChatTransitionKey: monitorChatTransitionKey,
    monitorContextTitleSignature: monitorContextTitleSignature,
    monitorIsActivelyWorking: monitorIsActivelyWorking,
    monitorIsExplicitCodexResource: monitorIsExplicitCodexResource,
    monitorLlmRuntimePresentation: monitorLlmRuntimePresentation,
    monitorLocalModelIsLoaded: monitorLocalModelIsLoaded,
    monitorReportMatchesTask: monitorReportMatchesTask,
    monitorRoleAdminErrorText: monitorRoleAdminErrorText,
    monitorRoleAdminShort: monitorRoleAdminShort,
    monitorStationMetadata: monitorStationMetadata,
    monitorTabBindingKey: monitorTabBindingKey,
    monitorTitlesEquivalent: monitorTitlesEquivalent,
  }),
});
})(globalThis);
