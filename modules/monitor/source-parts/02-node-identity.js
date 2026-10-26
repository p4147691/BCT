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

function monitorStableBrowserNodeKey(worker) {

  const ep=worker?.__endpoint||null;

  const tabId=String(ep?.tab_id??"").trim();

  const conversationKey=String(worker?.conversation_key||ep?.conversation_key||"").trim();

  return tabId&&conversationKey ? `tab:${tabId}:chat:${conversationKey}` : "";

}

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

function monitorNodeNumbersForMinimizedHwnd(hwnd, state = monitorLastAiState) {
  const key = String(hwnd || "").trim();
  if (!key) return [];

  return monitorActNodeNumbersForHwnd(key, state);


}

// The desktop-label summary is reserved for minimized ChatGPT windows. Open
// ChatGPT windows render their BCT/RCC number directly on their thumbnail.
function monitorMinimizedNodeSlotsByDesktop(state = monitorLastAiState) {
  return monitorMinimizedNodeBadgeContract?.slotsByDesktop?.({
    locations: monitorWindowDesktopLocations,
    numbersForHwnd: (hwnd) => monitorBadgeNodeNumbersForHwnd(hwnd, state),
  }) || new Map();
}

function profileForMonitorWorker(worker, state) {

  const profileId = String(worker?.profile_id || "").toUpperCase();

  return (Array.isArray(state?.profiles) ? state.profiles : [])

    .find((item) => String(item?.profile_id || "").toUpperCase() === profileId) || null;

}

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

function monitorEndpointWindowKey(endpoint) {

  if (!endpoint) return "";

  return [endpoint.transport_instance_id, endpoint.window_id].map((v)=>String(v ?? "")).join(":");

}

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
const monitorWorkersProjectionCache = new WeakMap();

function monitorWorkersProjectionForState(state) {
  if (!state || typeof state !== "object") return monitorWorkersForState(state);
  const cached = monitorWorkersProjectionCache.get(state);
  if (cached) return cached;
  const workers = monitorWorkersForState(state);
  monitorWorkersProjectionCache.set(state, workers);
  return workers;
}

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

function monitorDirectConversationGenerationState(conversationKey, now = Date.now()) {

  const key=String(conversationKey||"").trim();

  const tabStates=[...monitorDirectGenerationByTab.values()].filter((item)=>item.conversationKey===key&&now-Number(item.at||0)<=MONITOR_DIRECT_GENERATION_TTL_MS);

  if(tabStates.length) return tabStates.some((item)=>item.generating===true);

  const item=monitorDirectGenerationByConversation.get(key);

  if (!item || now-Number(item.at||0)>MONITOR_DIRECT_GENERATION_TTL_MS) return null;

  return item.generating===true;

}

function monitorDirectEndpointGenerationState(endpoint, now = Date.now()) {

  const key=String(endpoint?.conversation_key||"").trim(), tabId=String(endpoint?.tab_id??"").trim();

  if(!key||!tabId)return null;

  const item=monitorDirectGenerationByTab.get(`${key}:${tabId}`);

  if(!item||now-Number(item.at||0)>MONITOR_DIRECT_GENERATION_TTL_MS)return null;

  return item.generating===true;

}

function monitorDirectEndpointUserAttention(endpoint) {
  const key=String(endpoint?.conversation_key||"").trim(), tabId=String(endpoint?.tab_id??"").trim();
  if(!key)return null;
  // User attention is event-driven and stays visible until the content script explicitly reports that it cleared.
  // Generation/busy state still uses MONITOR_DIRECT_GENERATION_TTL_MS separately.
  if(tabId){
    const tabItem=monitorDirectGenerationByTab.get(`${key}:${tabId}`);
    if(tabItem)return tabItem.userAttention||null;
  }
  return monitorDirectGenerationByConversation.get(key)?.userAttention||null;
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

function monitorBrowserWindowIdForEndpoint(endpoint) {
  const metadata = endpoint?.metadata && typeof endpoint.metadata === "object" ? endpoint.metadata : {};
  return String(endpoint?.window_id ?? endpoint?.browser_window_id ?? metadata.window_id ?? metadata.browser_window_id ?? "").trim();
}

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
  if (!conversationKey) return { ok:true, changed:false, transitional:true };

  const hwnd = monitorHwndForBrowserWindowId(message?.windowId, state);
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
let monitorBrowserVisualRefreshTimer = 0;
let monitorBrowserVisualRefreshInFlight = false;
const MONITOR_BROWSER_VISUAL_REFRESH_DEBOUNCE_MS = 360;

function scheduleMonitorBrowserVisualRefresh(message) {
  const windowId = Number(message?.windowId);
  if (!Number.isInteger(windowId)) return;

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
    if (!desktopIds.size) return;

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
  await monitorPublishSharedRuntime("alert",`${MONITOR_SHARED_INSTANCE_PREFIX}${hostProfile}`,{symbol:"",tone:"monitor-instance",label:JSON.stringify({profile:hostProfile,build_id:MONITOR_RUNTIME_BUILD_ID,manifest_version:chrome.runtime.getManifest().version,reload_token:String(monitorReloadToken||""),monitor_title:document.title,hwnd,reason:String(reason||"event"),thumbnail_projection:monitorThumbnailProjectionRuntimeDiagnostics(),seen_at_ms:Date.now()})});

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

function monitorIsActivelyWorking(work) {

  return ["running", "working", "busy", "executing", "in_progress"].includes(String(work || "").toLowerCase());

}

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

