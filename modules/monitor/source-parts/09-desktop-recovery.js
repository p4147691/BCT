/*@@MONITOR_FUNCTION:monitorStructureEffectiveDesktopId@@*/

/*@@MONITOR_FUNCTION:monitorStructureMoveNodeToDesk@@*/

/*@@MONITOR_FUNCTION:monitorStructureMoveBundleToDesk@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleOrder@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleKinds@@*/

/*@@MONITOR_FUNCTION:monitorStructureEnsureBundleDefaults@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleName@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeIsActive@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleIsActive@@*/

/*@@MONITOR_FUNCTION:monitorStructureShowLocalModels@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleNode@@*/

/*@@MONITOR_FUNCTION:monitorStructureSyncLocalBundleManagerEdges@@*/

/*@@MONITOR_FUNCTION:monitorStructureBundleCard@@*/
/*@@MONITOR_FUNCTION:monitorStructureInstalledBundles@@*/

/*@@MONITOR_FUNCTION:monitorStructureDeskNodeGrid@@*/

/*@@MONITOR_FUNCTION:monitorStructureAutoLayout@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorStructureRemoveNode@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeControlState@@*/

/*@@MONITOR_FUNCTION:monitorStructurePersistNodeControls@@*/

/*@@MONITOR_FUNCTION:monitorStructureToggleNodeControl@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeDisplayName@@*/

/*@@MONITOR_FUNCTION:monitorStructureNodeShortNumber@@*/

/*@@MONITOR_FUNCTION:monitorStructureSocketCard@@*/

/*@@MONITOR_FUNCTION:monitorStructureRenderSocket@@*/
/*@@MONITOR_FUNCTION:monitorStructureWorkerStrip@@*/

/*@@MONITOR_FUNCTION:monitorStructureDeskTransferSlot@@*/

/*@@MONITOR_FUNCTION:monitorStructureDefaultParents@@*/

/*@@MONITOR_FUNCTION:monitorStructureEffectiveParents@@*/

/*@@MONITOR_FUNCTION:monitorStructureAuthorityOverrides@@*/

/*@@MONITOR_FUNCTION:monitorStructurePersistLinks@@*/

/*@@MONITOR_FUNCTION:monitorStructureWouldCycle@@*/

/*@@MONITOR_FUNCTION:monitorStructureSupervisorKeys@@*/

/*@@MONITOR_FUNCTION:monitorStructureResourceConnections@@*/

/*@@MONITOR_FUNCTION:monitorStructureToggleResourceEdge@@*/

/*@@MONITOR_FUNCTION:monitorStructureRenderResourcePools@@*/

/*@@MONITOR_FUNCTION:monitorStructureApplyActHierarchy@@*/

/*@@MONITOR_FUNCTION:monitorStructureRefreshAuthority@@*/

/*@@MONITOR_FUNCTION:monitorStructureBuildSavePayload@@*/

/*@@MONITOR_FUNCTION:monitorStructureCloneDraftValue@@*/

/*@@MONITOR_FUNCTION:monitorStructureHistorySnapshot@@*/

/*@@MONITOR_FUNCTION:monitorStructureHistoryKey@@*/

/*@@MONITOR_FUNCTION:monitorStructureUpdateHistoryButtons@@*/

/*@@MONITOR_FUNCTION:monitorStructureHistoryReset@@*/

/*@@MONITOR_FUNCTION:monitorStructureHistoryCommit@@*/

/*@@MONITOR_FUNCTION:monitorStructureApplyHistorySnapshot@@*/

/*@@MONITOR_FUNCTION:monitorStructureUndoAction@@*/

/*@@MONITOR_FUNCTION:monitorStructureRedoAction@@*/

/*@@MONITOR_FUNCTION:monitorStructureBaselineSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorStructurePersistWorkingDraft@@*/

/*@@MONITOR_FUNCTION:monitorStructureReconcileSnapshot@@*/

/*@@MONITOR_FUNCTION:monitorStructurePersistBaseline@@*/

/*@@MONITOR_FUNCTION:monitorStructureApplyBaseline@@*/

/*@@MONITOR_FUNCTION:monitorStructureRunAutoLayout@@*/

/*@@MONITOR_FUNCTION:monitorStructureDetachAll@@*/

/*@@MONITOR_FUNCTION:monitorStructureSetNodeExempt@@*/

