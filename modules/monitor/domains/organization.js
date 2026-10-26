//@@FN_START:clearMonitorHierarchyTargets
function clearMonitorHierarchyTargets(){for(const el of monitorStructurePanel.querySelectorAll("[data-hierarchy-slot]"))el.classList.remove("monitor-org-socket-target");}
//@@FN_END:clearMonitorHierarchyTargets

//@@FN_START:closeMonitorStructure
function closeMonitorStructure(){void monitorStructurePersistWorkingDraft();monitorStructureOpen=false;monitorStructurePanel.hidden=true;if(monitorLastAiState)renderWorkers(monitorLastAiState);}
//@@FN_END:closeMonitorStructure

//@@FN_START:monitorHierarchyApplyDrop
async function monitorHierarchyApplyDrop(target,hwnd){const node=monitorStructureNodeForHwnd(hwnd);if(!node)throw new Error("웹 노드를 찾지 못함");const desktopId=String(target?.dataset?.desktopId||"");if(target?.dataset?.orgDeskDrop&&desktopId)return monitorStructureMoveNodeToDesk(String(node.conversation_key||""),desktopId);return monitorStructureDropNode(String(target?.dataset?.hierarchySlot||""),node,desktopId);}
//@@FN_END:monitorHierarchyApplyDrop

//@@FN_START:monitorHierarchyTargetAt
function monitorHierarchyTargetAt(x,y){return document.elementsFromPoint(x,y).find(el=>el?.dataset?.hierarchySlot||el?.dataset?.orgDeskDrop)||null;}
//@@FN_END:monitorHierarchyTargetAt

//@@FN_START:monitorStructureAlignLowerDesksToOrchestrator
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
//@@FN_END:monitorStructureAlignLowerDesksToOrchestrator

//@@FN_START:monitorStructureApplyActHierarchy
function monitorStructureApplyActHierarchy(data){

  const nextLinks=monitorStructureAuthorityOverrides(data,monitorStructureAutoLayout());

  monitorStructureLinkOverrides=nextLinks;monitorStructurePersistLinks();

  const nextControls={};for(const item of (Array.isArray(data?.node_controls)?data.node_controls:[])){const key=String(item?.conversation_key||"").trim();if(key)nextControls[key]={auto:Boolean(item?.auto_wake??item?.enabled)};}

  monitorStructureNodeControls=nextControls;monitorStructurePersistNodeControls();

  if(Array.isArray(data?.resource_edges))monitorStructureResourceEdges=data.resource_edges.map(e=>({supervisor_key:String(e?.supervisor_key||""),resource_id:String(e?.resource_id||""),relation:"USES"})).filter(e=>e.supervisor_key&&e.resource_id);

  if(Number.isInteger(Number(data?.organization_generation)))monitorStructureOrganizationGeneration=Number(data.organization_generation);

}
//@@FN_END:monitorStructureApplyActHierarchy

//@@FN_START:monitorStructureApplyBaseline
function monitorStructureApplyBaseline(){
  if(!monitorStructureBaseline)return false;
  return monitorStructureApplyHistorySnapshot(monitorStructureBaseline);
}
//@@FN_END:monitorStructureApplyBaseline

//@@FN_START:monitorStructureApplyHistorySnapshot
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
//@@FN_END:monitorStructureApplyHistorySnapshot

//@@FN_START:monitorStructureAuthorityOverrides
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
//@@FN_END:monitorStructureAuthorityOverrides

//@@FN_START:monitorStructureAutoLayout
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
//@@FN_END:monitorStructureAutoLayout

//@@FN_START:monitorStructureAvailableNodes
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
//@@FN_END:monitorStructureAvailableNodes

