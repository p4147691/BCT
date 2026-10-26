function syncMonitorThumbnailTabBadges(container, className) {

  if (className !== "monitor-desktop-thumb-window") return;
  const projection = globalThis.MonitorBctThumbnailProjection;
  if (!projection?.render) {
    container.dataset.monitorNodeOverlayStatus = "MODULE_MISSING";
    container.dataset.monitorNodeOverlayRendered = "0";
    return;
  }
  const diagnostics = projection.render({
    container,
    state: monitorLastAiState,
    locations: monitorWindowDesktopLocations,
    highlightedHwnd: monitorBctNodeHighlightedHwnd,
    numbersForHwnd: monitorBadgeNodeNumbersForHwnd,
  });
  container.dataset.monitorNodeOverlayStatus = String(diagnostics.status || "UNKNOWN");
  container.dataset.monitorNodeOverlayCandidates = String(Number(diagnostics.candidates) || 0);
  container.dataset.monitorNodeOverlayMatched = String(Number(diagnostics.matched) || 0);
  container.dataset.monitorNodeOverlayRendered = String(Number(diagnostics.rendered) || 0);
  scheduleMonitorThumbnailProjectionReceipt();
  return diagnostics;
}
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
    const node = monitorBctWindowNodesCache.find((item) =>
      String(item?.conversationKey || "") === String(row.dataset.conversationKey || "")
    );
    if (position) {
      position.textContent = monitorBctNodeLocationText(node, index);
      position.title = Array.isArray(node?.roleTags) && node.roleTags.length
        ? `${index >= 0 ? `D${index + 1}` : "위치 확인 중"} · ${node.roleTags.join(" · ")}`
        : position.textContent;
    }
    row.dataset.desktopNumber = index >= 0 ? String(index + 1) : "";
  }
}
let monitorThumbnailProjectionPublishSignature="";
let monitorThumbnailProjectionPublishTimer=0;
function monitorThumbnailProjectionRuntimeDiagnostics() {
  if(!monitorDesktopThumbs)return [];
  return [...monitorDesktopThumbs.children].map((button)=>{
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    return {
      desktop_id:String(button.dataset.desktopId||visual?.dataset?.desktopId||""),
      status:String(visual?.dataset?.monitorNodeOverlayStatus||"NOT_RENDERED"),
      candidates:Number(visual?.dataset?.monitorNodeOverlayCandidates)||0,
      matched:Number(visual?.dataset?.monitorNodeOverlayMatched)||0,
      rendered:Number(visual?.dataset?.monitorNodeOverlayRendered)||0,
    };
  });
}
function scheduleMonitorThumbnailProjectionReceipt() {
  const diagnostics=monitorThumbnailProjectionRuntimeDiagnostics();
  const signature=JSON.stringify(diagnostics);
  if(signature===monitorThumbnailProjectionPublishSignature)return;
  monitorThumbnailProjectionPublishSignature=signature;
  if(monitorThumbnailProjectionPublishTimer)clearTimeout(monitorThumbnailProjectionPublishTimer);
  monitorThumbnailProjectionPublishTimer=setTimeout(()=>{
    monitorThumbnailProjectionPublishTimer=0;
    void monitorPublishSharedInstance("thumbnail-projection");
  },500);
}
function syncMonitorAllDesktopThumbnailNodeBadges() {
  for (const button of monitorDesktopThumbs.children) {
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    if (visual?.isConnected) syncMonitorThumbnailTabBadges(visual,"monitor-desktop-thumb-window");
  }
  syncMonitorBctNodeLocationLabels();
  syncMonitorMinimizedNodeBadges(monitorLastAiState);
  syncMonitorBctNodeTargetHighlight();
  scheduleMonitorThumbnailProjectionReceipt();
}

let monitorWindowPointerDrag = null;

let monitorDesktopPointerDrag = null;

let monitorCreateDesktopDropBusy = false;

let monitorCreateDesktopDropConsumedUntil = 0;

async function syncMonitorNativeZOrder(desktopId) {

  const id = String(desktopId || "").trim();

  if (!id) return false;

  const result = await monitorNative({ type: "getDesktopWindows", desktopId: id }).catch(() => null);

  if (!result?.ok || !Array.isArray(result.windows)) return false;

  const zByHwnd = new Map(result.windows.map((item) => {

    const nativeZ = Math.max(0, Number(item?.z) || 0);

    return [String(item?.hwnd || ""), String(10000 - Math.min(nativeZ, 9999))];

  }));

  for (const img of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const nativeZIndex = zByHwnd.get(String(img.dataset.hwnd || ""));

    if (!nativeZIndex) continue;

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");
    syncMonitorStatusLayer(img, img.dataset.hwnd || "");
    syncMonitorPauseOverlay(img, img.dataset.hwnd || "");
    syncMonitorDesktopNumberBadge(img, img.dataset.hwnd || "");
    syncMonitorNonChatCountdown(img, img.dataset.hwnd || "");

  }

  return true;

}

function applyMonitorForegroundFocus(hwnd) {

  const next = String(hwnd || "");

  if (!next) return;

  // A real Chrome click is the same selection gesture as clicking that window in Monitor.

  applyMonitorWindowHighlight(next, monitorSelectedHwnds.has(next) ? { toggle: true } : {});

}

function monitorViewportScreenOrigin() {

  const borderX = Math.max(0, (Number(window.outerWidth) - Number(window.innerWidth)) / 2);

  const chromeY = Math.max(0, Number(window.outerHeight) - Number(window.innerHeight) - borderX);

  return { x: Number(window.screenX) + borderX, y: Number(window.screenY) + chromeY };

}

function monitorSelectedEntries(primaryHwnd, sourceDesktopId) {

  const primary = String(primaryHwnd || "");

  const selected = monitorSelectedHwnds.has(primary) ? [...monitorSelectedHwnds] : [primary];

  return selected.map((hwnd) => {

    const location = monitorWindowDesktopLocations.get(String(hwnd));

    return { hwnd: String(hwnd), sourceDesktopId: String(location?.desktopId || sourceDesktopId || "") };

  }).filter((item) => /^\d+$/.test(item.hwnd) && item.hwnd !== "0" && item.sourceDesktopId === sourceDesktopId);

}

function monitorProfileIdForHwnd(hwnd) {

  const location = monitorWindowDesktopLocations.get(String(hwnd));

  const key = String(location?.conversationKey || "").trim();

  const endpoint = (Array.isArray(monitorLastAiState?.endpoints) ? monitorLastAiState.endpoints : []).find((item) => String(item?.conversation_key || "").trim() === key);

  const profile = String(endpoint?.profile_id || "").trim().toUpperCase();

  return ["GOOGLE", "NAVER"].includes(profile) ? profile : "";

}