/*@@MONITOR_FUNCTION:monitorStructureDetachBlankStep@@*/

/*@@MONITOR_FUNCTION:monitorStructureResetDraft@@*/

/*@@MONITOR_FUNCTION:monitorStructureExecuteDeskMoves@@*/

/*@@MONITOR_FUNCTION:monitorStructureRollbackDeskMoves@@*/

/*@@MONITOR_FUNCTION:monitorStructureFinalizeDeskMoves@@*/

/*@@MONITOR_FUNCTION:monitorStructureSavePlacement@@*/

/*@@MONITOR_FUNCTION:monitorStructureSave@@*/

/*@@MONITOR_FUNCTION:monitorStructureConnectNodesByPosition@@*/

/*@@MONITOR_FUNCTION:monitorStructureRestoreExemptForDirectLink@@*/

/*@@MONITOR_FUNCTION:monitorStructureSetParent@@*/

/*@@MONITOR_FUNCTION:monitorStructureDrawLinks@@*/

/*@@MONITOR_FUNCTION:monitorStructureDrawLiveLink@@*/

/*@@MONITOR_FUNCTION:monitorStructureFitViewport@@*/

/*@@MONITOR_FUNCTION:monitorStructureAlignLowerDesksToOrchestrator@@*/

/*@@MONITOR_FUNCTION:renderMonitorStructure@@*/
/*@@MONITOR_FUNCTION:monitorStructureDropNode@@*/

/*@@MONITOR_FUNCTION:monitorHierarchyTargetAt@@*/

/*@@MONITOR_FUNCTION:clearMonitorHierarchyTargets@@*/

/*@@MONITOR_FUNCTION:monitorHierarchyApplyDrop@@*/

/*@@MONITOR_FUNCTION:openMonitorStructure@@*/

/*@@MONITOR_FUNCTION:closeMonitorStructure@@*/

/*@@MONITOR_FUNCTION:monitorDiagTextError@@*/

/*@@MONITOR_FUNCTION:refreshMonitorAutoProcess@@*/

/*@@MONITOR_FUNCTION:toggleMonitorAutoProcess@@*/

/*@@MONITOR_FUNCTION:refreshMonitorActDiagnostic@@*/

/*@@MONITOR_FUNCTION:showMonitorDiagText@@*/
/*@@MONITOR_FUNCTION:refreshMonitorCurrentDiagnosticView@@*/

document.getElementById('monitorDiagRefresh').addEventListener('click',()=>refreshMonitorCurrentDiagnosticView().catch(e=>showMonitorDiagText(`관제 새로고침 실패: ${monitorDiagTextError(e)}`)));

monitorDiagToggle?.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();monitorDiagnostics.open=!monitorDiagnostics.open;});
monitorDiagnostics.addEventListener('toggle',()=>{if(monitorDiagToggle){monitorDiagToggle.textContent=monitorDiagnostics.open?'접기':'펼치기';monitorDiagToggle.setAttribute('aria-label',monitorDiagnostics.open?'진단 상세 화면 접기':'진단 상세 화면 펼치기');}if(monitorDiagnostics.open){void refreshMonitorActDiagnostic();void refreshMonitorAutoProcess();}});
for(const button of monitorDiagnostics.querySelectorAll('[data-monitor-diag-view]')){
  button.addEventListener('click',async()=>{
    for(const peer of monitorDiagnostics.querySelectorAll('[data-monitor-diag-view]'))peer.classList.toggle('is-active',peer===button);
    const view=String(button.dataset.monitorDiagView||'overview');
    const label=String(button.textContent||view);
    if(view==='overview'){
      showMonitorDiagText(`종합 관제\n${monitorDiagAct.textContent} · ${monitorAutoProcessQuick.textContent}\n오른쪽 위 새로고침 아이콘은 현재 선택한 관제 정보만 다시 확인합니다.`);
      return;
    }
    if(view==='act'){
      await refreshMonitorActDiagnostic();
      showMonitorDiagText(`ACT 관제\n${monitorDiagAct.textContent}`);
      return;
    }
    if(view==='monitor'){
      showMonitorDiagText(monitorRenderDiagnosticText());
      return;
    }
    showMonitorDiagText(`${label} 관제 · 세부 수집기 연결 전`);
  });
}

monitorStructureQuick.addEventListener("click",()=>{if(monitorStructureOpen)closeMonitorStructure();else void openMonitorStructure();});