//@@FN_START:monitorStructureBaselineIsCompatible
function monitorStructureBaselineIsCompatible(snapshot){
  if(!snapshot||typeof snapshot!=="object")return false;
  const liveKeys=new Set(monitorStructureAvailableNodes().map(node=>String(node?.conversation_key||"")).filter(Boolean));
  const required=new Set();
  const add=node=>{const key=String(node?.conversation_key||"");if(key)required.add(key);};
  add(snapshot.socketDraft?.orchestrator);add(snapshot.socketDraft?.aux1);add(snapshot.socketDraft?.aux2);
  for(const node of Object.values(snapshot.socketDraft?.managers||{}))add(node);
  for(const [key,parent] of Object.entries(snapshot.linkOverrides||{})){required.add(String(key));if(parent)required.add(String(parent));}
  for(const key of Object.keys(snapshot.deskMembership||{}))required.add(String(key));
  for(const edge of snapshot.resourceEdges||[]){const supervisor=String(edge?.supervisor_key||"");if(supervisor)required.add(supervisor);}
  const desktops=new Set((monitorDesktopState.desktopIds||[]).map(String));
  const deskValues=[...Object.values(snapshot.deskMembership||{}),...Object.values(snapshot.bundleDesk||{})].map(String).filter(Boolean);
  return [...required].every(key=>liveKeys.has(key))&&deskValues.every(id=>desktops.has(id));
}
//@@FN_END:monitorStructureBaselineIsCompatible

//@@FN_START:monitorStructureBaselineSnapshot
function monitorStructureBaselineSnapshot(){
  return {...monitorStructureHistorySnapshot(),savedAt:Date.now()};
}
//@@FN_END:monitorStructureBaselineSnapshot

//@@FN_START:monitorStructureBuildSavePayload
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
//@@FN_END:monitorStructureBuildSavePayload

//@@FN_START:monitorStructureBundleCard
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
//@@FN_END:monitorStructureBundleCard

//@@FN_START:monitorStructureBundleIsActive
function monitorStructureBundleIsActive(kind){
  if(kind==="local")return monitorLocalLlmIsUsable();
  return (monitorStructureBundleKinds()[kind]||[]).some(node=>monitorStructureNodeIsActive(node,kind));
}
//@@FN_END:monitorStructureBundleIsActive

//@@FN_START:monitorStructureBundleKinds
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
//@@FN_END:monitorStructureBundleKinds

//@@FN_START:monitorStructureBundleName
function monitorStructureBundleName(kind){
  return kind==="local"?"L-LLM":kind==="external"?"E-LLM":"G-CODEX";
}
//@@FN_END:monitorStructureBundleName

//@@FN_START:monitorStructureBundleNode
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
//@@FN_END:monitorStructureBundleNode

//@@FN_START:monitorStructureBundleOrder
function monitorStructureBundleOrder(){return ["local","external","codex-google"];}
//@@FN_END:monitorStructureBundleOrder

//@@FN_START:monitorStructureBundlePalette
function monitorStructureBundlePalette(){const bar=document.createElement("div");bar.className="monitor-org-bundle-palette";for(const kind of monitorStructureBundleOrder())if(!monitorStructureBundleDesk[kind]&&!monitorStructureManagerBundleDesk[kind])bar.append(monitorStructureBundleCard(kind));return bar;}
//@@FN_END:monitorStructureBundlePalette

//@@FN_START:monitorStructureClearDragFeedback
function monitorStructureClearDragFeedback(removeGhost=true){if(removeGhost){monitorStructurePointerGhost?.remove();monitorStructurePointerGhost=null;}for(const el of monitorStructurePanel.querySelectorAll(".is-desk-drop,.is-socket-drop,.monitor-org-link-target,.monitor-org-link-dragging"))el.classList.remove("is-desk-drop","is-socket-drop","monitor-org-link-target","monitor-org-link-dragging");}
//@@FN_END:monitorStructureClearDragFeedback

//@@FN_START:monitorStructureCloneDraftValue
function monitorStructureCloneDraftValue(value){
  try{return structuredClone(value);}catch(_){try{return JSON.parse(JSON.stringify(value));}catch(__){return value;}}
}
//@@FN_END:monitorStructureCloneDraftValue

//@@FN_START:monitorStructureConnectNodesByPosition
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
//@@FN_END:monitorStructureConnectNodesByPosition

//@@FN_START:monitorStructureDefaultParents
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
//@@FN_END:monitorStructureDefaultParents

//@@FN_START:monitorStructureDeskNodeGrid
function monitorStructureDeskNodeGrid(nodes,desktopId){
  const grid=monitorStructureWorkerStrip(nodes||[]);
  const bundles=[...monitorStructureInstalledBundles(desktopId).children];
  bundles.sort((a,b)=>Number(b.classList.contains("is-available"))-Number(a.classList.contains("is-available")));
  grid.append(...bundles,monitorStructureDeskTransferSlot(desktopId));
  return grid;
}
//@@FN_END:monitorStructureDeskNodeGrid