async function moveMonitorWindowSet(entries, targetDesktopId, undoKind = "window-move", undoExtra = {}) {

  const uniqueEntries = [...new Map((Array.isArray(entries) ? entries : []).filter((entry)=>entry?.hwnd).map((entry)=>[String(entry.hwnd), entry])).values()];

  const eligible = uniqueEntries.filter((entry)=>entry.sourceDesktopId && entry.sourceDesktopId !== targetDesktopId);

  const moved = [];

  for (const entry of eligible) {

    const result = await monitorNative({ type: "moveWindowToDesktop", hwnd: entry.hwnd, desktopId: targetDesktopId }).catch(() => null);

    if (result?.ok) moved.push({ hwnd: entry.hwnd, desktopId: entry.sourceDesktopId });

  }

  if (moved.length) {

    showDesktopUndo({ kind: undoKind, entries: moved, targetDesktopId, ...undoExtra });

    invalidateMonitorDesktopFrames(...eligible.map((x) => x.sourceDesktopId), targetDesktopId);

    setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(...eligible.map((x) => x.sourceDesktopId), targetDesktopId); }, 120);

    setTimeout(() => { void refreshAiMonitor(); }, 260);

  }

  return moved.length === eligible.length;

}

async function snapshotAllChromeHwnds() {

  const snap = await monitorNative({ type: "getAllChromeWindowHandles" }).catch(() => null);

  return new Set((Array.isArray(snap?.hwnds) ? snap.hwnds : []).map(String).filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0"));

}

async function waitForNewChromeHwnd(before, timeoutMs = 7000) {

  const started = Date.now();

  while (Date.now() - started < timeoutMs) {

    await new Promise((resolve) => setTimeout(resolve, 120));

    const now = await snapshotAllChromeHwnds();

    for (const hwnd of now) if (/^\d+$/.test(hwnd) && hwnd !== "0" && !before.has(hwnd)) return hwnd;

  }

  return "";

}

async function cloneMonitorWindowSet(entries, targetDesktopId, undoKind = "window-copy", undoExtra = {}) {

  const createdHwnds = []; const failed = [];

  for (const entry of entries) {

    const profileId = monitorProfileIdForHwnd(entry.hwnd);

    if (!profileId) { failed.push(entry.hwnd); continue; }

    const before = await snapshotAllChromeHwnds();

    const foreground = await monitorNative({ type: "getForegroundWindow" }).catch(() => null);

    const launch = await monitorNative({ type: "launchChatGptWindowCopy", sourceHwnd: entry.hwnd, profileId }).catch(() => null);

    if (!launch?.ok) { failed.push(entry.hwnd); continue; }

    const hwnd = await waitForNewChromeHwnd(before);

    if (!hwnd) { failed.push(entry.hwnd); continue; }

    const moved = await monitorNative({ type: "moveWindowToDesktop", hwnd, desktopId: targetDesktopId }).catch(() => null);

    if (!moved?.ok) { failed.push(entry.hwnd); await monitorNative({ type: "closeWindow", hwnd }).catch(() => null); continue; }

    await monitorNative({ type: "setWindowBoundsNoActivate", hwnd, left: launch.left, top: launch.top, width: launch.width, height: launch.height }).catch(() => null);

    if (foreground?.hwnd) await monitorNative({ type: "restoreForegroundWindow", hwnd: String(foreground.hwnd) }).catch(() => null);

    createdHwnds.push(hwnd);

  }

  if (createdHwnds.length) {

    showDesktopUndo({ kind: undoKind, hwnds: createdHwnds, targetDesktopId, ...undoExtra });

    invalidateMonitorDesktopFrames(targetDesktopId);

    setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(targetDesktopId); }, 180);

  }

  if (failed.length) setMonitorStatus(`Window copy partial failure - ok ${createdHwnds.length} / fail ${failed.length}`, false);

  return failed.length === 0 && createdHwnds.length > 0;

}

async function performMonitorWindowDrop(entries, targetDesktopId, copyMode) {

  return copyMode ? cloneMonitorWindowSet(entries, targetDesktopId) : moveMonitorWindowSet(entries, targetDesktopId);

}

function createMonitorNodeDragGhost(img, event) {

  const rect = img.getBoundingClientRect();

  const ghost = document.createElement("div");

  ghost.className = "monitor-node-drag-ghost";

  ghost.style.width = `${Math.max(28, rect.width)}px`;

  ghost.style.height = `${Math.max(20, rect.height)}px`;

  ghost.style.left = "0px"; ghost.style.top = "0px";

  document.body.append(ghost);

  return ghost;

}

function moveMonitorNodeDragGhost(ghost, clientX, clientY) {

  if (!ghost) return;

  ghost.style.transform = `translate3d(${clientX}px, ${clientY}px, 0) translate(-50%, -50%)`;

}

function destroyMonitorNodeDragGhost(ghost) { ghost?.remove(); }

function monitorTrashDropTargetAt(clientX, clientY) {

  if (monitorNodeTrash.hidden) return null;

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.("#monitorNodeTrash") || null;

}

function clearMonitorTrashDropTarget() { monitorNodeTrash?.classList.remove("monitor-node-trash-drop-target","monitor-node-trash-drop-success"); }

function monitorConversationKeysForHwnd(hwnd,state=monitorLastAiState) {

  const target=String(hwnd||""); if(!target||!state)return [];

  return monitorWorkersForState(state).filter((worker)=>String(endpointOsWindowHandle(endpointForMonitorWorker(worker,state))||"")===target).map((worker)=>String(worker?.conversation_key||"").trim()).filter(Boolean);

}

function monitorTrashRecordForKey(key,sourceKind="list"){

  key=String(key||"").trim(); if(!key)return null;

  const state=monitorLastAiState, ghost=monitorGhostCache.get(key)||{};

  const worker=state?monitorWorkersForState(state).find((x)=>String(x?.conversation_key||"").trim()===key):null;

  const endpoint=worker&&state?endpointForMonitorWorker(worker,state):(Array.isArray(state?.endpoints)?state.endpoints.find((x)=>String(x?.conversation_key||"").trim()===key):null);

  const em=endpoint?.metadata||{}; const desktop=Number(ghost?.desktop||em.desktop_id||em.desktop_index||0), slot=Number(ghost?.slot||em.slot_index||0);
  const bctNode=(Array.isArray(monitorBctWindowNodesCache)?monitorBctWindowNodesCache:[]).find((item)=>String(item?.conversationKey||"")===key)||{};

  return {...ghost,conversation_key:key,profile_id:String(ghost?.profile_id||worker?.profile_id||endpoint?.profile_id||"").toUpperCase(),title:String(ghost?.title||endpoint?.title||bctNode?.title||""),meaningful_title:String(ghost?.meaningful_title||worker?.task_title||endpoint?.title||bctNode?.title||""),node_label:String(bctNode?.nodeLabel||ghost?.node_label||""),network_id:String(bctNode?.scopeId||ghost?.network_id||""),network_name:String(bctNode?.scopeName||ghost?.network_name||""),role_tags:Array.isArray(bctNode?.roleTags)?[...bctNode.roleTags]:(Array.isArray(ghost?.role_tags)?ghost.role_tags:[]),desktop:Number.isInteger(desktop)&&desktop>0?desktop:null,slot:Number.isInteger(slot)&&slot>0?slot:null,first_seen_ms:Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0),closed_at_ms:Number(ghost?.closed_at_ms||monitorGhostTime(endpoint?.closed_at)||0),trash_source:sourceKind==="thumbnail"?"thumbnail":"list",trashed_at_ms:Date.now()};

}