document.getElementById("monitorStructureClose").addEventListener("click",closeMonitorStructure);

document.getElementById("monitorStructureSave").addEventListener("click",()=>{void monitorStructureSave().catch(()=>{});});
document.getElementById("monitorStructurePlacementSave").addEventListener("click",()=>{void monitorStructureSavePlacement().catch(()=>{});});
document.getElementById("monitorStructureUndo").addEventListener("click",monitorStructureUndoAction);
document.getElementById("monitorStructureRedo").addEventListener("click",monitorStructureRedoAction);

document.getElementById("monitorStructureAutoLayout").addEventListener("click",monitorStructureRunAutoLayout);

document.getElementById("monitorStructureLinkMode")?.addEventListener("click",()=>{if(!MONITOR_STRUCTURE_CONNECTIONS_ENABLED)return;monitorStructureLinkMode=!monitorStructureLinkMode;monitorStructureLinkSourceKey="";const button=document.getElementById("monitorStructureLinkMode");button?.classList.toggle("is-active",monitorStructureLinkMode);const status=document.getElementById("monitorStructureStatus");if(status)status.textContent=monitorStructureLinkMode?"선 연결 · 상위/하위 노드를 차례로 선택하세요":"선 연결 종료 · 노드 클릭은 AUTO 설정";renderMonitorStructure();});

monitorStructurePanel.addEventListener("click",event=>{

  if(Date.now()<monitorStructureSuppressNodeClickUntil)return;

  const card=event.target?.closest?.(".monitor-org-node-card[data-control-node='1'][data-node-key]");if(!card)return;
  if(monitorStructureLinkMode){const key=String(card.dataset.nodeKey||"");if(!key)return;if(!monitorStructureLinkSourceKey){monitorStructureLinkSourceKey=key;card.classList.add("monitor-org-link-source");const status=document.getElementById("monitorStructureStatus");if(status)status.textContent="선 연결 · 두 번째 노드를 선택하세요";return;}if(key===monitorStructureLinkSourceKey){monitorStructureLinkSourceKey="";card.classList.remove("monitor-org-link-source");return;}const sourceKey=monitorStructureLinkSourceKey;monitorStructureLinkSourceKey="";monitorStructureLinkMode=false;document.getElementById("monitorStructureLinkMode")?.classList.remove("is-active");monitorStructureConnectNodesByPosition(sourceKey,key);return;}

  void monitorStructureToggleNodeControl(String(card.dataset.nodeKey||"")).catch(error=>{const status=document.getElementById("monitorStructureStatus");if(status)status.textContent=`AUTO 변경 실패 · ${monitorDiagTextError(error)}`;});

});

/*@@MONITOR_FUNCTION:monitorStructureClearDragFeedback@@*/

/*@@MONITOR_FUNCTION:monitorStructureUpdateDragGhost@@*/

/*@@MONITOR_FUNCTION:monitorStructurePointerTargetAt@@*/

monitorStructurePanel.addEventListener("pointerdown",event=>{

  if(monitorStructureLinkMode)return;
  const mover=event.target?.closest?.('.monitor-org-node-card[data-org-move-node="1"][data-node-key]');

  if(!mover||event.button!==0)return;

  const key=String(mover.dataset.nodeKey||"");if(!key)return;

  if(!MONITOR_STRUCTURE_CONNECTIONS_ENABLED&&mover.closest?.(".monitor-org-manager-socket")){

    const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());

    const linked=Boolean(parents[key]||Object.values(parents).some(parent=>String(parent||"")===key));

    if(linked){const status=document.getElementById("monitorStructureStatus");if(status)status.textContent="Manager 이동 불가 · 먼저 빈 공간에 놓아 관리선을 끊어주세요";return;}

  }

  monitorStructureNodePointer={nodeKey:key,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,moved:false};

  try{monitorStructurePanel.setPointerCapture(event.pointerId);}catch(_){}

  event.preventDefault();event.stopPropagation();

});

/*@@MONITOR_FUNCTION:monitorStructureSlotAtPoint@@*/