//@@FN_START:monitorStructureDeskTransferSlot
function monitorStructureDeskTransferSlot(desktopId){const slot=document.createElement("div");slot.className="monitor-org-node-slot";slot.dataset.desktopId=String(desktopId||"");slot.textContent="+";slot.title="이 데스크로 노드 또는 자원 이동";return slot;}
//@@FN_END:monitorStructureDeskTransferSlot

//@@FN_START:monitorStructureDetachAll
function monitorStructureDetachAll(nodeKey){

  nodeKey=String(nodeKey||"");if(!nodeKey)return false;const historyBefore=monitorStructureHistorySnapshot();const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());let changed=false;

  if(Object.prototype.hasOwnProperty.call(parents,nodeKey)){monitorStructureLinkOverrides[nodeKey]=null;changed=true;}

  for(const [child,parent] of Object.entries(parents))if(String(parent||"")===nodeKey){monitorStructureLinkOverrides[child]=null;changed=true;}

  if(changed){monitorStructureDirty=true;monitorStructureHistoryCommit(historyBefore);renderMonitorStructure();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="노드 연결 해제됨 · 부모/자식 관리선 모두 끊김";}return changed;
}
//@@FN_END:monitorStructureDetachAll

//@@FN_START:monitorStructureDetachBlankStep
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
//@@FN_END:monitorStructureDetachBlankStep

