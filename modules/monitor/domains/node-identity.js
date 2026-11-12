//@@FN_START:applyMonitorBctNodeHighlight
function applyMonitorBctNodeHighlight(hwnd) {
  monitorBctNodeHighlightedHwnd = String(hwnd || "");
  // A BCT node selection is a Monitor-only projection.  It must not become a
  // generic HWND selection: that selection is shared with the native window
  // path and can decorate the real Chrome window.  Clear any old generic
  // selection, then keep only the node-list/thumbnail perimeter below.
  monitorSelectedHwnds.clear();
  monitorHighlightedHwnd = "";
  applyMonitorWindowHighlight("", { preserve: true, remote: true });
  publishMonitorSharedSelection();
  syncMonitorBctNodeTargetHighlight();
  // A selected node may be in a minimized Chrome window. Re-project the same
  // exact selection onto the desktop's minimized summary without changing any
  // Windows or Chrome state.
  syncMonitorMinimizedNodeBadges();
  syncMonitorAllDesktopThumbnailNodeBadges();
}
//@@FN_END:applyMonitorBctNodeHighlight

//@@FN_START:monitorBctNodeDisplayState
function monitorBctNodeDisplayState() {
  const stateKey = "__monitorBctNodeDisplayState";
  if (!globalThis[stateKey]) {
    let viewMode = "manual";
    try {
      const saved = String(globalThis.localStorage?.getItem("monitor.bct-node-view-mode.v1") || "");
      if (["manual", "number", "observed", "burden"].includes(saved)) viewMode = saved;
    } catch (_) {}
    globalThis[stateKey] = { firstObservedAt:new Map(), loaded:false, load:null, saveTimer:0, viewMode };
  }
  return globalThis[stateKey];
}
//@@FN_END:monitorBctNodeDisplayState

//@@FN_START:monitorBctNodeObservedKey
function monitorBctNodeObservedKey(node) {
  return String(monitorBctNodeSelectionKey(node) || node?.conversationKey || "").trim().toLowerCase();
}
//@@FN_END:monitorBctNodeObservedKey

//@@FN_START:loadMonitorBctNodeFirstObservedAt
function loadMonitorBctNodeFirstObservedAt() {
  const state = monitorBctNodeDisplayState();
  if (state.load) return state.load;
  const storage = globalThis.chrome?.storage?.local;
  if (!storage?.get) {
    state.loaded = true;
    return Promise.resolve();
  }
  state.load = storage.get("monitor.bct-node-first-observed.v1").then((stored) => {
    const values = stored?.["monitor.bct-node-first-observed.v1"];
    if (values && typeof values === "object") {
      for (const [key, observedAt] of Object.entries(values)) {
        const time = Number(observedAt || 0);
        if (key && Number.isFinite(time) && time > 0) state.firstObservedAt.set(key, time);
      }
    }
  }).catch(() => {}).finally(() => {
    state.loaded = true;
    if (Array.isArray(monitorBctWindowNodesCache)) renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
  });
  return state.load;
}
//@@FN_END:loadMonitorBctNodeFirstObservedAt

//@@FN_START:persistMonitorBctNodeFirstObservedAt
function persistMonitorBctNodeFirstObservedAt() {
  const storage = globalThis.chrome?.storage?.local;
  if (!storage?.set) return;
  const values = Object.fromEntries([...monitorBctNodeDisplayState().firstObservedAt.entries()].slice(-300));
  storage.set({ "monitor.bct-node-first-observed.v1": values }).catch(() => {});
}
//@@FN_END:persistMonitorBctNodeFirstObservedAt

//@@FN_START:observeMonitorBctNodeFirstSeen
function observeMonitorBctNodeFirstSeen(nodes) {
  const state = monitorBctNodeDisplayState();
  const now = Date.now();
  let changed = false;
  for (const node of nodes || []) {
    const key = monitorBctNodeObservedKey(node);
    if (key && !state.firstObservedAt.has(key)) {
      state.firstObservedAt.set(key, now);
      changed = true;
    }
  }
  if (!changed || state.saveTimer) return;
  void loadMonitorBctNodeFirstObservedAt().finally(() => {
    if (state.saveTimer) return;
    state.saveTimer = setTimeout(() => {
      state.saveTimer = 0;
      persistMonitorBctNodeFirstObservedAt();
    }, 200);
  });
}
//@@FN_END:observeMonitorBctNodeFirstSeen