monitorStructurePanel.addEventListener("pointermove",event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  if(!state.moved&&Math.hypot(event.clientX-state.startX,event.clientY-state.startY)>=7)state.moved=true;

  if(!state.moved)return;

  monitorStructureClearDragFeedback(false);monitorStructureUpdateDragGhost(state.nodeKey,event.clientX,event.clientY);monitorStructureRelationDragKey=state.nodeKey;monitorStructureDrawLiveLink(event.clientX,event.clientY);

  const target=monitorStructurePointerTargetAt(event.clientX,event.clientY,state.nodeKey);

  if(target?.kind==="desk")target.element.classList.add("is-desk-drop");else if(target?.kind==="socket")target.element.classList.add("is-socket-drop");else if(target?.kind==="node")target.element.classList.add("monitor-org-link-target");

  event.preventDefault();event.stopPropagation();

});

const monitorStructureFinishNodePointer=event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  const nodeKey=state.nodeKey,moved=state.moved;

  const target=moved?monitorStructurePointerTargetAt(event.clientX,event.clientY,nodeKey):null;

  monitorStructureNodePointer={nodeKey:"",pointerId:null,startX:0,startY:0,moved:false};

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  monitorStructureClearDragFeedback();monitorStructureRelationDragKey="";

  if(!moved)return;

  monitorStructureSuppressNodeClickUntil=Date.now()+500;

  if(target?.kind==="desk"){const desktopId=String(target.element.dataset.desktopId||"");if(desktopId)monitorStructureMoveNodeToDesk(nodeKey,desktopId);}else if(target?.kind==="socket"){const node=monitorStructureAvailableNodes().find(item=>String(item.conversation_key||"")===nodeKey)||null;const slot=String(target.element.dataset.hierarchySlot||""),desktopId=String(target.element.dataset.desktopId||"");if(node&&slot)monitorStructureDropNode(slot,node,desktopId);}else if(target?.kind==="node"){monitorStructureConnectNodesByPosition(nodeKey,String(target.element.dataset.nodeKey||""));}else if(target?.kind==="blank"){monitorStructureDetachBlankStep(nodeKey);}else monitorStructureDrawLinks(monitorStructureAutoLayout());

  event.preventDefault();event.stopPropagation();

};

monitorStructurePanel.addEventListener("pointerup",monitorStructureFinishNodePointer);

monitorStructurePanel.addEventListener("pointercancel",event=>{

  const state=monitorStructureNodePointer;if(!state.nodeKey||state.pointerId!==event.pointerId)return;

  monitorStructureNodePointer={nodeKey:"",pointerId:null,startX:0,startY:0,moved:false};

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  monitorStructureRelationDragKey="";monitorStructureClearDragFeedback();monitorStructureDrawLinks(monitorStructureAutoLayout());

});

monitorStructurePanel.addEventListener("pointerdown",event=>{

  const path=event.target?.closest?.(".monitor-org-link[data-child-key]");if(!path||path.classList.contains("monitor-org-link-live"))return;

  const child=String(path.dataset.childKey||"");if(!child)return;

  monitorStructureEdgePointer={child,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,moved:false};monitorStructureRelationDragKey=child;path.classList.add("is-edge-dragging");

  try{monitorStructurePanel.setPointerCapture(event.pointerId);}catch(_){}event.preventDefault();event.stopPropagation();

});

monitorStructurePanel.addEventListener("pointermove",event=>{

  const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;

  if(!state.moved&&Math.hypot(event.clientX-state.startX,event.clientY-state.startY)>=7)state.moved=true;

  if(state.moved)monitorStructureDrawLiveLink(event.clientX,event.clientY);

});

const monitorStructureFinishEdgePointer=event=>{

  const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;

  const child=state.child,moved=state.moved;monitorStructureEdgePointer={child:"",pointerId:null,startX:0,startY:0,moved:false};monitorStructureRelationDragKey="";

  try{monitorStructurePanel.releasePointerCapture(event.pointerId);}catch(_){}

  for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-link.is-edge-dragging"))el.classList.remove("is-edge-dragging");

  if(!moved){monitorStructureDrawLinks(monitorStructureAutoLayout());return;}

  const target=document.elementsFromPoint(event.clientX,event.clientY).find(el=>el?.closest?.(".monitor-org-node-card[data-node-key]"))?.closest?.(".monitor-org-node-card[data-node-key]")||null;

  const parent=target&&String(target.dataset.nodeKey||"")!==child?String(target.dataset.nodeKey||""):"";

  void monitorStructureSetParent(child,parent);

};

