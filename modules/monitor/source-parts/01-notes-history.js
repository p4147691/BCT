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

function monitorDesktopManagementMode(desktopId) {
  const value = String(monitorDesktopManagementModes[String(desktopId || "")] || "OBSERVE_ONLY").toUpperCase();
  return MONITOR_DESKTOP_MANAGEMENT_MODES.has(value) ? value : "OBSERVE_ONLY";
}

function monitorDesktopManagementModeText(mode) {
  if (mode === "MANAGED") return "관리";
  if (mode === "PROTECTED") return "보호";
  return "보기";
}

function monitorDesktopManagementNextMode(mode) {
  if (mode === "OBSERVE_ONLY") return "MANAGED";
  if (mode === "MANAGED") return "PROTECTED";
  return "OBSERVE_ONLY";
}

function monitorSetDesktopManagementMode(desktopId, nextMode) {
  const id = String(desktopId || "").trim();
  const mode = String(nextMode || "").toUpperCase();
  if (!id || !MONITOR_DESKTOP_MANAGEMENT_MODES.has(mode)) return;
  if (monitorDesktopManagementMode(id) === mode) return;
  monitorDesktopManagementModes = { ...monitorDesktopManagementModes, [id]: mode };
  chrome.storage.local.set({ [MONITOR_DESKTOP_MANAGEMENT_MODE_KEY]: monitorDesktopManagementModes }).catch(() => {});
  setMonitorStatus(`D${Math.max(1, monitorDesktopState.desktopIds.indexOf(id) + 1)} · ${monitorDesktopManagementModeText(mode)} 모드`, true);
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
async function refreshInitialBackgroundThumbs() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED || !monitorIsActiveDesktopRenderer()) return;
  const selectedId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "";
  let pending = monitorDesktopState.desktopIds.filter((id) => id && id !== selectedId);
  if (!pending.length) return;

  const retryDelays = [160, 420];
  for (let attempt = 0; pending.length; attempt += 1) {
    pending = await refreshBackgroundThumbs(...pending);
    if (!pending.length || attempt >= retryDelays.length) break;
    await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
    if (!monitorIsActiveDesktopRenderer()) break;
  }
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

function monitorRoleAdminErrorText(value) { const text=String(value||"ROLE_ADMIN_FAILED"); return text.replace(/^.*?(STALE_GENERATION|ROLE_OCCUPIED|ROLE_USER_RESERVED|ACTIVE_TASK_CONFLICT|ENDPOINT_[A-Z_]+)[: ]?/,'$1: ').slice(0,120); }

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

function monitorExactOpenEndpoint(state, conversationKey) {

  const key=String(conversationKey||"").trim();

  const rows=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((ep)=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===key);

  return rows.length===1?rows[0]:null;

}

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

function monitorRoleAdminShort(role) { return role==="ORCHESTRATOR"?"O":role==="COORDINATOR_1"?"C1":"C2"; }

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

function classifyMonitorWorker(worker) {
  const profileId = String(worker?.profile_id || "").trim().toUpperCase();
  const provider = String(worker?.provider || worker?.provider_type || "").trim().toLowerCase();

  if (provider === "codex" || profileId === "CODEX") return "chatgpt";
  if (["GOOGLE", "NAVER"].includes(profileId)) return "chatgpt";
  if (provider.includes("local") || profileId === "LOCAL" || profileId.startsWith("L:")) return "local-llm";
  return "external-llm";
}

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

function monitorCodexResourceProfile(worker) {
  return String(worker?.codex_profile_id || "").trim().toUpperCase();
}

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

function monitorLocalModelIsLoaded(node) {
  const runtime = node?.runtime && typeof node.runtime === "object" ? node.runtime : {};
  const state = String(node?.runtime_state || runtime.state || "").toUpperCase();
  return runtime.loaded === true || runtime.busy === true || ["LOADED", "BUSY"].includes(state);
}