//@@FN_START:monitorStructureDrawLinks
function monitorStructureDrawLinks(layout){requestAnimationFrame(()=>{if(!monitorStructureOpen)return;const svg=document.getElementById("monitorStructureLinks");if(!svg)return;const svgRect=svg.getBoundingClientRect();svg.setAttribute("viewBox",`0 0 ${svgRect.width} ${svgRect.height}`);svg.replaceChildren();for(const [childKey,parentKey] of Object.entries(monitorStructureEffectiveParents(layout))){const child=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(childKey)}"]`),parent=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(parentKey)}"]`);if(!child||!parent)continue;const a=parent.getBoundingClientRect(),b=child.getBoundingClientRect();const commandPair=Boolean(parent.closest(".monitor-org-command-orchestrator")&&child.closest(".monitor-org-command-aux1,.monitor-org-command-aux2"));let d="";if(commandPair){const childIsLeft=(b.left+b.width/2)<(a.left+a.width/2);const parentX=(childIsLeft?a.left:a.right)-svgRect.left;const parentY=a.top+a.height/2-svgRect.top;const childX=(childIsLeft?b.right:b.left)-svgRect.left;const childY=b.top+b.height/2-svgRect.top;d=`M ${parentX} ${parentY} L ${childX} ${childY}`;}else{const x1=a.left+a.width/2-svgRect.left,y1=a.bottom-svgRect.top,x2=b.left+b.width/2-svgRect.left,y2=b.top-svgRect.top;d=`M ${x1} ${y1} L ${x2} ${y2}`;}const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",d);path.setAttribute("class","monitor-org-link");path.dataset.childKey=String(childKey);path.dataset.parentKey=String(parentKey);svg.append(path);}});}
//@@FN_END:monitorStructureDrawLinks

//@@FN_START:monitorStructureDrawLiveLink
function monitorStructureDrawLiveLink(clientX,clientY){const svg=document.getElementById("monitorStructureLinks");if(!svg||!monitorStructureRelationDragKey)return;svg.querySelector(".monitor-org-link-live")?.remove();const source=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(monitorStructureRelationDragKey)}"]`);if(!source)return;const svgRect=svg.getBoundingClientRect(),a=source.getBoundingClientRect(),x1=a.left+a.width/2-svgRect.left,y1=a.top+a.height/2-svgRect.top,x2=clientX-svgRect.left,y2=clientY-svgRect.top;const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",`M ${x1} ${y1} L ${x2} ${y2}`);path.setAttribute("class","monitor-org-link monitor-org-link-live");svg.append(path);}
//@@FN_END:monitorStructureDrawLiveLink

//@@FN_START:monitorStructureDropNode
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
//@@FN_END:monitorStructureDropNode

//@@FN_START:monitorStructureEffectiveDesktopId
function monitorStructureEffectiveDesktopId(node){const key=String(node?.conversation_key||"");return String(monitorStructureDeskMembership[key]||node?.desktop_id||"");}
//@@FN_END:monitorStructureEffectiveDesktopId

//@@FN_START:monitorStructureEffectiveParents
function monitorStructureEffectiveParents(layout){const parents=monitorStructureDefaultParents(layout);for(const [child,parent] of Object.entries(monitorStructureLinkOverrides||{})){if(parent)parents[child]=parent;else delete parents[child];}return parents;}
//@@FN_END:monitorStructureEffectiveParents

//@@FN_START:monitorStructureEnsureBundleDefaults
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
//@@FN_END:monitorStructureEnsureBundleDefaults

//@@FN_START:monitorStructureExecuteDeskMoves
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
//@@FN_END:monitorStructureExecuteDeskMoves

//@@FN_START:monitorStructureFinalizeDeskMoves
function monitorStructureFinalizeDeskMoves(moveResult){

  for(const item of (Array.isArray(moveResult?.moves)?moveResult.moves:[]))delete monitorStructureDeskMembership[item.nodeKey];

}
//@@FN_END:monitorStructureFinalizeDeskMoves

//@@FN_START:monitorStructureFinishHtmlDragGhost
function monitorStructureFinishHtmlDragGhost(){
  destroyMonitorNodeDragGhost(monitorStructureHtmlDragGhost);
  monitorStructureHtmlDragGhost=null;
}
//@@FN_END:monitorStructureFinishHtmlDragGhost

//@@FN_START:monitorStructureFitViewport
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
//@@FN_END:monitorStructureFitViewport

//@@FN_START:monitorStructureHistoryCommit
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
//@@FN_END:monitorStructureHistoryCommit

//@@FN_START:monitorStructureHistoryKey
function monitorStructureHistoryKey(snapshot){return JSON.stringify(snapshot||{});}
//@@FN_END:monitorStructureHistoryKey

//@@FN_START:monitorStructureHistoryReset
function monitorStructureHistoryReset(){
  monitorStructureUndoStack.length=0;
  monitorStructureRedoStack.length=0;
  monitorStructureUpdateHistoryButtons();
}
//@@FN_END:monitorStructureHistoryReset

//@@FN_START:monitorStructureHistorySnapshot
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
//@@FN_END:monitorStructureHistorySnapshot

//@@FN_START:monitorStructureInstalledBundles
function monitorStructureInstalledBundles(desktopId){const wrap=document.createElement("div");wrap.className="monitor-org-desk-bundles";for(const kind of monitorStructureBundleOrder())if(String(monitorStructureBundleDesk[kind]||"")===String(desktopId||""))wrap.append(monitorStructureBundleCard(kind));return wrap;}
//@@FN_END:monitorStructureInstalledBundles

//@@FN_START:monitorStructureMoveBundleToDesk
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
//@@FN_END:monitorStructureMoveBundleToDesk

//@@FN_START:monitorStructureMoveNodeToDesk
function monitorStructureMoveNodeToDesk(nodeKey,desktopId){nodeKey=String(nodeKey||"");desktopId=String(desktopId||"");if(!nodeKey||!desktopId)return false;const bundleKind=nodeKey.startsWith("LLM:")?nodeKey.slice(4):"";if(monitorStructureBundleOrder().includes(bundleKind))return monitorStructureMoveBundleToDesk(bundleKind,desktopId);const historyBefore=monitorStructureHistorySnapshot();if(String(monitorStructureSocketDraft.orchestrator?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.orchestrator=null;if(String(monitorStructureSocketDraft.aux1?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.aux1=null;if(String(monitorStructureSocketDraft.aux2?.conversation_key||"")===nodeKey)monitorStructureSocketDraft.aux2=null;monitorStructureDeskMembership[nodeKey]=desktopId;for(const [desk,node] of Object.entries(monitorStructureSocketDraft.managers||{})){if(String(node?.conversation_key||"")===nodeKey)delete monitorStructureSocketDraft.managers[desk];}monitorStructureDirty=true;monitorStructureHistoryCommit(historyBefore);renderMonitorStructure();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="이동 예정 · 실행 시 실제 Desk 이동 후 노드 번호 확정";return true;}
//@@FN_END:monitorStructureMoveNodeToDesk

//@@FN_START:monitorStructureNodeControlState
function monitorStructureNodeControlState(key){

  const saved=monitorStructureNodeControls?.[String(key||"")]||{};

  return {auto:Boolean(saved.auto ?? saved.auto_wake ?? false)};

}
//@@FN_END:monitorStructureNodeControlState

//@@FN_START:monitorStructureNodeDisplayName
function monitorStructureNodeDisplayName(node){
  const number=String(node?.label||"").trim();
  const title=String(node?.title||"").trim();
  if(title&&title!==number)return title;
  const role=String(node?.role||"").trim().toUpperCase();
  if(role&&!["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2","MANAGER","WORKER"].includes(role))return role;
  const profile=String(node?.profile_id||"").trim().toUpperCase();
  return profile?("ChatGPT · "+profile):"ChatGPT";
}
//@@FN_END:monitorStructureNodeDisplayName

//@@FN_START:monitorStructureNodeForHwnd
function monitorStructureNodeForHwnd(hwnd){return monitorStructureAvailableNodes().find(node=>String(node.hwnd||"")===String(hwnd||""))||null;}
//@@FN_END:monitorStructureNodeForHwnd

//@@FN_START:monitorStructureNodeFromWorker
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
//@@FN_END:monitorStructureNodeFromWorker

//@@FN_START:monitorStructureNodeIdentityTokens
function monitorStructureNodeIdentityTokens(node){
  const label=String(node?.label||"").trim().toUpperCase();
  if(/^D\d+[-_]\d+$/.test(label))return [`act:${label}`];
  const tabId=String(node?.tab_id??"").trim();
  const conversationKey=String(node?.conversation_key||"").trim();
  if(tabId&&conversationKey)return [`tab:${tabId}:conversation:${conversationKey}`];
  return [`conversation:${conversationKey}`];
}
//@@FN_END:monitorStructureNodeIdentityTokens

//@@FN_START:monitorStructureNodeIsActive
function monitorStructureNodeIsActive(node,kind){
  const status=String(node?.status||node?.availability||node?.connection_status||"").trim().toLowerCase();
  const runtime=String(node?.runtime_state||node?.runtime?.state||node?.llm_runtime_state||"").trim().toLowerCase();
  const activeStates=["available","ready","loaded","busy","working","running","generating","connected","online","healthy"];
  if(kind==="local")return node?.loaded===true||["loaded","busy","working","running","generating"].includes(runtime)
    || ["loaded","busy","working","running","generating"].includes(status);
  return activeStates.includes(runtime)||activeStates.includes(status)
    ||node?.loaded===true||node?.active===true||node?.connected===true||node?.available===true;
}
//@@FN_END:monitorStructureNodeIsActive

//@@FN_START:monitorStructureNodeIsPlacementExempt
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
//@@FN_END:monitorStructureNodeIsPlacementExempt

//@@FN_START:monitorStructureNodeShortNumber
function monitorStructureNodeShortNumber(node){
  const label=String(node?.label||"").trim();
  const match=label.match(/^D\d+[-_](\d+)$/i);
  return match?match[1]:(label||"NODE");
}
//@@FN_END:monitorStructureNodeShortNumber

//@@FN_START:monitorStructurePersistBaseline
function monitorStructurePersistBaseline(){
  const snapshot=monitorStructureBaselineSnapshot();
  monitorStructureBaseline=monitorStructureCloneDraftValue(snapshot);
  return chrome.storage.local.set({[MONITOR_STRUCTURE_BASELINE_KEY]:snapshot});
}
//@@FN_END:monitorStructurePersistBaseline

//@@FN_START:monitorStructurePersistLinks
function monitorStructurePersistLinks(){chrome.storage.local.set({[MONITOR_STRUCTURE_LINK_KEY]:monitorStructureLinkOverrides});}
//@@FN_END:monitorStructurePersistLinks

//@@FN_START:monitorStructurePersistNodeControls
function monitorStructurePersistNodeControls(){chrome.storage.local.set({[MONITOR_STRUCTURE_NODE_CONTROL_KEY]:monitorStructureNodeControls});}
//@@FN_END:monitorStructurePersistNodeControls

//@@FN_START:monitorStructurePersistSavedLocal
function monitorStructurePersistSavedLocal(){

  monitorStructurePersistSockets();monitorStructurePersistLinks();

  chrome.storage.local.set({[MONITOR_STRUCTURE_DESK_MEMBERSHIP_KEY]:monitorStructureDeskMembership,[MONITOR_STRUCTURE_BUNDLE_DESK_KEY]:monitorStructureBundleDesk});

}
//@@FN_END:monitorStructurePersistSavedLocal

//@@FN_START:monitorStructurePersistSockets
function monitorStructurePersistSockets(){chrome.storage.local.set({[MONITOR_STRUCTURE_SOCKET_KEY]:monitorStructureSocketDraft});}
//@@FN_END:monitorStructurePersistSockets

//@@FN_START:monitorStructurePersistWorkingDraft
function monitorStructurePersistWorkingDraft(){
  const snapshot={...monitorStructureHistorySnapshot(),savedAt:Date.now()};
  return chrome.storage.local.set({[MONITOR_STRUCTURE_WORKING_DRAFT_KEY]:snapshot});
}
//@@FN_END:monitorStructurePersistWorkingDraft

//@@FN_START:monitorStructurePointerTargetAt
function monitorStructurePointerTargetAt(x,y,sourceKey){const elements=document.elementsFromPoint(x,y);const node=elements.map(el=>el?.closest?.(".monitor-org-node-card[data-node-key]")).find(el=>el&&String(el.dataset.nodeKey||"")!==sourceKey)||null;if(node)return {kind:"node",element:node};const socket=elements.map(el=>el?.closest?.(".monitor-org-socket[data-hierarchy-slot]")).find(el=>el&&!el.querySelector(".monitor-org-node-card[data-node-key]"))||null;if(socket)return {kind:"socket",element:socket};const desk=monitorStructureSlotAtPoint(x,y);if(desk)return {kind:"desk",element:desk};const canvas=elements.map(el=>el?.closest?.(".monitor-org-pyramid")).find(Boolean)||null;return canvas?{kind:"blank",element:canvas}:null;}
//@@FN_END:monitorStructurePointerTargetAt

//@@FN_START:monitorStructureReconcileSnapshot
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
//@@FN_END:monitorStructureReconcileSnapshot

//@@FN_START:monitorStructureRedoAction
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
//@@FN_END:monitorStructureRedoAction

//@@FN_START:monitorStructureRefreshAuthority
async function monitorStructureRefreshAuthority(){

  const [hr,rr,ar,wr,mr]=await Promise.all([actFetch(ORCHESTRATOR_HIERARCHY_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_RESOURCES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_AI_NODES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_ORG_WORKSPACES_URL,{cache:"no-store"}),actFetch(ORCHESTRATOR_EXECUTOR_METRICS_URL,{cache:"no-store"})]);

  const h=await hr.json().catch(()=>null),r=await rr.json().catch(()=>null),a=await ar.json().catch(()=>null),w=await wr.json().catch(()=>null),m=await mr.json().catch(()=>null);

  if(!hr.ok||!h?.ok)throw new Error(h?.error||`HTTP ${hr.status}`);if(rr.ok&&r?.ok){h.resource_edges=Array.isArray(r.resource_edges)?r.resource_edges:[];h.organization_generation=r.organization_generation;}

  monitorStructureAiNodes=ar.ok&&a?.ok&&Array.isArray(a.nodes)?a.nodes:[];monitorStructureWorkspaces=wr.ok&&w?.ok&&Array.isArray(w.workspaces)?w.workspaces:[];monitorStructureExecutorMetrics=mr.ok&&m?.ok?m:null;monitorStructureApplyActHierarchy(h);return h;

}
//@@FN_END:monitorStructureRefreshAuthority

//@@FN_START:monitorStructureRemoveNode
function monitorStructureRemoveNode(key){

  if(monitorStructureSocketDraft.orchestrator?.conversation_key===key)monitorStructureSocketDraft.orchestrator=null;

  if(monitorStructureSocketDraft.aux1?.conversation_key===key)monitorStructureSocketDraft.aux1=null;

  if(monitorStructureSocketDraft.aux2?.conversation_key===key)monitorStructureSocketDraft.aux2=null;

  for(const desktopId of Object.keys(monitorStructureSocketDraft.managers||{}))if(monitorStructureSocketDraft.managers[desktopId]?.conversation_key===key)delete monitorStructureSocketDraft.managers[desktopId];

}
//@@FN_END:monitorStructureRemoveNode

//@@FN_START:monitorStructureRenderResourcePools
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
//@@FN_END:monitorStructureRenderResourcePools

//@@FN_START:monitorStructureRenderSocket
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
//@@FN_END:monitorStructureRenderSocket

//@@FN_START:monitorStructureResetDraft
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
//@@FN_END:monitorStructureResetDraft

//@@FN_START:monitorStructureResourceConnections
function monitorStructureResourceConnections(resourceId){

  return monitorStructureResourceEdges.filter(e=>String(e.resource_id||"")===String(resourceId||"")).map(e=>String(e.supervisor_key||""));

}
//@@FN_END:monitorStructureResourceConnections

//@@FN_START:monitorStructureRestoreExemptForDirectLink
function monitorStructureRestoreExemptForDirectLink(nodeKey){
  nodeKey=String(nodeKey||"");if(!nodeKey)return true;
  const node=monitorStructureAvailableNodes().find(item=>String(item?.conversation_key||"")===nodeKey)||null;
  if(!node||!monitorStructureNodeIsPlacementExempt(node))return true;
  monitorStructurePlacementExemptions[nodeKey]=false;
  return true;
}
//@@FN_END:monitorStructureRestoreExemptForDirectLink

//@@FN_START:monitorStructureRollbackDeskMoves
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
//@@FN_END:monitorStructureRollbackDeskMoves

//@@FN_START:monitorStructureRunAutoLayout
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
//@@FN_END:monitorStructureRunAutoLayout

//@@FN_START:monitorStructureSave
async function monitorStructureSave(){

  const button=document.getElementById("monitorStructureSave"),status=document.getElementById("monitorStructureStatus");if(button?.disabled)return;let movedCount=0,moveResult=null,actSaved=false;

  if(button)button.disabled=true;if(status)status.textContent="실행 중 · 실제 Desk 이동 및 역할 확정…";

  try{moveResult=await monitorStructureExecuteDeskMoves();movedCount=Number(moveResult?.moved||0);const payload=monitorStructureBuildSavePayload();const r=await actFetch(ORCHESTRATOR_LAYOUT_SAVE_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const d=await r.json().catch(()=>null);if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);actSaved=true;monitorStructureApplyActHierarchy(d);monitorStructureFinalizeDeskMoves(moveResult);monitorStructureDirty=false;await monitorStructurePersistBaseline();await monitorStructurePersistWorkingDraft();await chrome.storage.local.remove(MONITOR_STRUCTURE_LEGACY_DRAFT_KEY);monitorStructureHistoryReset();await refreshMonitorRoleAdmin().catch(()=>{});await refreshAiMonitor().catch(()=>{});renderMonitorStructure();if(status)status.textContent=`실행 완료 · Desk ${movedCount}개 이동 · ${payload.assignments.length}개 노드 역할 확정`;}

  catch(error){let rollbackError=null;if(!actSaved&&Number(moveResult?.moved||0)>0){try{await monitorStructureRollbackDeskMoves(moveResult);}catch(e){rollbackError=e;}}if(status)status.textContent=rollbackError?`실행 실패 · Desk 자동 복구도 실패 · ${monitorDiagTextError(error)} / ${monitorDiagTextError(rollbackError)}`:`실행 실패${movedCount&&!actSaved?` · Desk ${movedCount}개 원위치 복구됨`:""} · ${monitorDiagTextError(error)}`;if(rollbackError)throw rollbackError;throw error;}

  finally{if(button)button.disabled=false;}

}
//@@FN_END:monitorStructureSave

//@@FN_START:monitorStructureSavePlacement
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
//@@FN_END:monitorStructureSavePlacement

//@@FN_START:monitorStructureSetNodeExempt
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
//@@FN_END:monitorStructureSetNodeExempt

//@@FN_START:monitorStructureSetParent
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
//@@FN_END:monitorStructureSetParent

//@@FN_START:monitorStructureShowLocalModels
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
//@@FN_END:monitorStructureShowLocalModels

//@@FN_START:monitorStructureSlotAtPoint
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
//@@FN_END:monitorStructureSlotAtPoint

//@@FN_START:monitorStructureSocketCard
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
//@@FN_END:monitorStructureSocketCard

//@@FN_START:monitorStructureSupervisorKeys
function monitorStructureSupervisorKeys(layout){

  return new Set([layout.orchestrator,layout.aux1,layout.aux2,...Object.values(layout.desktops||{}).map(x=>x.manager)].filter(Boolean).map(x=>String(x.conversation_key||"")));

}
//@@FN_END:monitorStructureSupervisorKeys

//@@FN_START:monitorStructureSyncLocalBundleManagerEdges
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
//@@FN_END:monitorStructureSyncLocalBundleManagerEdges

//@@FN_START:monitorStructureToggleNodeControl
async function monitorStructureToggleNodeControl(key){

  key=String(key||"");if(!key)return;

  const enabled=!monitorStructureNodeControlState(key).auto;

  const r=await actFetch(ORCHESTRATOR_NODE_CONTROL_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_key:key,enabled})});

  const d=await r.json().catch(()=>null);if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);

  monitorStructureNodeControls[key]={auto:Boolean(d.auto_wake??d.enabled)};monitorStructurePersistNodeControls();renderMonitorStructure();

}
//@@FN_END:monitorStructureToggleNodeControl

//@@FN_START:monitorStructureToggleResourceEdge
function monitorStructureToggleResourceEdge(supervisorKey,resourceId){

  supervisorKey=String(supervisorKey||"");resourceId=String(resourceId||"");if(!supervisorKey||!resourceId)return;

  const historyBefore=monitorStructureHistorySnapshot();
  const exists=monitorStructureResourceEdges.some(e=>e.supervisor_key===supervisorKey&&e.resource_id===resourceId);

  monitorStructureResourceEdges=exists?monitorStructureResourceEdges.filter(e=>!(e.supervisor_key===supervisorKey&&e.resource_id===resourceId)):[...monitorStructureResourceEdges,{supervisor_key:supervisorKey,resource_id:resourceId,relation:"USES"}];

  monitorStructureDirty=true;
  monitorStructureHistoryCommit(historyBefore);

  renderMonitorStructure(); const status=document.getElementById("monitorStructureStatus"); if(status)status.textContent="DRAFT ? AI ?? ?? ??? ? ?? ?";

}
//@@FN_END:monitorStructureToggleResourceEdge

//@@FN_START:monitorStructureTrackHtmlDragGhost
function monitorStructureTrackHtmlDragGhost(event){
  if(!monitorStructureHtmlDragGhost)return;
  moveMonitorNodeDragGhost(monitorStructureHtmlDragGhost,event.clientX,event.clientY);
}
//@@FN_END:monitorStructureTrackHtmlDragGhost

//@@FN_START:monitorStructureUndoAction
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
//@@FN_END:monitorStructureUndoAction

//@@FN_START:monitorStructureUpdateDragGhost
function monitorStructureUpdateDragGhost(nodeKey,clientX,clientY){if(!monitorStructurePointerGhost){const source=monitorStructurePanel.querySelector(`.monitor-org-node-card[data-node-key="${CSS.escape(nodeKey)}"]`);if(!source)return;monitorStructurePointerGhost=createMonitorNodeDragGhost(source);monitorStructurePointerGhost.classList.add("monitor-org-drag-ghost");}moveMonitorNodeDragGhost(monitorStructurePointerGhost,clientX,clientY);}
//@@FN_END:monitorStructureUpdateDragGhost

//@@FN_START:monitorStructureUpdateHistoryButtons
function monitorStructureUpdateHistoryButtons(){
  const undo=document.getElementById("monitorStructureUndo");
  const redo=document.getElementById("monitorStructureRedo");
  if(undo)undo.disabled=monitorStructureUndoStack.length===0;
  if(redo)redo.disabled=monitorStructureRedoStack.length===0;
}
//@@FN_END:monitorStructureUpdateHistoryButtons

//@@FN_START:monitorStructureUseNodeDragGhost
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
//@@FN_END:monitorStructureUseNodeDragGhost

//@@FN_START:monitorStructureWorkerStrip
function monitorStructureWorkerStrip(nodes){

  const strip=document.createElement("div");strip.className="monitor-org-workers";

  for(const node of nodes){const item=monitorStructureSocketCard(node,true,true);item.classList.add("monitor-org-worker-card");item.draggable=false;item.dataset.nodeKey=String(node.conversation_key||"");item.dataset.orgMoveNode="1";strip.append(item);}return strip;

}
//@@FN_END:monitorStructureWorkerStrip

//@@FN_START:monitorStructureWouldCycle
function monitorStructureWouldCycle(child,parent,parents){let cur=parent;const seen=new Set([child]);while(cur){if(seen.has(cur))return true;seen.add(cur);cur=parents[cur]||"";}return false;}
//@@FN_END:monitorStructureWouldCycle

//@@FN_START:openMonitorStructure
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
//@@FN_END:openMonitorStructure

//@@FN_START:renderMonitorStructure
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
//@@FN_END:renderMonitorStructure