function persistMonitorTrashedNodes(){

  const records=[...monitorTrashRecords.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX);

  chrome.storage.local.set({[MONITOR_TRASHED_NODES_KEY]:[...monitorTrashedConversationKeys],[MONITOR_TRASH_RECORDS_KEY]:records});

}

function updateMonitorNodeTrashUndoUi(){

  clearTimeout(monitorNodeTrashUndoTimer); const now=Date.now(); monitorNodeTrash.hidden=false;

  if(!monitorNodeTrashUndoSnapshot||now>=monitorNodeTrashUndoExpiresAt){monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;monitorNodeTrashUndo.hidden=true;return;}

  monitorNodeTrashUndo.hidden=false; const seconds=Math.max(0,Math.ceil((monitorNodeTrashUndoExpiresAt-now)/1000)); monitorNodeTrashUndoCountdown.textContent=`${seconds}s`;

  monitorNodeTrashUndoTimer=setTimeout(updateMonitorNodeTrashUndoUi,250);

}

async function trashMonitorConversationKeys(keys,sourceKind="list"){

  const unique=[...new Set((keys||[]).map(String).filter(Boolean))].filter((key)=>!monitorTrashedConversationKeys.has(key)); if(!unique.length)return false;

  const endpoints=Array.isArray(monitorLastAiState?.endpoints)?monitorLastAiState.endpoints:[];

  const pending=[];

  for(const key of unique){

    const record=monitorTrashRecordForKey(key,sourceKind);

    const open=endpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key&&String(ep?.presence_state||"").toUpperCase()==="OPEN");

    const tabId=Number(open?.tab_id??open?.metadata?.tab_id);

    pending.push({key,record,open,tabId});

  }

  const failed=[];

  for(const item of pending){

    if(item.open&&Number.isInteger(item.tabId)&&item.tabId>=0){

      try{

        const ep=item.open;

        const body={conversation_key:item.key,tab_id:item.tabId,transport_instance_id:String(ep?.transport_instance_id||""),session_id:String(ep?.session_id||""),profile_id:String(ep?.profile_id||"")};

        const r=await actFetch(ORCHESTRATOR_CONVERSATION_CLOSE_TAB_URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});

        const data=await r.json().catch(()=>({}));

        if(!r.ok||!data?.ok||!data?.verified||!data?.closed){failed.push(item.key);continue;}

      }catch(_){failed.push(item.key);continue;}

    }

    if(item.record)monitorTrashRecords.set(item.key,item.record);

    monitorTrashedConversationKeys.add(item.key);monitorHiddenGhosts.delete(item.key);

  }

  if(failed.length){setMonitorStatus(`연결 탭 ${failed.length}개 닫기 실패 · 해당 노드는 유지됨`,false);}

  const succeeded=pending.filter((item)=>!failed.includes(item.key)).map((item)=>item.key);

  if(succeeded.length){persistMonitorTrashedNodes();monitorNodeTrashUndoSnapshot={keys:succeeded};monitorNodeTrashUndoExpiresAt=Date.now()+MONITOR_NODE_TRASH_UNDO_MS;updateMonitorNodeTrashUndoUi();if(monitorLastAiState)renderWorkers(monitorLastAiState);}

  if(succeeded.length&&!failed.length)setMonitorStatus(`노드 ${succeeded.length}개 삭제 · 연결 탭 닫힘 확인`,true);

  return succeeded.length>0;

}

function refreshMonitorRecoveryMenu(){

  if(!(monitorClosedConversationPickerOpen&&monitorClosedRecoveryMenu&&monitorLastAiState))return;

  const panes=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane-scroll')].map((el)=>({cls:el.parentElement?.className||'',top:el.scrollTop}));

  monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));

  for(const saved of panes){const pane=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane')].find((el)=>(el.className||'')===saved.cls);const scroll=pane?.querySelector('.monitor-trash-pane-scroll');if(scroll)scroll.scrollTop=saved.top;}

}

function restoreMonitorTrashRecord(key){key=String(key||"");monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}

function deleteMonitorTrashRecord(key){key=String(key||"");monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}

function deleteMonitorRecoveryRecord(key){

  key=String(key||""); if(!key)return; monitorTrashRecords.delete(key); monitorTrashedConversationKeys.add(key); monitorGhostCache.delete(key); monitorHiddenGhosts.delete(key);

  const items=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>String(x?.conversation_key||"").trim()!==key); monitorRebootSnapshot={...monitorRebootSnapshot,items};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

function monitorDeletedDesktopLoadImage(src){

  return new Promise((resolve)=>{

    const value=String(src||"");

    if(!value){resolve(null);return;}

    const image=new Image();

    image.onload=()=>resolve(image);

    image.onerror=()=>resolve(null);

    image.src=value;

  });

}

function monitorDeletedDesktopDrawCover(ctx,image,width,height){

  if(!ctx||!image||!image.naturalWidth||!image.naturalHeight)return;

  const scale=Math.max(width/image.naturalWidth,height/image.naturalHeight);

  const drawWidth=image.naturalWidth*scale,drawHeight=image.naturalHeight*scale;

  ctx.drawImage(image,(width-drawWidth)/2,(height-drawHeight)/2,drawWidth,drawHeight);

}