//@@FN_START:monitorBctNodeObservedAgeText
function monitorBctNodeObservedAgeText(node, now = Date.now()) {
  const state = monitorBctNodeDisplayState();
  if (!state.loaded) return "관측 확인 중";
  const observedAt = Number(state.firstObservedAt.get(monitorBctNodeObservedKey(node)) || 0);
  if (!observedAt) return "관측 0분";
  const seconds = Math.max(0, Math.floor((now - observedAt) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `관측 ${minutes}분`;
}
//@@FN_END:monitorBctNodeObservedAgeText

//@@FN_START:monitorBctNodeBurdenScore
function monitorBctNodeBurdenScore(node) {
  const burden = monitorBctNodeBurden(node);
  return burden.label === "높음" ? 3 : burden.label === "보통" ? 2 : burden.label === "낮음" ? 1 : 0;
}
//@@FN_END:monitorBctNodeBurdenScore

//@@FN_START:monitorBctNodeDetail
function monitorBctNodeDetail(node, desktopPosition, nativeLocation) {
  const minimized = nativeLocation?.iconic === true;
  const burden = monitorBctNodeBurden(node);
  const reasoningObserved = String(node?.reasoningRaw || node?.reasoningLevel || "").trim();
  const reasoningUnknown = !reasoningObserved || ["?", "UNKNOWN", "UNOBSERVED", "N/A"].includes(reasoningObserved.toUpperCase());
  // Dot does not expose a reasoning-level setting. An absent observation is
  // not an unknown setting, so leave this optional display field empty.
  const reasoning = reasoningUnknown ? (node?.dotKey ? "" : "미확인") : reasoningObserved;
  // RCC can expose the model-selector label together with its value (for
  // example, "추론 수준Instant").  Keep that raw observation for the detail
  // surface, but remove the presentation label before producing the compact
  // card token.
  const compactReasoningKey = reasoning
    .replace(/^(?:추론\s*수준|reasoning\s*level)\s*[:：-]?\s*/i, "")
    .trim()
    .toLowerCase();
  const normalizedReasoningLabel = ({
    instant: "I",
    low: "L",
    medium: "M",
    high: "H",
    xhigh: "E",
    "extra high": "E",
    "extra-high": "E",
    pro: "P",
    max: "Max",
    ultra: "Ultra",
  })[compactReasoningKey] || reasoning;
  // The raw observation is the display authority.  Cached node records from
  // an earlier Monitor build may carry an uncompressed reasoningLevel, so do
  // not let that stale presentation value widen a freshly rendered card.
  const reasoningLabel = normalizedReasoningLabel;
  const observedAge = monitorBctNodeObservedAgeText(node);
  const observedAgeCompact = observedAge
    .replace("관측 확인 중", "확인중")
    .replace(/^관측 (\d+)분$/, "$1분");
  const locationText = monitorBctNodeLocationText(node, desktopPosition);
  const surfaceText = monitorBctNodeSurfaceText(node);
  return {
    text: [
      `${locationText}${minimized ? " _" : ""}`,
      surfaceText,
      reasoningLabel,
      observedAgeCompact,
      burden.label,
    ].filter(Boolean).join(" "),
    title: [
      `위치 ${locationText}`,
      minimized ? "최소화됨" : "표시 중",
      `종류 ${surfaceText}`,
      reasoning ? `추론 ${reasoning}` : "",
      observedAge,
      `부담 ${burden.label} (${burden.title})`,
    ].filter(Boolean).join(" · "),
  };
}
//@@FN_END:monitorBctNodeDetail

//@@FN_START:setMonitorBctNodeViewMode
function setMonitorBctNodeViewMode(value) {
  const next = ["manual", "number", "observed", "burden"].includes(String(value)) ? String(value) : "manual";
  monitorBctNodeDisplayState().viewMode = next;
  try { globalThis.localStorage?.setItem("monitor.bct-node-view-mode.v1", next); } catch (_) {}
  const control = document.getElementById("monitorBctNodeViewMode");
  if (control) control.value = next;
  if (Array.isArray(monitorBctWindowNodesCache)) renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
}
//@@FN_END:setMonitorBctNodeViewMode

//@@FN_START:applyMonitorChatNavigationIdentity
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
    monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(selectedNode);
    // Chrome chose this tab. Mirror that exact tab in Monitor, including the
    // browser-window perimeter in the thumbnail. This is visual state only:
    // it must never activate, move, or otherwise change the real window.
    const displayHwnd = monitorDisplayHwndForBrowserWindowId(
      selectedNode.windowId,
      state,
      selectedNode.instanceId,
      selectedNode.sessionId,
    );
    if (displayHwnd) applyMonitorBctNodeHighlight(displayHwnd);
    else {
      monitorBctNodeHighlightedHwnd = "";
      syncMonitorBctNodeTargetHighlight();
      syncMonitorMinimizedNodeBadges(state);
      syncMonitorAllDesktopThumbnailNodeBadges();
    }
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
//@@FN_END:applyMonitorChatNavigationIdentity

//@@FN_START:approveMonitorNodeChatChange
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
//@@FN_END:approveMonitorNodeChatChange

//@@FN_START:compareMonitorBctNodeDisplayOrder
function compareMonitorBctNodeDisplayOrder(left, right) { return globalThis.MonitorDomainAPIs["node-identity"]["compareMonitorBctNodeDisplayOrder"].apply(this, arguments); }
//@@FN_END:compareMonitorBctNodeDisplayOrder

//@@FN_START:endpointForMonitorWorker
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
//@@FN_END:endpointForMonitorWorker

//@@FN_START:endpointOsWindowHandle
function endpointOsWindowHandle(endpoint) {

  const metadata = endpoint?.metadata && typeof endpoint.metadata === "object" ? endpoint.metadata : {};

  const raw = endpoint?.hwnd ?? endpoint?.os_hwnd ?? metadata.hwnd ?? metadata.os_hwnd ?? metadata.window_handle;

  const value = String(raw ?? "").trim();

  return /^\d+$/.test(value) && value !== "0" ? value : "";

}
//@@FN_END:endpointOsWindowHandle

//@@FN_START:endpointRegistryIsAuthoritative
function endpointRegistryIsAuthoritative(worker, state) {

  const source = String(profileForMonitorWorker(worker, state)?.metadata?.presence_source || "").toLowerCase();

  return source === "endpoint_registry";

}
//@@FN_END:endpointRegistryIsAuthoritative

//@@FN_START:getMonitorBctNodeInteractionService
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
      dotKey: target?.dotKey,
      codexLocalReference: target?.codexLocalReference,
    }),
  });
  return monitorBctNodeInteractionService;
}
//@@FN_END:getMonitorBctNodeInteractionService

//@@FN_START:monitorActBrowserNode
function monitorActBrowserNode(worker, state = monitorLastAiState) {

  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return null;

  const key=monitorStableBrowserNodeKey(worker);

  const actNodes=Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[];

  if(key){const direct=actNodes.find((node)=>String(node?.browser_node_id||"")===key);if(direct&&String(direct?.identity_authority||"")==="ACT_TAB_CHAT")return direct;}

  return null;

}
//@@FN_END:monitorActBrowserNode

//@@FN_START:monitorActNodeNumbersForHwnd
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
//@@FN_END:monitorActNodeNumbersForHwnd

//@@FN_START:monitorAgeIdentityForHwnd
function monitorAgeIdentityForHwnd(hwnd, state = monitorLastAiState) {

  const key=String(hwnd||"").trim(); if(!key||!state)return { worker:null, conversationKey:"", profileId:"", ageing:0, nodeNumber:0 };

  const workers=monitorWorkersForState(state).filter((worker)=>{

    if(classifyMonitorWorker(worker)!=="chatgpt"||!String(worker?.conversation_key||"").trim())return false;

    const location=monitorEndpointLocation(worker,state);

    return String(monitorResolvedWorkerHwnd(worker,state,location)||"").trim()===key;

  });

  return monitorAgeIdentityForWorkerGroup(workers,state);

}
//@@FN_END:monitorAgeIdentityForHwnd

//@@FN_START:monitorAgeIdentityForWorkerGroup
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
//@@FN_END:monitorAgeIdentityForWorkerGroup