monitorStructurePanel.addEventListener("pointerup",monitorStructureFinishEdgePointer);

monitorStructurePanel.addEventListener("pointercancel",event=>{const state=monitorStructureEdgePointer;if(!state.child||state.pointerId!==event.pointerId)return;monitorStructureEdgePointer={child:"",pointerId:null,startX:0,startY:0,moved:false};monitorStructureRelationDragKey="";monitorStructureDrawLinks(monitorStructureAutoLayout());});

monitorStructurePanel.addEventListener("dragstart",event=>{

  const bundle=event.target?.closest?.(".monitor-org-bundle[data-bundle-kind]");if(bundle){monitorStructureUseNodeDragGhost(event);event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("application/x-dwm-org-bundle",String(bundle.dataset.bundleKind||""));return;}

  const mover=event.target?.closest?.('.monitor-org-node-card[data-org-move-node="1"]');if(mover){monitorStructureUseNodeDragGhost(event);const key=String(mover.dataset.nodeKey||"");const inManager=Boolean(mover.closest?.(".monitor-org-manager-socket"));if(inManager){const parents=monitorStructureEffectiveParents(monitorStructureAutoLayout());const linked=Boolean(parents[key]||Object.values(parents).some(parent=>String(parent||"")===key));if(linked)event.dataTransfer.setData("application/x-dwm-org-manager-linked","1");}event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("application/x-dwm-org-node",key);return;}

  const resource=event.target?.closest?.(".monitor-org-resource-card[data-resource-id]");if(resource){monitorStructureResourceDragId=String(resource.dataset.resourceId||"");resource.classList.add("is-dragging");event.dataTransfer.effectAllowed="link";event.dataTransfer.setData("application/x-dwm-llm-resource",monitorStructureResourceDragId);return;}

  const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");if(!card)return;

  monitorStructureRelationDragKey=String(card.dataset.nodeKey||"");event.dataTransfer.effectAllowed="move";event.dataTransfer.setData("text/plain",monitorStructureRelationDragKey);card.classList.add("monitor-org-link-dragging");

  requestAnimationFrame(()=>monitorStructureDrawLiveLink(event.clientX,event.clientY));

});

monitorStructurePanel.addEventListener("dragover",event=>{

  const types=[...(event.dataTransfer?.types||[])];const carriesNode=types.includes("application/x-dwm-org-node")||types.includes("application/x-dwm-structure-node");const carriesBundle=types.includes("application/x-dwm-org-bundle");const socket=event.target?.closest?.('.monitor-org-socket[data-hierarchy-slot][data-desktop-id]');const emptySocket=socket?.matches?.(':not(:has(.monitor-org-node-card[data-node-key]))')?socket:null;if(socket&&carriesBundle){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);socket.classList.add("is-socket-drop");return;}if(emptySocket&&carriesNode){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);emptySocket.classList.add("is-socket-drop");return;}
  const desk=event.target?.closest?.('.monitor-org-node-slot[data-desktop-id]');const linkedManager=types.includes("application/x-dwm-org-manager-linked");if(desk&&(carriesNode||types.includes("application/x-dwm-org-bundle"))){event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureClearDragFeedback(false);if(!linkedManager)desk.classList.add("is-desk-drop");return;}

  if(monitorStructureResourceDragId){const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");const supervisors=monitorStructureSupervisorKeys(monitorStructureAutoLayout());if(card&&supervisors.has(String(card.dataset.nodeKey||""))){event.preventDefault();event.dataTransfer.dropEffect="link";card.classList.add("monitor-org-link-target");}return;}

  if(!monitorStructureRelationDragKey)return;event.preventDefault();event.dataTransfer.dropEffect="move";monitorStructureDrawLiveLink(event.clientX,event.clientY);

  const card=event.target?.closest?.(".monitor-org-node-card[data-node-key]");

  for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-link-target"))el.classList.remove("monitor-org-link-target");

  if(card&&card.dataset.nodeKey!==monitorStructureRelationDragKey)card.classList.add("monitor-org-link-target");

});