async function monitorFreezeDesktopThumbnail(desktopId,wallpaperDataUri=""){

  if(!desktopId)return "";

  try{

    const width=320,height=180;

    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;

    const ctx=canvas.getContext("2d",{alpha:false});if(!ctx)return "";

    ctx.fillStyle="#121821";ctx.fillRect(0,0,width,height);

    const wallpaper=String(wallpaperDataUri||await getObservedWallpaper(desktopId,false).catch(()=>""));

    const wallpaperImage=await monitorDeletedDesktopLoadImage(wallpaper);

    if(wallpaperImage)monitorDeletedDesktopDrawCover(ctx,wallpaperImage,width,height);

    const tile=[...monitorDesktopThumbs.children].find((button)=>String(button.dataset.desktopId||"")===String(desktopId));

    const visual=tile?.querySelector(".monitor-desktop-thumb-visual");

    if(visual&&visual.dataset.monitorFrameReady!=="1")await refreshDesktopThumb(visual,desktopId).catch(()=>false);

    let painted=0;

    if(visual){

      const images=[...visual.querySelectorAll(".monitor-desktop-thumb-window")].filter((node)=>String(node.src||"")).sort((a,b)=>Number(a.style.zIndex||a.dataset.nativeZIndex||0)-Number(b.style.zIndex||b.dataset.nativeZIndex||0));

      for(const node of images){

        const image=await monitorDeletedDesktopLoadImage(node.src);

        if(!image)continue;

        const left=(parseFloat(node.style.left)||0)*width/100,top=(parseFloat(node.style.top)||0)*height/100;

        const w=(parseFloat(node.style.width)||0)*width/100,h=(parseFloat(node.style.height)||0)*height/100;

        if(w<=0||h<=0)continue;

        ctx.drawImage(image,left,top,w,h);painted+=1;

      }

    }

    if(!painted){

      const frame=await captureDesktopFrame(desktopId,"thumb").catch(()=>null);

      if(frame?.meta){

        const vw=Math.max(1,Number(frame.meta.previewVirtualWidth??frame.meta.virtualWidth)||1),vh=Math.max(1,Number(frame.meta.previewVirtualHeight??frame.meta.virtualHeight)||1);

        const vl=Number(frame.meta.previewVirtualLeft??frame.meta.virtualLeft??0),vt=Number(frame.meta.previewVirtualTop??frame.meta.virtualTop??0);

        for(const entry of Array.isArray(frame.frames)?frame.frames:[]){

          const image=await monitorDeletedDesktopLoadImage(entry?.dataUri),item=entry?.item||{};

          if(!image)continue;

          const left=((Number(item.left)-vl)/vw)*width,top=((Number(item.top)-vt)/vh)*height,w=(Number(item.width)/vw)*width,h=(Number(item.height)/vh)*height;

          if(![left,top,w,h].every(Number.isFinite)||w<=0||h<=0)continue;

          ctx.drawImage(image,left,top,w,h);painted+=1;

        }

      }

    }

    try{return canvas.toDataURL("image/webp",0.66)||canvas.toDataURL("image/png");}

    catch(_){return canvas.toDataURL("image/png");}

  }catch(_){return "";}

}

function persistMonitorTrashedDesktops(){chrome.storage.local.set({[MONITOR_TRASHED_DESKTOPS_KEY]:[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,30)});}

function monitorDesktopNodeSnapshots(desktopId,index,state=monitorLastAiState){const targetDesktop=Number(index)+1,out=[];for(const worker of monitorWorkersForState(state||{})){const key=String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim();if(!key)continue;const loc=monitorCanonicalPhysicalLocation(worker,state||{}),actNode=monitorActBrowserNode(worker,state||{}),sameId=desktopId&&String(actNode?.desktop_id||"").trim()===String(desktopId);if(!(sameId||Number(loc?.desktop)===targetDesktop))continue;out.push({conversation_key:key,profile_id:String(worker?.profile_id||worker?.__endpoint?.profile_id||"").toUpperCase(),title:String(worker?.task_title||worker?.title||worker?.__endpoint?.title||""),node_label:String(actNode?.node_label||loc?.label||""),slot:Number(loc?.slot||0)||null,hwnd:String(loc?.hwnd||actNode?.hwnd||"")});}return out;}

function restoreMonitorDesktopNodeSnapshots(nodes){for(const item of Array.isArray(nodes)?nodes:[]){const key=String(item?.conversation_key||"");if(!key)continue;monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);monitorHiddenGhosts.delete(key);}persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);}

function storeMonitorTrashedDesktop(snapshot){const id=String(snapshot?.desktopId||`desktop-${Date.now()}`);monitorTrashedDesktops.set(id,{...snapshot,id,trashed_at_ms:Date.now()});persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}

function deleteMonitorTrashedDesktop(id){monitorTrashedDesktops.delete(String(id||""));persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}

async function restoreMonitorTrashedDesktop(id,button){const item=monitorTrashedDesktops.get(String(id||""));if(!item)return;if(button)button.disabled=true;try{const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:item.hwnds||[],wallpaperPath:item.wallpaperPath||""});if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");restoreMonitorDesktopNodeSnapshots(item.nodes);deleteMonitorTrashedDesktop(id);renderVirtualDesktops(result);}catch(error){setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false);if(button)button.disabled=false;}}

function clearMonitorThumbnailRecovery(){

  monitorTrashedDesktops.clear(); persistMonitorTrashedDesktops();

  for(const [key,item] of [...monitorTrashRecords]) if(String(item?.trash_source||"list")==="thumbnail"){monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(String(key));}

  persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

function clearMonitorConversationRecovery(){

  const recovery=monitorClosedConversationRecoveryItems(monitorLastAiState);

  for(const item of recovery){const key=String(item?.conversation_key||"").trim();if(key){monitorTrashedConversationKeys.add(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);}}

  for(const [key,item] of [...monitorTrashRecords]) if(String(item?.trash_source||"list")!=="thumbnail"){monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(String(key));}

  monitorRebootSnapshot={...monitorRebootSnapshot,items:[]};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}

monitorNodeTrashUndoButton.addEventListener("click",()=>{const snap=monitorNodeTrashUndoSnapshot;if(!snap||Date.now()>=monitorNodeTrashUndoExpiresAt)return;for(const key of snap.keys||[]){monitorTrashedConversationKeys.delete(String(key));monitorTrashRecords.delete(String(key));}persistMonitorTrashedNodes();monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;updateMonitorNodeTrashUndoUi();if(monitorLastAiState)renderWorkers(monitorLastAiState);});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_TRASHED_NODES_KEY,MONITOR_TRASH_RECORDS_KEY,MONITOR_TRASHED_NOTES_KEY,MONITOR_TRASHED_DESKTOPS_KEY],(data)=>{for(const key of Array.isArray(data?.[MONITOR_TRASHED_NODES_KEY])?data[MONITOR_TRASHED_NODES_KEY]:[])monitorTrashedConversationKeys.add(String(key));for(const item of Array.isArray(data?.[MONITOR_TRASH_RECORDS_KEY])?data[MONITOR_TRASH_RECORDS_KEY]:[])if(item?.conversation_key)monitorTrashRecords.set(String(item.conversation_key),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_NOTES_KEY])?data[MONITOR_TRASHED_NOTES_KEY]:[])if(item?.id)monitorTrashedNotes.set(String(item.id),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_DESKTOPS_KEY])?data[MONITOR_TRASHED_DESKTOPS_KEY]:[])if(item?.id)monitorTrashedDesktops.set(String(item.id),item);if(monitorLastAiState)renderWorkers(monitorLastAiState);});

function monitorDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.(".monitor-desktop-thumb") || null;

}

function monitorCreateDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.("#monitorCreateDesktop") === monitorCreateDesktop ? monitorCreateDesktop : null;

}