//@@FN_START:monitorBadgeNodeNumbersForHwnd
function monitorBadgeNodeNumbersForHwnd(hwnd, state = monitorLastAiState, options = null) {
  // BCT/RCC owns conversation labels, and Native/ACT maps the physical HWND.
  // Thumbnail labels use only the current-session/display contract. Legacy ACT
  // mappings may lag behind a Chrome tab detach/attach and must never merge two
  // different Chrome window_ids onto one physical thumbnail window.
  const includeTabIds = options?.includeTabIds === true;
  const tokenFor = (node) => {
    if (node?.dotKey) return "DOT";
    const codex = /^C(\d{1,2})$/i.exec(String(node?.nodeLabel || "").trim());
    if (codex) return `C${codex[1]}`;
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
    // The minimized summary is rendered while Chrome and the Monitor list are
    // often refreshing together.  Prefer the retained display map, but build
    // one read-only exact fallback from the same current-session contract when
    // that cache has not caught up yet.  It never guesses an HWND.
    const fallbackHwndByLineage = new Map((monitorWindowHwndContract?.resolve?.({
      nodes: monitorBctWindowNodesCache,
      locations: monitorWindowDesktopLocations,
      now: Date.now(),
    })?.bindings || []).map((binding) => [String(binding?.lineage || ""), String(binding?.hwnd || "")]));
    const hwndForNode = (node) => {
      const mapped = monitorBctDisplaySessionHwnd(node.windowId, node.instanceId, node.sessionId);
      if (mapped) return mapped;
      return String(fallbackHwndByLineage.get(`${node?.instanceId || ""}:${node?.sessionId || ""}:${node?.windowId || ""}`) || "");
    };
    const matched = monitorBctWindowNodesCache.filter((node) =>
      hwndForNode(node) === String(hwnd))
      .sort((left,right) =>
        (Number.isSafeInteger(left?.tabIndex) ? left.tabIndex : Number.MAX_SAFE_INTEGER) -
          (Number.isSafeInteger(right?.tabIndex) ? right.tabIndex : Number.MAX_SAFE_INTEGER) ||
        Number(left?.tabId || 0) - Number(right?.tabId || 0));
    const byTabId = new Map(matched.map((node) => [Number(node?.tabId), node])
      .filter(([tabId]) => Number.isInteger(tabId) && tabId >= 0));
    const browserWindowIds = [...new Set(matched.map((node) => Number(node?.windowId))
      .filter((windowId) => Number.isInteger(windowId)))];

    // When Chrome has just told us the current tab order, it is more current
    // than Core's next membership refresh. Keep only ChatGPT tabs whose BCT
    // identity is not available yet visible as `?`. Ordinary tabs in the same
    // Chrome window (YouTube, GitHub, etc.) are physical thumbnail content,
    // not candidate BCT nodes.
    if (browserWindowIds.length === 1) {
      const browserTabs = monitorBrowserVisualTabsForWindow(browserWindowIds[0]);
      if (browserTabs.length) {
        return browserTabs
          .filter((tab) => byTabId.has(Number(tab.tabId)) || tab?.chatGpt === true)
          .map((tab) => itemFor(byTabId.get(Number(tab.tabId)), tab.tabId));
      }
    }

    return matched.map((node) => itemFor(node));
  }
  return monitorActNodeNumbersForHwnd(hwnd, state).map((token) => includeTabIds ? { token, tabId: null } : token);
}
//@@FN_END:monitorBadgeNodeNumbersForHwnd