monitorStructurePanel.addEventListener("drop",event=>{

  const socket=event.target?.closest?.('.monitor-org-socket[data-hierarchy-slot][data-desktop-id]');const kind=String(event.dataTransfer?.getData("application/x-dwm-org-bundle")||"");if(socket&&monitorStructureBundleOrder().includes(kind)){event.preventDefault();monitorStructureClearDragFeedback();monitorStructureMoveBundleToDesk(kind,String(socket.dataset.desktopId||""),String(socket.dataset.hierarchySlot||"")==="manager");return;}const emptySocket=socket?.matches?.(':not(:has(.monitor-org-node-card[data-node-key]))')?socket:null;if(emptySocket){const nodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");const raw=String(event.dataTransfer?.getData("application/x-dwm-structure-node")||"");let node=nodeKey?monitorStructureAvailableNodes().find(item=>String(item.conversation_key||"")===nodeKey)||null:null;if(!node&&raw){try{node=JSON.parse(raw);}catch(_){}}if(node?.conversation_key){event.preventDefault();monitorStructureClearDragFeedback();monitorStructureDropNode(String(emptySocket.dataset.hierarchySlot||""),node,String(emptySocket.dataset.desktopId||""));return;}}
  const desk=event.target?.closest?.('.monitor-org-node-slot[data-desktop-id]');if(desk){const desktopId=String(desk.dataset.desktopId||"");const nodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");const linkedManager=String(event.dataTransfer?.getData("application/x-dwm-org-manager-linked")||"")==="1";const kind=String(event.dataTransfer?.getData("application/x-dwm-org-bundle")||"");const raw=String(event.dataTransfer?.getData("application/x-dwm-structure-node")||"");if(nodeKey&&linkedManager){event.preventDefault();const st=document.getElementById("monitorStructureStatus");if(st)st.textContent="Manager 이동 불가 · 먼저 연결을 해제하세요";return;}if(nodeKey){event.preventDefault();monitorStructureMoveNodeToDesk(nodeKey,desktopId);return;}if(kind){event.preventDefault();monitorStructureMoveBundleToDesk(kind,desktopId);return;}if(raw){try{const node=JSON.parse(raw);if(node?.conversation_key){event.preventDefault();monitorStructureMoveNodeToDesk(String(node.conversation_key),desktopId);return;}}catch(_){}}}

  const blankNodeKey=String(event.dataTransfer?.getData("application/x-dwm-org-node")||"");if(blankNodeKey){event.preventDefault();monitorStructureDetachBlankStep(blankNodeKey);return;}

  if(monitorStructureResourceDragId){event.preventDefault();const target=event.target?.closest?.(".monitor-org-node-card[data-node-key]");const supervisors=monitorStructureSupervisorKeys(monitorStructureAutoLayout());if(target&&supervisors.has(String(target.dataset.nodeKey||"")))monitorStructureToggleResourceEdge(String(target.dataset.nodeKey||""),monitorStructureResourceDragId);monitorStructureResourceDragId="";return;}

  if(!monitorStructureRelationDragKey)return;event.preventDefault();

  const child=monitorStructureRelationDragKey,target=event.target?.closest?.(".monitor-org-node-card[data-node-key]");

  if(target&&target.dataset.nodeKey!==child)void monitorStructureSetParent(child,String(target.dataset.nodeKey||""));else monitorStructureDetachBlankStep(child);monitorStructureRelationDragKey="";

});

monitorStructurePanel.addEventListener("dragend",()=>{monitorStructureClearDragFeedback();monitorStructureRelationDragKey="";monitorStructureResourceDragId="";for(const el of monitorStructurePanel.querySelectorAll(".monitor-org-resource-card.is-dragging"))el.classList.remove("is-dragging");monitorStructureDrawLinks(monitorStructureAutoLayout());});

document.getElementById("monitorStructureClear").addEventListener("click",()=>{void monitorStructureResetDraft();});

monitorAutoProcessQuick.addEventListener('click',()=>toggleMonitorAutoProcess().catch(e=>showMonitorDiagText(`자동 처리 변경 실패: ${monitorDiagTextError(e)}`,false)));

document.getElementById('monitorDiagLogCopy').addEventListener('click',async()=>{const text=String(monitorDiagLog.textContent||'');try{await navigator.clipboard.writeText(text);monitorDiagLogCopyState.textContent='복사됨';}catch(_){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.append(ta);ta.select();document.execCommand('copy');ta.remove();monitorDiagLogCopyState.textContent='복사됨';}setTimeout(()=>{monitorDiagLogCopyState.textContent='';},1600);});

refreshMonitorAutoProcess();

/* HIERARCHY_DISABLED_FOR_STABILITY */