function clearMonitorDesktopDropTargets() {

  for (const button of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb")) button.classList.remove("monitor-desktop-drop-target");

  monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-target");

}

let monitorWorkerRowPointerDrag = null;

let monitorWorkerRowSuppressClickUntil = 0;

function monitorWorkerRowOrderTargetAt(clientX, clientY) {

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.(".monitor-worker-row[data-conversation-key][data-desktop-id]") || null;

}

function clearMonitorWorkerOrderTargets() {

  for(const row of monitorWorkers.querySelectorAll(".monitor-worker-row.monitor-worker-order-target-before,.monitor-worker-row.monitor-worker-order-target-after")) row.classList.remove("monitor-worker-order-target-before","monitor-worker-order-target-after");

}

function beginMonitorWorkerRowPointerDrag(event) {

  if(monitorRoleAssignMode) return;

  if(event.button!==0 || event.target?.closest?.("button,input,textarea,select,a,.monitor-work-state")) return;

  const row=event.currentTarget, hwnd=String(row?.dataset?.hwnd||""), key=String(row?.dataset?.conversationKey||""), sourceDesktopId=String(row?.dataset?.desktopId||"");

  let keys=[key]; try{const parsed=JSON.parse(String(row?.dataset?.conversationKeys||"[]"));if(Array.isArray(parsed)&&parsed.length)keys=[...new Set(parsed.map(String).filter(Boolean))];}catch(_){}

  if(!/^\d+$/.test(hwnd)||hwnd==="0"||!key||!sourceDesktopId) return;

  const currentOrder=[...monitorWorkers.querySelectorAll(`.monitor-worker-row[data-desktop-id="${CSS.escape(sourceDesktopId)}"][data-conversation-key]`)].map(x=>String(x.dataset.conversationKey||"")).filter(Boolean);

  if(currentOrder.length) monitorSetWorkerOrder(sourceDesktopId,currentOrder);

  monitorWorkerRowPointerDrag={pointerId:event.pointerId,row,hwnd,key,keys,sourceDesktopId,entries:[{hwnd,sourceDesktopId}],ghost:null,startX:event.clientX,startY:event.clientY,moved:false};

}

function updateMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||event.pointerId!==drag.pointerId)return;

  if(!drag.moved&&Math.hypot(event.clientX-drag.startX,event.clientY-drag.startY)>=10){

    drag.moved=true;

    drag.ghost=createMonitorNodeDragGhost(drag.row,event); drag.ghost.classList.add("monitor-worker-row-drag-ghost"); moveMonitorNodeDragGhost(drag.ghost,event.clientX,event.clientY);

    drag.row.classList.add("monitor-worker-row-dragging");

    try{drag.row.setPointerCapture(event.pointerId);}catch(_){}

  }

  if(!drag.moved)return;

  event.preventDefault(); moveMonitorNodeDragGhost(drag.ghost,event.clientX,event.clientY); clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

  if(monitorTrashDropTargetAt(event.clientX,event.clientY)){monitorNodeTrash.classList.add("monitor-node-trash-drop-target");return;}

  if(monitorCreateDesktopDropTargetAt(event.clientX,event.clientY)){monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");return;}

  const desktopTarget=monitorDesktopDropTargetAt(event.clientX,event.clientY);

  if(desktopTarget?.dataset?.desktopId&&desktopTarget.dataset.desktopId!==drag.sourceDesktopId){desktopTarget.classList.add("monitor-desktop-drop-target");return;}

  const rowTarget=monitorWorkerRowOrderTargetAt(event.clientX,event.clientY);

  if(rowTarget&&rowTarget!==drag.row&&String(rowTarget.dataset.desktopId||"")===drag.sourceDesktopId){

    const rect=rowTarget.getBoundingClientRect(), after=event.clientY>rect.top+rect.height/2;

    rowTarget.classList.add(after?"monitor-worker-order-target-after":"monitor-worker-order-target-before");

  }

}