//@@FN_START:monitorBctNodeInsertionAt
function monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey) {
  const rows = [...list.querySelectorAll(".monitor-bct-node-row")]
    .filter((row) => (!row.parentElement || row.parentElement === list) &&
      String(row.dataset.nodeSelectionKey || row.dataset.conversationKey || "") !== draggedKey && !row.hidden)
    .map((row) => ({ row, rect: row.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width > 0 && rect.height > 0);
  if (!rows.length) return null;
  const direct = hit?.closest?.(".monitor-bct-node-row");
  if (direct && (!direct.parentElement || direct.parentElement === list) &&
      hit?.closest?.(".monitor-bct-node-list") === list &&
      String(direct.dataset.nodeSelectionKey || direct.dataset.conversationKey || "") !== draggedKey) {
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
//@@FN_END:monitorBctNodeInsertionAt

//@@FN_START:monitorBctNodeLocationText
function monitorBctNodeLocationText(node, desktopPosition) {
  return desktopPosition >= 0 ? `D${desktopPosition + 1}` : "D?";
}
//@@FN_END:monitorBctNodeLocationText

//@@FN_START:monitorBctNodeSurfaceText
function monitorBctNodeSurfaceText(node) {
  if (node?.codexLocalReference) return "Codex";
  if (node?.dotKey) return "Dot";
  if (!String(node?.conversationKey || "").trim()) return "New";
  const kind = String(node?.surfaceKind || "UNKNOWN").trim().toUpperCase();
  // The browser product surface is Chat or Work. CODEX_MARKERS describe who
  // is directing an ordinary ChatGPT conversation; they do not turn that
  // chatgpt.com/c page into a third browser surface.
  return kind === "WORK" ? "Work" : "Chat";
}
//@@FN_END:monitorBctNodeSurfaceText

//@@FN_START:monitorBctNodeBurden
function monitorBctNodeBurden(node) {
  const telemetry = node?.telemetry && typeof node.telemetry === "object" ? node.telemetry : {};
  const heap = Number(telemetry.js_heap_used_mb);
  const limit = Number(telemetry.js_heap_limit_mb);
  const chars = Number(telemetry.rendered_chars);
  const performance = String(telemetry.performance_state || "NORMAL").toUpperCase();
  const ratio = Number.isFinite(heap) && Number.isFinite(limit) && limit > 0 ? heap / limit : 0;
  const score = (performance !== "NORMAL" ? 3 : 0) + (ratio >= .75 ? 3 : ratio >= .45 ? 2 : ratio > 0 ? 1 : 0) + (chars >= 800000 ? 2 : chars >= 250000 ? 1 : 0);
  const label = score >= 4 ? "높음" : score >= 2 ? "보통" : score > 0 ? "낮음" : "미확인";
  const evidence = [Number.isFinite(heap) ? `JS 힙 ${heap}MB${Number.isFinite(limit) ? `/${limit}MB` : ""}` : "", Number.isFinite(chars) ? `렌더 ${chars.toLocaleString()}자` : "", performance !== "NORMAL" ? `상태 ${performance}` : ""].filter(Boolean);
  return Object.freeze({ label, title: evidence.length ? evidence.join(" · ") : "탭 부담 관측값 없음" });
}
//@@FN_END:monitorBctNodeBurden

//@@FN_START:monitorBctNodeRoleSummary
function monitorBctNodeRoleSummary(node) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorBctNodeRoleSummary"].apply(this, arguments); }
//@@FN_END:monitorBctNodeRoleSummary

//@@FN_START:monitorBctNodeRoleRank
function monitorBctNodeRoleRank(node) {
  if (node?.dotKey) return -1;
  const tags = Array.isArray(node?.roleTags)
    ? node.roleTags.map((tag) => String(tag).trim().toLowerCase())
    : [];
  if (tags.includes("supervisor")) return 0;
  if (tags.includes("manager")) return 1;
  return 2;
}
//@@FN_END:monitorBctNodeRoleRank

//@@FN_START:monitorBctNodeSelectionKey
function monitorBctNodeSelectionKey(value) {
  const instanceId = String(value?.instanceId || "").trim();
  const sessionId = String(value?.sessionId || "").trim();
  const windowId = String(value?.windowId || "").trim();
  const tabId = String(value?.tabId || "").trim();
  if (!windowId || !tabId) return "";
  return instanceId && sessionId
    ? `${instanceId}:${sessionId}:${windowId}:${tabId}`
    : `tab:${windowId}:${tabId}`;
}
//@@FN_END:monitorBctNodeSelectionKey

//@@FN_START:monitorBrowserDisplaySlots
function monitorBrowserDisplaySlots(workers,state) { return monitorListDisplaySlots(workers,state); }
//@@FN_END:monitorBrowserDisplaySlots

//@@FN_START:monitorBrowserWindowIdForEndpoint
function monitorBrowserWindowIdForEndpoint(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorBrowserWindowIdForEndpoint"].apply(this, arguments); }
//@@FN_END:monitorBrowserWindowIdForEndpoint

//@@FN_START:monitorCanonicalNodeBindings
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
//@@FN_END:monitorCanonicalNodeBindings

//@@FN_START:monitorCodexResourceProfile
function monitorCodexResourceProfile(worker) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorCodexResourceProfile"].apply(this, arguments); }
//@@FN_END:monitorCodexResourceProfile

//@@FN_START:monitorDirectEndpointUserAttention
function monitorDirectEndpointUserAttention(endpoint) {
  return monitorNodeGenerationAPI.directUserAttention(endpoint);
}
//@@FN_END:monitorDirectEndpointUserAttention

//@@FN_START:monitorEndpointFreshnessState
function monitorEndpointFreshnessState(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointFreshnessState"].apply(this, arguments); }
//@@FN_END:monitorEndpointFreshnessState

//@@FN_START:monitorEndpointGenerationIsActive
function monitorEndpointGenerationIsActive(endpoint) {
  return monitorNodeGenerationAPI.endpointIsGenerating(endpoint);
}
//@@FN_END:monitorEndpointGenerationIsActive

//@@FN_START:monitorEndpointGeometry
function monitorEndpointGeometry(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointGeometry"].apply(this, arguments); }
//@@FN_END:monitorEndpointGeometry

//@@FN_START:monitorEndpointInstanceId
function monitorEndpointInstanceId(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointInstanceId"].apply(this, arguments); }
//@@FN_END:monitorEndpointInstanceId

//@@FN_START:monitorEndpointIsMinimized
function monitorEndpointIsMinimized(endpoint, worker = null, state = null) {

  const resolvedLocation = worker && state ? monitorEndpointLocation(worker, state) : null;

  const resolvedHwnd = worker && state ? monitorResolvedWorkerHwnd(worker, state, resolvedLocation) : "";

  const hwnd = String(resolvedHwnd || endpointOsWindowHandle(endpoint) || "").trim();

  const live = hwnd ? monitorWindowDesktopLocations.get(hwnd) : null;

  if (live && typeof live.iconic === "boolean") return live.iconic;

  return String(endpoint?.metadata?.window_bounds?.state || "").toLowerCase() === "minimized";

}
//@@FN_END:monitorEndpointIsMinimized

//@@FN_START:monitorEndpointLocation
function monitorEndpointLocation(worker, state) { return monitorCanonicalPhysicalLocation(worker, state)?.location || null; }
//@@FN_END:monitorEndpointLocation

//@@FN_START:monitorEndpointWindowKey
function monitorEndpointWindowKey(endpoint) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorEndpointWindowKey"].apply(this, arguments); }
//@@FN_END:monitorEndpointWindowKey

//@@FN_START:monitorExactOpenEndpoint
function monitorExactOpenEndpoint(state, conversationKey) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorExactOpenEndpoint"].apply(this, arguments); }
//@@FN_END:monitorExactOpenEndpoint

//@@FN_START:monitorExactSelectedChatNode
function monitorExactSelectedChatNode() {
  const nodes = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [];
  const selected = nodes.find((node) =>
    monitorBctSelectedNodeKey && monitorBctNodeSelectionKey(node) === monitorBctSelectedNodeKey
  );
  if (selected) return selected;
  const active = nodes.filter((node) => node.active === true && node.conversationKey && !node.displayStale);
  return active.length === 1 ? active[0] : null;
}
//@@FN_END:monitorExactSelectedChatNode

//@@FN_START:monitorHwndHasOpenChatEndpoint
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
//@@FN_END:monitorHwndHasOpenChatEndpoint

//@@FN_START:monitorListDisplaySlots
function monitorListDisplaySlots(members, state) {

  const result=new Map();

  for(const worker of (Array.isArray(members)?members:[])){

    const stable=monitorStableNodeSlot(worker,state);

    if(stable)result.set(worker?.__display_key,`N${stable.slot} · D${stable.desktop}`);

  }

  return result;

}
//@@FN_END:monitorListDisplaySlots

//@@FN_START:monitorLocationForEndpoint
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
//@@FN_END:monitorLocationForEndpoint

//@@FN_START:monitorMarkSystemNode
function monitorMarkSystemNode(conversationKey){ const key=String(conversationKey||"").trim(); if(!key||monitorSystemNodeKeys.has(key))return; monitorSystemNodeKeys.add(key); monitorPersistSystemNodes(); }
//@@FN_END:monitorMarkSystemNode

//@@FN_START:monitorNodeBindingsSignature
function monitorNodeBindingsSignature(values = monitorNodeBindings.values()) {
  return JSON.stringify(monitorCanonicalNodeBindings(values));
}
//@@FN_END:monitorNodeBindingsSignature

//@@FN_START:monitorNodeChatChangeState
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
//@@FN_END:monitorNodeChatChangeState

//@@FN_START:monitorNodeIdentityParts
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
//@@FN_END:monitorNodeIdentityParts

//@@FN_START:monitorOpenEndpointForHwnd
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
//@@FN_END:monitorOpenEndpointForHwnd

//@@FN_START:monitorOpenEndpointsForConversation
function monitorOpenEndpointsForConversation(state, conversationKey) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorOpenEndpointsForConversation"].apply(this, arguments); }
//@@FN_END:monitorOpenEndpointsForConversation

//@@FN_START:monitorPersistNodeBindings
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
//@@FN_END:monitorPersistNodeBindings

//@@FN_START:monitorPersistSystemNodes
function monitorPersistSystemNodes(){ try { localStorage.setItem(MONITOR_SYSTEM_NODE_STORAGE_KEY, JSON.stringify([...monitorSystemNodeKeys])); } catch (_) {} }
//@@FN_END:monitorPersistSystemNodes

//@@FN_START:monitorProfileIdForHwnd
function monitorProfileIdForHwnd(hwnd) {

  const location = monitorWindowDesktopLocations.get(String(hwnd));

  const key = String(location?.conversationKey || "").trim();

  const endpoint = (Array.isArray(monitorLastAiState?.endpoints) ? monitorLastAiState.endpoints : []).find((item) => String(item?.conversation_key || "").trim() === key);

  const profile = String(endpoint?.profile_id || "").trim().toUpperCase();

  return ["GOOGLE", "NAVER"].includes(profile) ? profile : "";

}
//@@FN_END:monitorProfileIdForHwnd

//@@FN_START:monitorStableBrowserNodeKey
function monitorStableBrowserNodeKey(worker) { return globalThis.MonitorDomainAPIs["node-identity"]["monitorStableBrowserNodeKey"].apply(this, arguments); }
//@@FN_END:monitorStableBrowserNodeKey

//@@FN_START:monitorStableNodeForEndpoint
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
//@@FN_END:monitorStableNodeForEndpoint

//@@FN_START:monitorStableNodeForWindow
function monitorStableNodeForWindow(hwnd, endpoint = null) {

  const tabKey=monitorTabBindingKey(endpoint);

  if (tabKey) { const byTab=monitorNodeBindings.get(tabKey); if (byTab) return byTab; }

  const lineage = monitorBrowserLineageKey(endpoint);

  if (lineage && monitorNodeBindings.has(`lineage:${lineage}`)) return monitorNodeBindings.get(`lineage:${lineage}`) || null;

  const key = String(hwnd || "").trim();

  return key && monitorNodeBindings.has(`hwnd:${key}`) ? (monitorNodeBindings.get(`hwnd:${key}`) || null) : null;

}
//@@FN_END:monitorStableNodeForWindow

//@@FN_START:monitorStableNodeSlot
function monitorStableNodeSlot(worker,state,liveUsedSlots=null,acceptedCurrentKeys=null) {

  return monitorStableNodeSlotRecord(worker,monitorStableBrowserNodeKey(worker),state);

}
//@@FN_END:monitorStableNodeSlot

//@@FN_START:monitorStableNodeSlotRecord
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
//@@FN_END:monitorStableNodeSlotRecord

//@@FN_START:monitorStoreNodeBinding
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
//@@FN_END:monitorStoreNodeBinding

//@@FN_START:profileForMonitorWorker
function profileForMonitorWorker(worker, state) { return globalThis.MonitorDomainAPIs["node-identity"]["profileForMonitorWorker"].apply(this, arguments); }
//@@FN_END:profileForMonitorWorker

//@@FN_START:scheduleMonitorBctNodeStartupRevalidation
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
//@@FN_END:scheduleMonitorBctNodeStartupRevalidation

//@@FN_START:startMonitorBctRosterWatch
function startMonitorBctRosterWatch() {
  if (MONITOR_ACTIVE_STARTUP_ENABLED) {
    monitorBctShell?.subscribeRosterChanges(() => void refreshMonitorBctWindowNodes());
  }
}
//@@FN_END:startMonitorBctRosterWatch

//@@FN_START:refreshMonitorBctWindowNodes
async function refreshMonitorBctWindowNodes() {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorBctShell) return;
  if (monitorBctWindowNodeRefreshBusy) {
    monitorBctWindowNodeRefreshPending = true;
    return;
  }
  monitorBctWindowNodeRefreshBusy = true;
  monitorBctWindowNodeRefreshPending = false;
  if (monitorBctNodesRefresh) monitorBctNodesRefresh.disabled = true;
  if (monitorBctNodeSummary) monitorBctNodeSummary.textContent = "확인 중…";
  try {
    const state = await monitorBctShell.monitorState();
    renderMonitorGithubInbox(state);
    monitorBctManagerStatuses = monitorBctShell.managerStatuses
      ? monitorBctShell.managerStatuses(state)
      : Object.freeze([]);
    const observedNodes = monitorBctShell.displayWindowNodes
      ? monitorBctShell.displayWindowNodes(state, monitorBctWindowNodesCache || [])
      : monitorBctShell.windowNodes(state);
    const nextNodes = applyMonitorBctPendingRoleProjections(observedNodes);
    // A saved reorder owns the visible list until the Core reply is available.
    // Do not let an unrelated, older status refresh paint the previous order
    // over the optimistic order while that write is in flight.
    if (monitorBctNodeReorderPending) {
      monitorBctDeferredNodeRender = nextNodes;
      return;
    }
    monitorBctWindowNodesCache = nextNodes;
    resetMonitorBctProjectionConvergence();
    await refreshMonitorBctBrowserWindowGeometry();
    await refreshMonitorIdentityIndex(monitorLastAiState, true);
    refreshMonitorBctCurrentSessionWindowHwnd();
    refreshMonitorBctDisplayWindowHwnd();
    renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleMonitorBctProjectionConvergence("bct-state");
    if (monitorBctWindowNodesCache.some((node) => node.displayStale === true)) {
      scheduleMonitorBctNodeStartupRevalidation();
    }
  } catch (error) {
    if (monitorBctNodeSummary) monitorBctNodeSummary.textContent = "상태 확인 실패";
    const message = document.createElement("div");
    message.className = "monitor-bct-node-empty is-error";
    message.textContent = `BCT 창 현황을 불러오지 못했습니다 · ${error?.message || error}`;
    monitorWorkers?.replaceChildren(message);
  } finally {
    monitorBctWindowNodeRefreshBusy = false;
    if (monitorBctNodesRefresh) monitorBctNodesRefresh.disabled = false;
    if (monitorBctWindowNodeRefreshPending) {
      monitorBctWindowNodeRefreshPending = false;
      queueMicrotask(() => void refreshMonitorBctWindowNodes());
    }
  }
}
//@@FN_END:refreshMonitorBctWindowNodes

//@@FN_START:renderMonitorGithubInbox
function renderMonitorGithubInbox(state) {
  if (!monitorGithubInbox) return;
  const items = Array.isArray(state?.github_run_inbox) ? state.github_run_inbox.slice(0, 12) : [];
  monitorGithubInbox.replaceChildren();
  monitorGithubInbox.className = "monitor-github-inbox-ticker";
  if (!items.length) {
    monitorGithubInbox.textContent = "GitHub Inbox · 새 결과 없음";
    return;
  }
  const unreadCount = items.filter((item) => item?.unread === true).length;
  const latest = items[0];
  const stateLabel = String(latest?.state || "확인 중");
  const project = String(latest?.repository || "GitHub");
  const kind = String(latest?.context?.kind || latest?.context?.type || "CI");
  const runId = String(latest?.run_id || "");
  const message = document.createElement("span");
  message.textContent = `GitHub Inbox · ${unreadCount ? `${unreadCount}개 새 결과 · ` : ""}${stateLabel} · ${project} · ${kind}${runId ? ` #${runId}` : ""}`;
  message.title = String(latest?.next_step || latest?.error_summary || "최신 GitHub 결과");
  monitorGithubInbox.append(message);
  const target = String(latest?.url || "");
  if (/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/actions\/runs\/[1-9][0-9]*$/.test(target)) {
    const link = document.createElement("a");
    link.href = target;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "열기";
    monitorGithubInbox.append(link);
  }
}
//@@FN_END:renderMonitorGithubInbox

//@@FN_START:refreshMonitorEndpointRegistry
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
//@@FN_END:refreshMonitorEndpointRegistry

//@@FN_START:refreshMonitorIdentityIndex
async function refreshMonitorIdentityIndex(state, force = false) {
  const now = Date.now();
  if (!force && now - monitorIdentityIndexRefreshAt < MONITOR_IDENTITY_INDEX_REFRESH_MS) return false;
  if (monitorIdentityIndexInflight) return monitorIdentityIndexInflight;

  const openEndpoints = (Array.isArray(state?.endpoints) ? state.endpoints : []).filter((ep) =>
    String(ep?.presence_state || "").toUpperCase() === "OPEN"
    && ["GOOGLE", "NAVER"].includes(String(ep?.profile_id || "").toUpperCase())
  );
  // The roster renders every open tab, not only Chrome's active tab. Limit
  // this read-only projection by open instance state, otherwise an inactive
  // node remains D? until a user happens to click it.
  const bctOpenNodes = (Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [])
    .filter((node) => String(node?.instanceState || "").toUpperCase() === "OPEN");
  if ((!openEndpoints.length && !bctOpenNodes.length) || !monitorDesktopState.desktopIds.length) return false;

  const wanted = new Set([
    ...openEndpoints.map((ep) => String(ep?.conversation_key || "").trim()),
    ...bctOpenNodes.map((node) => String(node?.conversationKey || "").trim()),
  ].filter(Boolean));
  // Dot and confirmed Codex-local surfaces deliberately do not manufacture a
  // /c/<UUID> conversation key.  They still need a fresh Native Chrome-window
  // snapshot for the display-only HWND/desktop join.  Keep UUID matching below
  // for mutation-safe identity, but do not skip the read-only projection merely
  // because every currently open BCT node is one of those non-UUID surfaces.
  if (!wanted.size && !bctOpenNodes.length) return false;

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
        const iconicLifecycleLocked = previous?.iconicLifecycleLocked === true;
        const nextLocation = {
          ...(previous || {}), hwnd, title: String(item?.title || previous?.title || ""),
          className: "Chrome_WidgetWin_1", desktopId, desktop: i + 1,
          left: Number(item?.left ?? previous?.left) || 0, top: Number(item?.top ?? previous?.top) || 0,
          width: Number(item?.width ?? previous?.width) || 0, height: Number(item?.height ?? previous?.height) || 0,
          z: Number(item?.z ?? previous?.z) || 0, iconic: iconicLifecycleLocked || Boolean(item?.iconic), iconicLifecycleLocked, visible: Boolean(item?.visible), at: now,
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
    // The initial desktop snapshot can arrive before the BCT identity join.
    // Rebuild the display mapping and its minimized D# summary after that join
    // even when no Worker-list row changed; otherwise already-minimized
    // Chrome windows stay absent until a later unrelated lifecycle event.
    refreshMonitorBctDisplayWindowHwnd();
    syncMonitorMinimizedNodeBadges(monitorLastAiState);
    if (projectionChanged && monitorLastAiState) renderWorkers(monitorLastAiState);
    return projectionChanged;
  })().finally(() => { monitorIdentityIndexInflight = null; });

  monitorIdentityIndexInflight = job;
  return job;
}
//@@FN_END:refreshMonitorIdentityIndex

//@@FN_START:refreshMonitorWindowIdentity
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
//@@FN_END:refreshMonitorWindowIdentity

//@@FN_START:monitorUniqueBctConversationNodes
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
//@@FN_END:monitorUniqueBctConversationNodes

//@@FN_START:renderMonitorBctWindowNodes
function renderMonitorBctWindowNodes(nodes) {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorWorkers) return;
  // A background refresh can arrive while the pointer is captured by a card.
  // Replacing that card would silently cancel every drag, so retain the newest
  // snapshot and paint it once the current drop has finished instead.
  if (monitorBctPointerDrag) {
    monitorBctDeferredNodeRender = nodes;
    return;
  }
  monitorBctDeferredNodeRender = null;
  nodes = monitorUniqueBctConversationNodes(nodes);
  observeMonitorBctNodeFirstSeen(nodes);
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
    Number(right.key === "__unassigned__") - Number(left.key === "__unassigned__") ||
    left.name.localeCompare(right.name, "ko"));
  for (const group of orderedGroups) {
    const localNodeOrder = new Map(
      (monitorBctNodeOrderByScope.get(group.key) || []).map((key, index) => [String(key).toLowerCase(), index]),
    );
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
      // A supervisor is globally unassigned and a Manager is singular per
      // network. Keep either coordination role at the visual head; manual
      // drag order applies to the ordinary nodes that follow.
      const roleDifference = monitorBctNodeRoleRank(left) - monitorBctNodeRoleRank(right);
      if (roleDifference) return roleDifference;
      const viewNodeNumber = (node) => {
        const digits = String(node.nodeLabel || "").replace(/^N/i, "");
        return /^\d+$/.test(digits) ? Number(digits) : Number.MAX_SAFE_INTEGER;
      };
      if (monitorBctNodeDisplayState().viewMode === "number") {
        const difference = viewNodeNumber(left) - viewNodeNumber(right);
        if (difference) return difference;
      }
      if (monitorBctNodeDisplayState().viewMode === "observed") {
        const difference = Number(monitorBctNodeDisplayState().firstObservedAt.get(monitorBctNodeObservedKey(left)) || Number.MAX_SAFE_INTEGER)
          - Number(monitorBctNodeDisplayState().firstObservedAt.get(monitorBctNodeObservedKey(right)) || Number.MAX_SAFE_INTEGER);
        if (difference) return difference;
      }
      if (monitorBctNodeDisplayState().viewMode === "burden") {
        const difference = monitorBctNodeBurdenScore(right) - monitorBctNodeBurdenScore(left);
        if (difference) return difference;
      }
      const leftLocalOrder = localNodeOrder.get(monitorBctNodeSelectionKey(left).toLowerCase());
      const rightLocalOrder = localNodeOrder.get(monitorBctNodeSelectionKey(right).toLowerCase());
      if (leftLocalOrder != null || rightLocalOrder != null) {
        if (leftLocalOrder == null) return 1;
        if (rightLocalOrder == null) return -1;
        if (leftLocalOrder !== rightLocalOrder) return leftLocalOrder - rightLocalOrder;
      }
      const nodeNumber = (node) => {
        const digits = String(node.nodeLabel || "").replace(/^N/i, "");
        return /^\d+$/.test(digits) ? Number(digits) : Number.MAX_SAFE_INTEGER;
      };
      const leftManual = Number(left.displayOrder || 0);
      const rightManual = Number(right.displayOrder || 0);
      if (leftManual > 0 || rightManual > 0) {
        if (leftManual <= 0) return 1;
        if (rightManual <= 0) return -1;
        if (leftManual !== rightManual) return leftManual - rightManual;
      }
      const numberDifference = nodeNumber(left) - nodeNumber(right);
      if (numberDifference) return numberDifference;
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
    const managerStatus = group.key === "__unassigned__" ? null
      : (Array.isArray(monitorBctManagerStatuses) ? monitorBctManagerStatuses : [])
        .find((item) => String(item?.scopeId || "") === String(group.key || ""));
    let managerNotice = "";
    if (managerStatus?.status === "NOT_OPEN") {
      managerNotice = ` · Manager 닫힘: ${managerStatus.managerNodeLabel || "기록됨"}`;
      groupSection.classList.add("monitor-bct-manager-not-open");
    } else if (managerStatus?.status === "MISSING") {
      managerNotice = " · Manager 없음";
    } else if (managerStatus?.status === "CONFLICT") {
      managerNotice = " · Manager 충돌";
      groupSection.classList.add("monitor-bct-manager-conflict");
    }
    groupText.textContent = `${group.name} · ${group.nodes.length}${managerNotice}`;
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
    if (node.dotKey) row.classList.add("monitor-bct-orchestrator");
    if (node.codexLocalReference) row.classList.add("monitor-bct-codex-local");
    row.dataset.tabId = String(node.tabId);
    row.dataset.windowId = String(node.windowId);
    row.dataset.instanceId = String(node.instanceId || "");
    row.dataset.sessionId = String(node.sessionId || "");
    row.dataset.nodeIndex = String(index + 1);
    row.dataset.nodeLabel = node.nodeLabel || "";
    row.dataset.conversationKey = node.conversationKey;
    row.dataset.nodeSelectionKey = monitorBctNodeSelectionKey(node);
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
    number.textContent = node.dotKey ? "DOT" : node.nodeLabel || "N?";
    number.title = node.codexLocalReference
      ? "Codex 비공개 로컬 참조의 조회 전용 C 번호 · 전송 대상 아님"
      : node.nodeLabel
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
    const detail = monitorBctNodeDetail(node, desktopPosition, nativeLocation);
    location.textContent = detail.text;
    location.title = detail.title;
    body.append(location);
    const presence = document.createElement("span");
    const stale = node.displayStale === true || node.instanceState !== "OPEN";
    presence.className = `monitor-bct-node-presence${!stale && node.generating === true ? " is-busy" : ""}`;
    presence.setAttribute("aria-label", stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음");
    presence.title = stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음";
    globalThis.MonitorStatusIcon?.render?.(presence, { activity: !stale && node.generating === true ? "play" : "pause" });
    row.append(number, body, presence);
    const roleTags = Array.isArray(node.roleTags) ? node.roleTags.map((tag) => String(tag).trim().toLowerCase()) : [];
    row.classList.toggle("is-manager", roleTags.includes("manager"));
    row.classList.toggle("is-supervisor", !String(node.scopeName || "").trim() && roleTags.includes("supervisor"));
    row.classList.toggle("is-dot", Boolean(node.dotKey));
    installMonitorBctRoleLongPress(row, node);
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
        // Explicit row selection acknowledges a terminal report; observed
        // Chrome tab/foreground changes never acknowledge work.
        const selectedReport = monitorNodeReportState(node,monitorLastAiState);
        const acknowledge = globalThis.MonitorNodeTokenVisualContract?.shouldAcknowledge(selectedReport) === true;
        if (acknowledge) monitorAcknowledgePostWork(selectedReport.conversationKey,"");
        monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(node);
        // Preserve the exact D# selected number (white and enlarged) before
        // attempting any linked window interaction.
        syncMonitorBctNodeTargetHighlight();
        syncMonitorMinimizedNodeBadges(monitorLastAiState);
        getMonitorBctNodeInteractionService().select(hwnd);
        if (acknowledge) {
          syncMonitorAllDesktopThumbnailNodeBadges();
          if (monitorLastAiState) renderWorkers(monitorLastAiState);
        }
        setMonitorStatus(`${node.nodeLabel || "N?"} 연결 웹브라우저 창을 표시했습니다.`, true, 1800);
      }).catch((error) => {
        setMonitorStatus(`연결 창 표시 실패 · ${error?.message || error}`, false, 3500);
      });
    });
    row.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("monitor-bct-node-switch-pending");
      const tabTarget = {
        tabId: node.tabId,
        windowId: node.windowId,
        conversationKey: node.conversationKey,
        dotKey: node.dotKey,
        codexLocalReference: node.codexLocalReference,
      };
      // A newly-created Chrome window does not have an exact HWND binding
      // until its tab becomes the observed active conversation.  Select the
      // exact tab first, then refresh the current-session HWND join and move
      // its desktop/window.  This never guesses a tab or conversation.
      void getMonitorBctNodeInteractionService().focusExactTab(tabTarget).then(() =>
        resolveMonitorBctNodeHwnd(node)
      ).then((hwnd) => (
        monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(node),
        getMonitorBctNodeInteractionService().activate(hwnd, tabTarget)
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
    if (node.conversationKey || node.dotKey || node.codexLocalReference) {
      row.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(node);
        monitorBctNodeHighlightedHwnd = "";
        syncMonitorBctNodeTargetHighlight();
        syncMonitorMinimizedNodeBadges(monitorLastAiState);
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
    const activeCount = nodes.filter((node) => node.active === true).length;
    const generatingCount = nodes.filter((node) => node.generating === true).length;
    monitorBctNodeSummary.textContent = stale
      ? `${nodes.length}개 연결 · RCC 일시 지연 · 마지막 확인 목록`
      : `${nodes.length}개 연결 · 활성 ${activeCount} · 응답 중 ${generatingCount}`;
  }
}
//@@FN_END:renderMonitorBctWindowNodes

//@@FN_START:resolveMonitorBctNodeDisplayHwnd
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
//@@FN_END:resolveMonitorBctNodeDisplayHwnd

//@@FN_START:resolveMonitorBctNodeHwnd
async function resolveMonitorBctNodeHwnd(node) {
  let hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (hwnd) return String(hwnd);
  await refreshMonitorIdentityIndex(monitorLastAiState, true);
  refreshMonitorBctCurrentSessionWindowHwnd();
  hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (!hwnd) throw new Error("현재 세션에서 이 노드와 웹브라우저 창을 정확히 대조하지 못함");
  return String(hwnd);
}
//@@FN_END:resolveMonitorBctNodeHwnd

//@@FN_START:resolveStableMonitorLocation
function resolveStableMonitorLocation(worker, state) { return monitorCanonicalPhysicalLocation(worker, state)?.label || "UNMAPPED"; }
//@@FN_END:resolveStableMonitorLocation

//@@FN_START:scheduleMonitorMinimizedBadgeConvergence
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
//@@FN_END:scheduleMonitorMinimizedBadgeConvergence

//@@FN_START:syncMonitorBctNodeLocationLabels
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
    // A blank conversation key is valid for Dot and Codex-local references, so
    // it cannot identify a roster row.  Use the same exact selection key that
    // rendered the row; this keeps its D# detail attached to its own Chrome
    // window rather than the first other blank-key node.
    const node = monitorBctWindowNodesCache.find((item) =>
      monitorBctNodeSelectionKey(item) === String(row.dataset.nodeSelectionKey || "")
    );
    if (position) {
      const detail = monitorBctNodeDetail(node, index, location);
      position.textContent = detail.text;
      position.title = detail.title;
    }
    row.dataset.desktopNumber = index >= 0 ? String(index + 1) : "";
  }
}
//@@FN_END:syncMonitorBctNodeLocationLabels

//@@FN_START:syncMonitorBctNodeTargetHighlight
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
//@@FN_END:syncMonitorBctNodeTargetHighlight

//@@FN_START:syncMonitorMinimizedNodeBadges
function syncMonitorMinimizedNodeBadges(state = monitorLastAiState) {
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") === false) {
    for (const host of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-minimized-nodes")) host.remove();
    return;
  }
  const tokensByDesktop = monitorMinimizedNodeTokensByDesktop(state);
  // This is a module-scoped `let`, not a property of `window`. Reading it via
  // globalThis loses every list-originated selection, so minimized badges never
  // receive their selected index even though the list row is highlighted.
  const selectedKey = String(monitorBctSelectedNodeKey || "");
  const selectedNode = (Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : []).find((node) => monitorBctNodeSelectionKey(node) === selectedKey);
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
    // A Chrome tab move may refresh the D# summary a moment before its tabId
    // reaches the list cache.  Prefer the exact tabId, then fall back to the
    // stable, unique BCT node number that is already rendered in this same
    // desktop summary.  `?` never uses this fallback because it is not unique.
    let selectedIndex = tokens.findIndex((item) => selectedTabId && Number(item.tabId) === selectedTabId);
    if (selectedIndex < 0 && selectedToken !== "?") {
      selectedIndex = tokens.findIndex((item) => item.token === selectedToken);
    }
    const width = Number(label.getBoundingClientRect?.().width || 0);
    const budget = Math.max(9, Math.floor((width || 118) / 6.2));
    let first = 0, last = Math.max(0, tokens.length - 1);
    // Each token is a separate compact badge. Count the visible spaces and
    // ellipses too, so overflow becomes `… 2 3 4 …` rather than clipping the
    // selected number at the edge.
    const lengthFor = (left, right) => (left > 0 ? 2 : 0) + (right < tokens.length - 1 ? 2 : 0) + tokens.slice(left, right + 1).map((item) => item.token).join(" ").length;
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
    const fullText = tokens.length ? tokens.map((item) => item.token).join(" ") : "";
    const parts = [];
    if (tokens.length) {
      if (first > 0) { const more = document.createElement("span"); more.className = "monitor-desktop-minimized-more"; more.textContent = "…"; parts.push(more); }
      for (let index = first; index <= last; index += 1) {
        const badge = document.createElement("span");
        const selected = index === selectedIndex;
        const token = tokens[index];
        const nodes = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [];
        let node = Number.isInteger(Number(token.tabId))
          ? nodes.find((candidate) => Number(candidate?.tabId) === Number(token.tabId))
          : null;
        if (!node && token.token !== "?") {
          const matches = nodes.filter((candidate) => String(candidate?.nodeLabel || "").trim().replace(/^N/i, "") === token.token);
          if (matches.length === 1) node = matches[0];
        }
        const report = monitorNodeReportState(node,state);
        const visuals = globalThis.MonitorNodeTokenVisualContract;
        const kind = visuals?.activityFor(report) || "";
        const roleClasses = visuals?.classesFor(node,report,selected) || [];
        const reportClass = kind ? " has-report is-" + kind : "";
        badge.className = ["monitor-desktop-minimized-node",...roleClasses,
          selected ? "monitor-desktop-minimized-node-selected" : ""].filter(Boolean).join(" ");
        badge.textContent = token.token;
        const interactive = visuals?.shouldAcknowledge(report) === true;
        badge.title = `최소화 노드 ${token.token}${reportClass ? ` · ${String(report?.label || (kind === "working" ? "처리 중" : kind === "abnormal" ? "상태 확인 필요" : "확인 대기"))}${interactive ? " · 클릭하여 확인" : ""}` : ""}`;
        if (interactive) {
          badge.setAttribute("role","button");
          badge.setAttribute("tabindex","0");
          badge.addEventListener("pointerdown",(event)=>event.stopPropagation());
          badge.addEventListener("click",(event)=>{
            event.preventDefault();
            event.stopPropagation();
            const conversationKey=String(report?.conversationKey||"").trim();
            if(!conversationKey)return;
            if(node && typeof monitorBctNodeSelectionKey === "function")
              monitorBctSelectedNodeKey=monitorBctNodeSelectionKey(node);
            monitorAcknowledgePostWork(conversationKey,"");
            syncMonitorMinimizedNodeBadges(state);
            syncMonitorAllDesktopThumbnailNodeBadges();
            if(monitorLastAiState)renderWorkers(monitorLastAiState);
          });
        }
        parts.push(badge);
      }
      if (last < tokens.length - 1) { const more = document.createElement("span"); more.className = "monitor-desktop-minimized-more"; more.textContent = "…"; parts.push(more); }
    }
    host.className = `monitor-desktop-minimized-nodes${selectedIndex >= 0 ? " monitor-bct-minimized-selection" : ""}`;
    host.title = fullText ? `최소화 노드 ${fullText}` : "";
    host.replaceChildren(...parts);
    host.hidden = tokens.length === 0;
  }
}
//@@FN_END:syncMonitorMinimizedNodeBadges