function monitorLocalOllamaModels(payload) {
  const nodes = Array.isArray(payload?.llm_nodes) ? payload.llm_nodes : [];
  return nodes
    .filter((node) => String(node?.kind || "").toLowerCase() === "local"
      && String(node?.provider || "").toLowerCase() === "ollama")
    .sort((a, b) => Number(monitorLocalModelIsLoaded(b)) - Number(monitorLocalModelIsLoaded(a)));
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

function cleanMonitorWorkerName(worker) {

  const raw = String(worker?.display_name || worker?.name || worker?.role || "").trim().replace(/^(?:G|N|E|L):\s*/i, "");

  const role = String(worker?.role || raw).trim().toUpperCase();

  const abbreviations = { ORCHESTRATOR: "O", COORDINATOR_1: "C1", COORDINATOR_2: "C2", WORKER: "W" };

  return abbreviations[role] || raw || "Agent";

}

function stationForMonitorWorker(worker, state) {

  const workerId = `chatgpt:${String(worker?.profile_id || "").toUpperCase()}:${String(worker?.role || "").toUpperCase()}`;

  const stations = Array.isArray(state?.stations) ? state.stations : [];

  return stations.find((station) => String(station?.worker_id || "").toUpperCase() === workerId.toUpperCase()) || null;

}

function monitorStationMetadata(station) {

  if (!station) return {};

  if (station.metadata && typeof station.metadata === "object") return station.metadata;

  try { return JSON.parse(String(station.metadata_json || "{}")); }

  catch (_) { return {}; }

}

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

function monitorChatTransitionKey(nodeIdentityKey, profileId, oldKey, newKey) {

  const node=String(nodeIdentityKey||"").trim(), profile=String(profileId||"").toUpperCase(), from=String(oldKey||"").trim(), to=String(newKey||"").trim();

  return node&&profile&&from&&to&&from!==to ? `${node}|${profile}:${from}>${to}` : "";

}

function monitorChatTransitionIsApproved(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); return Boolean(key&&monitorApprovedChatTransitions.has(key));

}

function monitorRememberApprovedChatTransition(nodeIdentityKey, profileId, oldKey, newKey) {

  const key=monitorChatTransitionKey(nodeIdentityKey,profileId,oldKey,newKey); if(!key)return; monitorApprovedChatTransitions.add(key);

  if(monitorApprovedChatTransitionsReady)chrome.storage.local.set({[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]:[...monitorApprovedChatTransitions]});

}

function monitorBrowserLineageKey(endpoint) {

  if (!endpoint) return "";

  const transport = String(endpoint?.transport_instance_id || "").trim();

  const windowId = String(endpoint?.window_id ?? "").trim();

  if (!transport || !windowId) return "";

  return `${transport}:${windowId}`;

}

function monitorTabBindingKey(endpoint) {

  const transport=String(endpoint?.transport_instance_id||"").trim();

  const tabId=String(endpoint?.tab_id??"").trim();

  return transport&&tabId ? `tab:${transport}:${tabId}` : "";

}

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

const MONITOR_STRUCTURE_SOCKET_KEY = "desktopWindowMonitorStructureSocketsV1";

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

const MONITOR_STRUCTURE_DESK_MEMBERSHIP_KEY = "desktopWindowMonitorStructureDeskMembershipV1";

const MONITOR_STRUCTURE_BUNDLE_DESK_KEY = "desktopWindowMonitorStructureBundleDeskV1";

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


function monitorOpenEndpointsForConversation(state, conversationKey) {

  const key = String(conversationKey || "").trim();

  if (!key) return [];

  return (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((endpoint) =>

    String(endpoint?.conversation_key || "").trim() === key

    && String(endpoint?.presence_state || "").toUpperCase() === "OPEN"

  );

}

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

function monitorEndpointInstanceId(endpoint) {

  if (!endpoint) return "";

  return [endpoint.transport_instance_id, endpoint.session_id, endpoint.tab_id].map((v)=>String(v ?? "")).join(":");

}

function monitorEndpointGeometry(endpoint) {

  const b = endpoint?.metadata?.window_bounds || {};

  return { left:Number(b.left), top:Number(b.top), width:Number(b.width), height:Number(b.height) };

}