async function finishMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||event.pointerId!==drag.pointerId)return;

  monitorWorkerRowPointerDrag=null; drag.row?.classList.remove("monitor-worker-row-dragging"); destroyMonitorNodeDragGhost(drag.ghost);

  try{drag.row?.releasePointerCapture(event.pointerId);}catch(_){}

  if(!drag.moved){clearMonitorDesktopDropTargets();clearMonitorWorkerOrderTargets();return;}

  monitorWorkerRowSuppressClickUntil=Date.now()+650;

  const trashTarget=monitorTrashDropTargetAt(event.clientX,event.clientY);

  const createTarget=trashTarget?null:monitorCreateDesktopDropTargetAt(event.clientX,event.clientY);

  const desktopTarget=createTarget?null:monitorDesktopDropTargetAt(event.clientX,event.clientY);

  const rowTarget=(!createTarget&&!desktopTarget)?monitorWorkerRowOrderTargetAt(event.clientX,event.clientY):null;

  const rect=rowTarget?.getBoundingClientRect?.(), after=Boolean(rowTarget&&event.clientY>rect.top+rect.height/2);

  clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

  if(trashTarget){if(await trashMonitorConversationKeys(drag.keys||[drag.key],"list")){monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);}return;}

  if(createTarget){

    monitorCreateDesktopDropConsumedUntil=Date.now()+700; monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

    try{const created=await createDesktopForDrop(drag.sourceDesktopId,[drag.hwnd],false);if(created?.ok)monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");}

    catch(error){setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message||error}`,false);}

    finally{setTimeout(()=>monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending","monitor-create-desktop-drop-success"),650);}

    return;

  }

  const targetDesktopId=String(desktopTarget?.dataset?.desktopId||"");

  if(targetDesktopId&&targetDesktopId!==drag.sourceDesktopId){

    desktopTarget.classList.add("monitor-desktop-drop-pending");

    try{if(await performMonitorWindowDrop(drag.entries,targetDesktopId,false)){monitorMoveWorkerOrderKey(drag.key,drag.sourceDesktopId,targetDesktopId);desktopTarget.classList.add("monitor-desktop-drop-success");}}

    finally{setTimeout(()=>desktopTarget.classList.remove("monitor-desktop-drop-pending","monitor-desktop-drop-success"),650);}

    return;

  }

  if(rowTarget&&rowTarget!==drag.row&&String(rowTarget.dataset.desktopId||"")===drag.sourceDesktopId){

    const targetKey=String(rowTarget.dataset.conversationKey||"");

    if(monitorReorderWorkerKey(drag.sourceDesktopId,drag.key,targetKey,after)&&monitorLastAiState)renderWorkers(monitorLastAiState);

  }

}

function cancelMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||(event?.pointerId!=null&&event.pointerId!==drag.pointerId))return;

  monitorWorkerRowPointerDrag=null; drag.row?.classList.remove("monitor-worker-row-dragging"); destroyMonitorNodeDragGhost(drag.ghost); clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

}

function beginMonitorWindowPointerDrag(event) {

  if (event.button !== 0) return;

  const img = event.currentTarget;

  const hwnd = String(img?.dataset?.hwnd || "");

  if (!/^\d+$/.test(hwnd) || hwnd === "0") return;

  // Clicking the window surface inside Monitor counts as reading the same alert as clicking the real Chrome window.

  monitorAcknowledgePostWorkForHwnd(hwnd);

  const sourceDesktopId = img.closest(".monitor-desktop-thumb")?.dataset.desktopId || img.parentElement?.dataset?.desktopId || "";

  const initiallySelected = monitorSelectedHwnds.has(hwnd);

  if (event.ctrlKey) applyMonitorWindowHighlight(hwnd, { toggle: true }); else if (!initiallySelected) applyMonitorWindowHighlight(hwnd);

  if (!monitorSelectedHwnds.has(hwnd)) return;

  const entries = monitorSelectedEntries(hwnd, sourceDesktopId);

  const ghost = createMonitorNodeDragGhost(img, event);

  moveMonitorNodeDragGhost(ghost, event.clientX, event.clientY);

  monitorWindowPointerDrag = { pointerId: event.pointerId, hwnd, sourceDesktopId, entries, img, ghost, startX: event.clientX, startY: event.clientY, moved: false, copyMode: Boolean(event.shiftKey), initiallySelected, ctrlSelectionHandled: Boolean(event.ctrlKey) };

  img.classList.add("monitor-window-dragging");

  try { img.setPointerCapture(event.pointerId); } catch (_) {}

  event.preventDefault();

}

function updateMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= 5) drag.moved = true;

  moveMonitorNodeDragGhost(drag.ghost, event.clientX, event.clientY);

  clearMonitorDesktopDropTargets();

  clearMonitorHierarchyTargets();

  clearMonitorTrashDropTarget();

  if (monitorTrashDropTargetAt(event.clientX,event.clientY)) { monitorNodeTrash.classList.add("monitor-node-trash-drop-target"); return; }

  if (monitorStructureOpen) {

    const hierarchyTarget = monitorHierarchyTargetAt(event.clientX, event.clientY);

    if (hierarchyTarget) hierarchyTarget.classList.add("monitor-org-socket-target");

    return;

  }

  if (monitorCreateDesktopDropTargetAt(event.clientX, event.clientY)) {

    monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");

    return;

  }

  const target = monitorDesktopDropTargetAt(event.clientX, event.clientY);

  if (target && target.dataset.desktopId && (event.shiftKey || drag.copyMode || target.dataset.desktopId !== drag.sourceDesktopId)) target.classList.add("monitor-desktop-drop-target");

}

async function finishMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  monitorWindowPointerDrag = null;

  drag.img?.classList.remove("monitor-window-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  try { drag.img?.releasePointerCapture(event.pointerId); } catch (_) {}

  if (!drag.moved) {

    if (drag.initiallySelected && !drag.ctrlSelectionHandled) applyMonitorWindowHighlight(drag.hwnd, { toggle: true });

    clearMonitorDesktopDropTargets(); clearMonitorHierarchyTargets(); return;

  }

  if (monitorStructureOpen) {

    const hierarchyTarget = monitorHierarchyTargetAt(event.clientX, event.clientY);

    clearMonitorHierarchyTargets();

    if (!hierarchyTarget) return;

    try { await monitorHierarchyApplyDrop(hierarchyTarget, drag.hwnd); }

    catch (error) { const st=document.getElementById("monitorStructureStatus"); if(st)st.textContent=`지정 실패 · ${monitorDiagTextError(error?.message||error)}`; }

    return;

  }

  const trashTarget = monitorTrashDropTargetAt(event.clientX,event.clientY);

  const createTarget = trashTarget ? null : monitorCreateDesktopDropTargetAt(event.clientX, event.clientY);

  const target = (trashTarget||createTarget) ? null : monitorDesktopDropTargetAt(event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (trashTarget) { const keys=[...new Set((drag.entries||[]).flatMap((entry)=>monitorConversationKeysForHwnd(entry.hwnd)))]; if(await trashMonitorConversationKeys(keys,"thumbnail")){monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);} return; }

  if (createTarget) {

    monitorCreateDesktopDropConsumedUntil = Date.now() + 700;

    monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

    try {

      const created = await createDesktopForDrop(drag.sourceDesktopId, drag.entries.map((item) => item.hwnd), Boolean(event.shiftKey || drag.copyMode));

      if (created?.ok) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");

    } catch (error) {

      setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message || error}`, false);

    } finally {

      setTimeout(() => monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending", "monitor-create-desktop-drop-success"), 650);

    }

    return;

  }

  const targetDesktopId = target?.dataset?.desktopId || "";

  const copyMode = Boolean(event.shiftKey || drag.copyMode);

  if (!target || !targetDesktopId || (!copyMode && targetDesktopId === drag.sourceDesktopId)) return;

  target.classList.add("monitor-desktop-drop-pending");

  try {

    if (await performMonitorWindowDrop(drag.entries, targetDesktopId, copyMode)) target.classList.add("monitor-desktop-drop-success");

  } finally {

    setTimeout(() => target.classList.remove("monitor-desktop-drop-pending", "monitor-desktop-drop-success"), 650);

  }

}

function cancelMonitorWindowPointerDrag(event) {

  const drag = monitorWindowPointerDrag;

  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;

  monitorWindowPointerDrag = null;

  drag.img?.classList.remove("monitor-window-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  clearMonitorDesktopDropTargets();

  clearMonitorHierarchyTargets();

  clearMonitorTrashDropTarget();

}

function beginMonitorDesktopPointerDrag(event) {

  if (event.button !== 0 || event.target?.closest?.(".monitor-desktop-thumb-window")) return;

  const button = event.currentTarget;

  const sourceDesktopId = String(button?.dataset?.desktopId || "");

  if (!sourceDesktopId) return;

  const visual = button.querySelector(".monitor-desktop-thumb-visual") || button;

  const ghost = createMonitorNodeDragGhost(visual, event);

  ghost.classList.add("monitor-desktop-drag-ghost");

  moveMonitorNodeDragGhost(ghost, event.clientX, event.clientY);

  monitorDesktopPointerDrag = { pointerId: event.pointerId, sourceDesktopId, button, ghost, startX: event.clientX, startY: event.clientY, moved: false, copyMode: Boolean(event.shiftKey) };

  try { button.setPointerCapture(event.pointerId); } catch (_) {}

}

function updateMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= 6) {

    drag.moved = true;

    drag.button.classList.add("monitor-desktop-dragging");

  }

  if (!drag.moved) return;

  event.preventDefault();

  moveMonitorNodeDragGhost(drag.ghost, event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (drag.sourceDesktopId !== monitorDesktopState.currentDesktopId && monitorTrashDropTargetAt(event.clientX,event.clientY)) { monitorNodeTrash.classList.add("monitor-node-trash-drop-target"); return; }

  if (monitorCreateDesktopDropTargetAt(event.clientX, event.clientY)) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-target");

}

async function finishMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || event.pointerId !== drag.pointerId) return;

  monitorDesktopPointerDrag = null;

  drag.button.classList.remove("monitor-desktop-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  try { drag.button.releasePointerCapture(event.pointerId); } catch (_) {}

  if (!drag.moved) { clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget(); return; }

  drag.button.dataset.monitorDropSuppressClick = "1";

  setTimeout(() => delete drag.button.dataset.monitorDropSuppressClick, 0);

  const trashTarget = drag.sourceDesktopId !== monitorDesktopState.currentDesktopId ? monitorTrashDropTargetAt(event.clientX,event.clientY) : null;

  const createTarget = trashTarget ? null : monitorCreateDesktopDropTargetAt(event.clientX, event.clientY);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

  if (trashTarget) {

    const sourceIndex=monitorDesktopState.desktopIds.indexOf(drag.sourceDesktopId);

    if(sourceIndex>=0){await removeVirtualDesktopPreview(sourceIndex,{trashDrop:true});monitorNodeTrash.classList.add("monitor-node-trash-drop-success");setTimeout(()=>clearMonitorTrashDropTarget(),650);}

    return;

  }

  if (!createTarget) return;

  monitorCreateDesktopDropConsumedUntil = Date.now() + 700;

  monitorCreateDesktop.classList.add("monitor-create-desktop-drop-pending");

  try {

    const hwnds = await getDesktopBrowserWindowHandles(drag.sourceDesktopId);

    const created = await createDesktopForDrop(drag.sourceDesktopId, hwnds, Boolean(event.shiftKey || drag.copyMode));

    if (created?.ok) monitorCreateDesktop.classList.add("monitor-create-desktop-drop-success");

  } catch (error) {

    setMonitorStatus(`새 데스크톱 이동 실패 · ${error?.message || error}`, false);

  } finally {

    setTimeout(() => monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-pending", "monitor-create-desktop-drop-success"), 650);

  }

}

function cancelMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;

  monitorDesktopPointerDrag = null;

  drag.button?.classList.remove("monitor-desktop-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

}

document.addEventListener("pointermove", updateMonitorWindowPointerDrag, true);

document.addEventListener("pointerup", finishMonitorWindowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWindowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointerup", finishMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorDesktopPointerDrag, true);

document.addEventListener("pointerup", finishMonitorDesktopPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorDesktopPointerDrag, true);

function invalidateMonitorDesktopFrames(...desktopIds) {

  // Every invalidation starts a new capture generation so an older in-flight

  // capture can never repopulate the cache after a move/layout change.

  // Generation invalidation is scoped below after the affected desktop IDs are known.

  // Thumbnail batch generation only changes for a full invalidation.

  const ids = new Set(desktopIds.filter(Boolean).map(String));
  if (!ids.size) {
    monitorFrameGeneration += 1;
    monitorFrameDesktopGenerations.clear();
    monitorThumbBatchGeneration += 1;
  } else {
    for (const desktopId of ids) {
      monitorFrameDesktopGenerations.set(desktopId, Number(monitorFrameDesktopGenerations.get(desktopId) || 0) + 1);
    }
  }

  for (const key of [...monitorFrameCache.keys()]) {

    // cacheKey = generation:desktopId:profile:hostHwnd

    const desktopId = String(key).split(":")[1] || "";

    if (!ids.size || ids.has(desktopId)) monitorFrameCache.delete(key);

  }

}

async function moveMonitorWindowToDesktop(hwnd, sourceDesktopId, targetDesktopId) {

  if (!/^\d+$/.test(String(hwnd || "")) || !targetDesktopId) return false;

  const result = await monitorNative({ type: "moveWindowToDesktop", hwnd: String(hwnd), desktopId: targetDesktopId }).catch(() => null);

  if (!result?.ok) return false;

  const actualSourceDesktopId = sourceDesktopId || result.sourceDesktopId || "";

  invalidateMonitorDesktopFrames(actualSourceDesktopId, targetDesktopId);

  setTimeout(() => { refreshDesktopDropThumbnails(actualSourceDesktopId, targetDesktopId).catch(() => {}); }, 120);

  return true;

}

async function getDesktopBrowserWindowHandles(desktopId) {

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") throw new Error("Monitor host HWND를 확인할 수 없어 데스크톱 이동을 중단했습니다.");

  const snapshot = await monitorNative({ type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true });

  if (!snapshot?.ok) throw new Error(snapshot?.error || "데스크톱 창 목록을 읽지 못했습니다.");

  const hwnds = (Array.isArray(snapshot.windows) ? snapshot.windows : [])

    .filter((item) => item?.className === "Chrome_WidgetWin_1" && (item?.visible || item?.iconic))

    .map((item) => String(item?.hwnd || ""))

    .filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0" && hwnd !== hostHwnd);

  return [...new Set(hwnds)];

}

async function refreshDesktopDropThumbnails(sourceDesktopId, targetDesktopId) {

  invalidateMonitorDesktopFrames(sourceDesktopId, targetDesktopId);

  await new Promise((resolve) => setTimeout(resolve, 140));

  for (const desktopId of [sourceDesktopId, targetDesktopId]) {

    const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === desktopId);

    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

    if (visual) await refreshDesktopThumb(visual, desktopId);

  }

  await refreshObservedWindows();

}

async function createDesktopForDrop(sourceDesktopId, hwnds, copyMode = false) {

  if (monitorCreateDesktopDropBusy) return { ok: false, error: "DROP_BUSY" };

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!sourceDesktopId || !/^\d+$/.test(hostHwnd) || hostHwnd === "0") throw new Error("Monitor host HWND 또는 원본 데스크톱을 확인할 수 없습니다.");

  const exactHwnds = [...new Set((Array.isArray(hwnds) ? hwnds : []).map(String).filter((hwnd) => /^\d+$/.test(hwnd) && hwnd !== "0" && hwnd !== hostHwnd))];

  if (!exactHwnds.length) throw new Error("이동할 브라우저 창이 없습니다.");

  const authoritative = await monitorNative({ type: "getDesktopWindowHandles", desktopId: sourceDesktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true });

  if (!authoritative?.ok) throw new Error(authoritative?.error || "원본 데스크톱 창 목록을 확인하지 못했습니다.");

  const authoritativeHwnds = new Set((Array.isArray(authoritative.windows) ? authoritative.windows : []).map((item) => String(item?.hwnd || "")));

  const stale = exactHwnds.filter((hwnd) => !authoritativeHwnds.has(hwnd));

  if (stale.length) throw new Error(`원본 데스크톱에서 HWND를 재확인하지 못했습니다 · ${stale.join(",")}`);

  monitorCreateDesktopDropBusy = true;

  try {

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const result = await monitorNative({ type: "createVirtualDesktop" });

    if (!result?.ok) throw new Error(result?.error || "새 데스크톱 생성 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const createdIds = resultIds.filter((id) => !beforeIds.has(id));

    if (createdIds.length !== 1) throw new Error(`새 데스크톱 식별 실패 · created=${createdIds.length}`);

    const createdId = createdIds[0];

    const entries = exactHwnds.map((hwnd) => ({ hwnd, sourceDesktopId }));

    const success = copyMode

      ? await cloneMonitorWindowSet(entries, createdId, "create-copy", { createdId, sourceDesktopId })

      : await moveMonitorWindowSet(entries, createdId, "create-move", { createdId, sourceDesktopId });

    const moved = success ? [...exactHwnds] : [];

    const failed = success ? [] : [...exactHwnds];

    monitorDesktopState.observedDesktopId = createdId;

    renderVirtualDesktops(result);

    const createdIndex = monitorDesktopState.desktopIds.indexOf(createdId);

    if (createdIndex >= 0) selectVirtualDesktopPreview(createdIndex);

    await refreshDesktopDropThumbnails(sourceDesktopId, createdId);

    await refreshVirtualDesktops();

    settleNewDesktopWallpaper(createdId).catch(() => {});

    if (failed.length) {

      setMonitorStatus(`새 데스크톱 부분 이동 · 성공 ${moved.length} / 실패 ${failed.length}`, false);

      return { ok: false, partial: moved.length > 0, createdId, moved, failed };

    }

    return { ok: true, createdId, moved, failed: [] };

  } finally {

    monitorCreateDesktopDropBusy = false;

  }

}

function bindDesktopDropTarget(button) {

  if (!button || button.dataset.monitorDropBound) return;

  button.dataset.monitorDropBound = "1";

  const readPayload = (event) => {

    try { return JSON.parse(event.dataTransfer.getData("application/x-desktopwindow-hwnd") || "null"); } catch (_) { return null; }

  };

  button.addEventListener("dragover", (event) => {

    if (!event.dataTransfer.types.includes("application/x-desktopwindow-hwnd")) return;

    event.preventDefault(); event.dataTransfer.dropEffect = "move"; button.classList.add("monitor-desktop-drop-target");

  });

  button.addEventListener("dragleave", (event) => { if (!button.contains(event.relatedTarget)) button.classList.remove("monitor-desktop-drop-target"); });

  button.addEventListener("drop", async (event) => {

    event.preventDefault(); button.classList.remove("monitor-desktop-drop-target");

    const payload = readPayload(event);

    const targetDesktopId = button.dataset.desktopId || "";

    if (!payload?.hwnd || !targetDesktopId || payload.sourceDesktopId === targetDesktopId) return;

    button.classList.add("monitor-desktop-drop-pending");

    try { if (await moveMonitorWindowToDesktop(payload.hwnd, payload.sourceDesktopId, targetDesktopId)) button.classList.add("monitor-desktop-drop-success"); }

    finally { setTimeout(() => button.classList.remove("monitor-desktop-drop-pending", "monitor-desktop-drop-success"), 650); }

  });

}

async function refreshDesktopThumb(visual, desktopId) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED || !visual?.isConnected) return false;
  if (String(visual.dataset.desktopId || "").toLowerCase() !== String(desktopId || "").toLowerCase()) return false;
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer) return false;
  // Native is authoritative: explicit per-desktop GUID/file snapshot; never
  // use the legacy actual/restore/Progman wallpaper image maps.
  const wallpaperReady = await renderer.refreshWallpaper(visual, desktopId, id =>
    monitorNative({type:"getDesktopVisualSnapshot",desktopId:id,
      maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,quality:68}));
  if (!visual.isConnected || String(visual.dataset.desktopId).toLowerCase() !== String(desktopId).toLowerCase()) return false;
  // Window geometry is separate Native HWND truth; pixels never become wallpaper.
  // On other desktops capture may fail/CLOAKED; V2 renders a transparent outline.
  const frameToken = renderer.beginFrame(visual,desktopId);
  if (frameToken == null) return false;
  const frame = await captureDesktopFrame(desktopId, "thumb").catch(() => null);
  if (!frame || !visual.isConnected) { renderer.frameFailure(visual,desktopId,"FRAME_UNAVAILABLE",frameToken); return wallpaperReady; }
  return renderer.windowFrame(visual,desktopId,frame,{
    frameToken,
    afterRender: tile => {
      for (const image of tile.querySelectorAll(".monitor-desktop-thumb-window")) {
        const hwnd = String(image.dataset.hwnd || "");
        try {
          applyPersistentMonitorRoleClass(image,hwnd);
          image.classList.toggle("monitor-window-row-hovered",
            Boolean(monitorHoveredHwnd) && hwnd===monitorHoveredHwnd && !monitorSelectedHwnds.has(hwnd));
          syncMonitorStatusLayer(image,hwnd);
          syncMonitorPauseOverlay(image,hwnd);
          syncMonitorDesktopNumberBadge(image,hwnd);
          syncMonitorNonChatCountdown(image,hwnd);
          if (!image.dataset.monitorDragBound) {
            image.dataset.monitorDragBound="1";
            image.draggable=false;
            image.addEventListener("pointerdown",beginMonitorWindowPointerDrag);
          }
        }catch(error){ console.warn("Monitor thumbnail V2 badge delayed",hwnd,error); }
      }
      syncMonitorThumbnailTabBadges(tile,"monitor-desktop-thumb-window");
    }
  });
}

function syncMonitorMinimizedNodeBadges(state = monitorLastAiState) {
  const slotsByDesktop = monitorMinimizedNodeSlotsByDesktop(state);

  for (const button of monitorDesktopThumbs.children) {

    const visual = button.querySelector(".monitor-desktop-thumb-visual");

    if (!visual) continue;

    const label = button.querySelector(".monitor-desktop-thumb-label");
    if (!label) continue;
    visual.querySelector(".monitor-desktop-minimized-nodes")?.remove();
    let host = label.querySelector(".monitor-desktop-minimized-nodes");

    if (!host) { host = document.createElement("span"); host.className = "monitor-desktop-minimized-nodes"; label.append(host); }

    const slots = slotsByDesktop.get(String(button.dataset.desktopId || "")) || [];

    const visibleSlots = slots.slice(0, 2);
    const badges = visibleSlots.map((slot) => { const badge=document.createElement("span"); badge.className="monitor-node-number-badge monitor-desktop-minimized-node"; badge.textContent=String(slot); badge.title=`최소화 노드 ${slot}`; return badge; });
    if (slots.length >= 3) {
      const more = document.createElement("span");
      more.className = "monitor-desktop-minimized-more";
      more.textContent = "...";
      more.title = `최소화 노드 ${slots.length}개`;
      badges.push(more);
    }
    host.replaceChildren(...badges);

    host.hidden = slots.length === 0;

  }

}

