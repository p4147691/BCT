//@@FN_START:beginMonitorBctNodePointerDrag
function beginMonitorBctNodePointerDrag(event, row, node) {
  if (event.button !== 0 || !node?.conversationKey || monitorBctPointerDrag || monitorBctNodeReorderPending) return;
  monitorBctPointerDrag = {
    pointerId: event.pointerId,
    row,
    node,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
    drop: null,
  };
  // Document capture receives pointerup even beyond the row or the list.
  document.addEventListener("pointermove", updateMonitorBctNodePointerDrag, true);
  document.addEventListener("pointerup", endMonitorBctNodePointerDrag, true);
  document.addEventListener("pointercancel", cancelMonitorBctNodePointerDrag, true);
  window.addEventListener("blur", cancelMonitorBctNodePointerDrag);
  row.addEventListener("lostpointercapture", cancelMonitorBctNodePointerDrag);
  try { row.setPointerCapture(event.pointerId); } catch (_) {}
}
//@@FN_END:beginMonitorBctNodePointerDrag

//@@FN_START:beginMonitorDesktopPointerDrag
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
//@@FN_END:beginMonitorDesktopPointerDrag

//@@FN_START:beginMonitorWindowPointerDrag
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
//@@FN_END:beginMonitorWindowPointerDrag

//@@FN_START:beginMonitorWorkerRowPointerDrag
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
//@@FN_END:beginMonitorWorkerRowPointerDrag

//@@FN_START:bindDesktopDropTarget
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
//@@FN_END:bindDesktopDropTarget

//@@FN_START:cancelMonitorBctNodePointerDrag
function cancelMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;
  monitorBctStopDragInput(drag);
  if (drag.active) finishMonitorBctNodeDrag();
}
//@@FN_END:cancelMonitorBctNodePointerDrag

//@@FN_START:cancelMonitorDesktopPointerDrag
function cancelMonitorDesktopPointerDrag(event) {

  const drag = monitorDesktopPointerDrag;

  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;

  monitorDesktopPointerDrag = null;

  drag.button?.classList.remove("monitor-desktop-dragging");

  destroyMonitorNodeDragGhost(drag.ghost);

  clearMonitorDesktopDropTargets(); clearMonitorTrashDropTarget();

}
//@@FN_END:cancelMonitorDesktopPointerDrag

//@@FN_START:cancelMonitorWindowPointerDrag
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
//@@FN_END:cancelMonitorWindowPointerDrag

//@@FN_START:cancelMonitorWorkerRowPointerDrag
function cancelMonitorWorkerRowPointerDrag(event) {

  const drag=monitorWorkerRowPointerDrag; if(!drag||(event?.pointerId!=null&&event.pointerId!==drag.pointerId))return;

  monitorWorkerRowPointerDrag=null; drag.row?.classList.remove("monitor-worker-row-dragging"); destroyMonitorNodeDragGhost(drag.ghost); clearMonitorDesktopDropTargets(); clearMonitorWorkerOrderTargets(); clearMonitorTrashDropTarget();

}
//@@FN_END:cancelMonitorWorkerRowPointerDrag

//@@FN_START:clearMonitorBctNodeDropFeedback
function clearMonitorBctNodeDropFeedback() {
  monitorWorkers?.querySelectorAll?.(
    ".monitor-bct-drop-before,.monitor-bct-drop-after,.monitor-bct-node-list-target",
  ).forEach((element) => {
    element.classList.remove(
      "monitor-bct-drop-before",
      "monitor-bct-drop-after",
      "monitor-bct-node-list-target",
    );
    if (element.dataset) delete element.dataset.dropPosition;
  });
}
//@@FN_END:clearMonitorBctNodeDropFeedback

//@@FN_START:clearMonitorConversationRecovery
function clearMonitorConversationRecovery(){

  const recovery=monitorClosedConversationRecoveryItems(monitorLastAiState);

  for(const item of recovery){const key=String(item?.conversation_key||"").trim();if(key){monitorTrashedConversationKeys.add(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);}}

  for(const [key,item] of [...monitorTrashRecords]) if(String(item?.trash_source||"list")!=="thumbnail"){monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(String(key));}

  monitorRebootSnapshot={...monitorRebootSnapshot,items:[]};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}
//@@FN_END:clearMonitorConversationRecovery

//@@FN_START:clearMonitorDesktopDropTargets
function clearMonitorDesktopDropTargets() {

  for (const button of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb")) button.classList.remove("monitor-desktop-drop-target");

  monitorCreateDesktop.classList.remove("monitor-create-desktop-drop-target");

}
//@@FN_END:clearMonitorDesktopDropTargets

//@@FN_START:scheduleMonitorExternalWindowDropTargets
function scheduleMonitorExternalWindowDropTargets() {
  if (monitorExternalWindowDropTargetTimer) return;
  monitorExternalWindowDropTargetTimer = setTimeout(() => {
    monitorExternalWindowDropTargetTimer = 0;
    void syncMonitorExternalWindowDropTargets();
  }, 0);
}
//@@FN_END:scheduleMonitorExternalWindowDropTargets

//@@FN_START:recordMonitorExternalWindowDropPointer
function recordMonitorExternalWindowDropPointer(event) {
  const screenX = Number(event?.screenX);
  const screenY = Number(event?.screenY);
  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  if (![screenX, screenY, clientX, clientY].every(Number.isFinite)) return;
  // A pointer observed by the Monitor document gives the exact document-to-
  // screen offset, including Chrome's non-document chrome. This is more
  // reliable than assuming window.screenY is the document origin.
  monitorExternalWindowDropScreenOrigin = { left: screenX - clientX, top: screenY - clientY };
}
//@@FN_END:recordMonitorExternalWindowDropPointer

//@@FN_START:syncMonitorExternalWindowDropTargets
async function syncMonitorExternalWindowDropTargets() {
  const hostWindowHwnd = String(monitorDesktopState?.hostWindowHwnd || "").trim();
  const screenScale = Math.max(.5, Math.min(4, Number(window.devicePixelRatio) || 1));
  const screenOrigin = monitorExternalWindowDropScreenOrigin || { left: Number(window.screenX || 0), top: Number(window.screenY || 0) };
  const targets = [...monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb[data-desktop-id]")]
    .map((tile) => {
      const desktopId = String(tile.dataset.desktopId || "").trim().toLowerCase();
      const rect = tile.getBoundingClientRect();
      return { desktopId, left: screenOrigin.left + rect.left, top: screenOrigin.top + rect.top, width: rect.width, height: rect.height };
    })
    .filter((target) => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(target.desktopId) && target.width >= 16 && target.height >= 16);
  const signature = JSON.stringify({ hostWindowHwnd, screenScale, targets });
  if (signature === monitorExternalWindowDropTargetSignature) return;
  monitorExternalWindowDropTargetSignature = signature;
  if (!/^\d+$/.test(hostWindowHwnd) || hostWindowHwnd === "0") return;
  const receipt = await monitorNative({ type:"setExternalWindowDropTargets", hostWindowHwnd, screenScale, targets }).catch(() => null);
  if (!receipt?.ok) monitorExternalWindowDropTargetSignature = "";
}
//@@FN_END:syncMonitorExternalWindowDropTargets

//@@FN_START:handleMonitorExternalWindowDropFinished
async function handleMonitorExternalWindowDropFinished(event) {
  if (event?.ok !== true) return;
  const desktopId = String(event.desktopId || "").trim().toLowerCase();
  invalidateMonitorDesktopFrames(...[desktopId].filter(Boolean));
  await refreshVirtualDesktops();
  void refreshWindowsCurrentState();
  void refreshSelectedThumb();
}
//@@FN_END:handleMonitorExternalWindowDropFinished

//@@FN_START:clearMonitorTrashDropTarget
function clearMonitorTrashDropTarget() { monitorNodeTrash?.classList.remove("monitor-node-trash-drop-target","monitor-node-trash-drop-success"); }
//@@FN_END:clearMonitorTrashDropTarget

//@@FN_START:commitDesktopUndoRestore
function commitDesktopUndoRestore(now = Date.now()) { monitorRecoveryUndoSession.pop(now); }
//@@FN_END:commitDesktopUndoRestore

//@@FN_START:commitMonitorBctNodeDrop
async function commitMonitorBctNodeDrop(destinationGroupKey, targetConversationKey, position, destinationScopeName = "") {
  if (monitorBctNodeReorderPending) {
    finishMonitorBctNodeDrag();
    return;
  }
  const draggedKey = monitorBctDraggedNodeKey;
  const snapshot = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache.slice() : [];
  const semanticSnapshot = monitorUniqueBctConversationNodes(snapshot);
  const dragged = semanticSnapshot.find((node) => node.conversationKey === draggedKey);
  const destinationScopeId = destinationGroupKey === "__unassigned__" ? "" : destinationGroupKey;
  const destinationSample = semanticSnapshot.find((node) => (node.scopeId || "") === destinationScopeId);
  const movedAcrossScopes = (dragged?.scopeId || "") !== destinationScopeId;
  const resolvedDestinationScopeName = destinationScopeId
    ? String(destinationScopeName || destinationSample?.scopeName || "").trim()
    : "";
  if (!dragged || (movedAcrossScopes
    ? !monitorBctShell?.updateConversationScope || (destinationScopeId && !resolvedDestinationScopeName)
    : !monitorBctShell?.reorderConversations)) {
    finishMonitorBctNodeDrag();
    return;
  }

  const destination = semanticSnapshot
    .filter((node) => node.conversationKey !== draggedKey && (node.scopeId || "") === destinationScopeId)
    .sort(compareMonitorBctNodeDisplayOrder);
  let insertion = destination.length;
  if (targetConversationKey) {
    const targetIndex = destination.findIndex((node) => node.conversationKey === targetConversationKey);
    if (targetIndex >= 0) insertion = targetIndex + (position === "after" ? 1 : 0);
  }
  destination.splice(insertion, 0, dragged);
  const nextOrders = new Map(destination.map((node, index) => [node.conversationKey, index + 1]));

  if (movedAcrossScopes) {
    // Move the card immediately.  The write still goes through the same Core
    // metadata contract as the context menu; only a failed write rolls back.
    const optimisticSnapshot = snapshot.map((node) => {
      if (node.conversationKey !== draggedKey) return node;
      return Object.freeze({
        ...node,
        scopeId: destinationScopeId,
        scopeName: resolvedDestinationScopeName,
        displayOrder: nextOrders.get(draggedKey) || 1,
      });
    });
    monitorBctNodeReorderPending = true;
    monitorBctWindowNodesCache = optimisticSnapshot;
    finishMonitorBctNodeDrag();
    renderMonitorBctWindowNodes(optimisticSnapshot);
    try {
      await monitorBctShell.updateConversationScope(dragged, {
        displayName: String(dragged.title || dragged.nodeLabel || dragged.conversationKey || "ChatGPT").trim(),
        scopeName: resolvedDestinationScopeName,
        roleTags: Array.isArray(dragged.roleTags) ? dragged.roleTags : [],
      });
      await refreshMonitorBctWindowNodes();
      setMonitorStatus(
        destinationScopeId ? "노드를 대화망으로 이동했습니다." : "노드를 미소속 대화로 이동했습니다.",
        true,
        2200,
      );
    } catch (error) {
      if (monitorBctWindowNodesCache === optimisticSnapshot) {
        monitorBctWindowNodesCache = snapshot;
        renderMonitorBctWindowNodes(snapshot);
      }
      setMonitorStatus(`대화망 이동 실패 · ${error?.message || error}`, false, 4200);
    } finally {
      monitorBctNodeReorderPending = false;
    }
    return;
  }

  const optimisticSnapshot = snapshot.map((node) => {
    if (!nextOrders.has(node.conversationKey)) return node;
    return Object.freeze({
      ...node,
      scopeId: destinationScopeId,
      scopeName: destinationScopeId ? String(destinationSample?.scopeName || "") : "",
      displayOrder: nextOrders.get(node.conversationKey),
    });
  });
  monitorBctNodeReorderPending = true;
  monitorBctWindowNodesCache = optimisticSnapshot;
  finishMonitorBctNodeDrag();
  renderMonitorBctWindowNodes(optimisticSnapshot);
  try {
    await monitorBctShell.reorderConversations(destination, {
      scopeId: destinationScopeId,
      movedConversationKey: "",
    });
    setMonitorStatus("노드 표시 순서를 저장했습니다.", true, 2200);
  } catch (error) {
    // A newer RCC refresh replaces this exact snapshot. Never overwrite it.
    if (monitorBctWindowNodesCache === optimisticSnapshot) {
      monitorBctWindowNodesCache = snapshot;
      renderMonitorBctWindowNodes(snapshot);
    }
    setMonitorStatus(`노드 순서 저장 실패 · ${error?.message || error}`, false, 4200);
  } finally {
    monitorBctNodeReorderPending = false;
  }
}
//@@FN_END:commitMonitorBctNodeDrop

//@@FN_START:createDesktopForDrop
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
//@@FN_END:createDesktopForDrop

//@@FN_START:createMonitorNodeDragGhost
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
//@@FN_END:createMonitorNodeDragGhost

//@@FN_START:createMonitorWorkRecoveryButton
function createMonitorWorkRecoveryButton() {
  return globalThis.MonitorWorkRecovery.createButton({
    fetcher: actFetch,
    openConversation: target => restoreMonitorDetachedTask(target, document.createElement('button')),
  });
}
//@@FN_END:createMonitorWorkRecoveryButton

//@@FN_START:deleteMonitorRecoveryRecord
function deleteMonitorRecoveryRecord(key){

  key=String(key||""); if(!key)return; monitorTrashRecords.delete(key); monitorTrashedConversationKeys.add(key); monitorGhostCache.delete(key); monitorHiddenGhosts.delete(key);

  const items=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>String(x?.conversation_key||"").trim()!==key); monitorRebootSnapshot={...monitorRebootSnapshot,items};

  chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot}); monitorPublishSharedRebootSnapshot(); monitorGhostPersist(true); persistMonitorTrashedNodes(); if(monitorLastAiState)renderWorkers(monitorLastAiState); refreshMonitorRecoveryMenu();

}
//@@FN_END:deleteMonitorRecoveryRecord

//@@FN_START:deleteMonitorTrashRecord
function deleteMonitorTrashRecord(key){key=String(key||"");monitorTrashRecords.delete(key);monitorTrashedConversationKeys.add(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}
//@@FN_END:deleteMonitorTrashRecord

//@@FN_START:deleteMonitorTrashedDesktop
function deleteMonitorTrashedDesktop(id){monitorTrashedDesktops.delete(String(id||""));persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}
//@@FN_END:deleteMonitorTrashedDesktop

//@@FN_START:destroyMonitorNodeDragGhost
function destroyMonitorNodeDragGhost(ghost) { ghost?.remove(); }
//@@FN_END:destroyMonitorNodeDragGhost

//@@FN_START:endMonitorBctNodePointerDrag
function endMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  // Re-evaluate at pointerup. The last preview is never authority if the
  // pointer moved out of the hit-zone without another pointermove event.
  clearMonitorBctNodeDropFeedback();
  const drop = drag.active
    ? monitorBctNodeDropAt(event.clientX, event.clientY, drag.node.conversationKey)
    : null;
  monitorBctStopDragInput(drag);
  if (!drag.active) return;
  event.preventDefault();
  if (!drop) {
    finishMonitorBctNodeDrag();
    return;
  }
  void commitMonitorBctNodeDrop(
    drop.scopeId,
    drop.targetConversationKey,
    drop.position,
    drop.scopeName,
  );
}
//@@FN_END:endMonitorBctNodePointerDrag

//@@FN_START:expireDesktopUndoSession
function expireDesktopUndoSession(now = Date.now()) { return monitorRecoveryUndoSession.expire(now); }
//@@FN_END:expireDesktopUndoSession

//@@FN_START:finishMonitorBctNodeDrag
function finishMonitorBctNodeDrag() {
  stopMonitorBctNativePreview();
  const suppressedKey = monitorBctSuppressedClickKey;
  monitorBctSuppressScopeClickUntil = Date.now() + 350;
  monitorBctDraggedNodeKey = "";
  clearMonitorBctNodeDropFeedback();
  monitorWorkers?.querySelectorAll?.(".monitor-bct-node-row.is-dragging")
    .forEach((row) => row.classList.remove("is-dragging"));
  monitorBctDragGhost?.remove?.();
  monitorBctDragGhost = null;
  document.documentElement.classList.remove("monitor-bct-node-drag-active");
  monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list-available")
    .forEach((list) => list.classList.remove("monitor-bct-node-list-available"));
  globalThis.setTimeout(() => {
    if (monitorBctSuppressedClickKey === suppressedKey) monitorBctSuppressedClickKey = "";
  }, 400);
}
//@@FN_END:finishMonitorBctNodeDrag

//@@FN_START:finishMonitorDesktopPointerDrag
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
//@@FN_END:finishMonitorDesktopPointerDrag

//@@FN_START:finishMonitorWindowPointerDrag
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
//@@FN_END:finishMonitorWindowPointerDrag

//@@FN_START:finishMonitorWorkerRowPointerDrag
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
//@@FN_END:finishMonitorWorkerRowPointerDrag

//@@FN_START:flashDesktopTransition
function flashDesktopTransition() {

  monitorTransitionFlash.classList.remove("active");

  const button=[...monitorDesktopThumbs.children].find((node)=>Number(node.dataset.index)===monitorDesktopState.selectedIndex);

  if(!button)return;

  button.classList.remove("monitor-desktop-card-flash");

  void button.offsetWidth;

  button.classList.add("monitor-desktop-card-flash");

  setTimeout(()=>button.classList.remove("monitor-desktop-card-flash"),420);

}
//@@FN_END:flashDesktopTransition

//@@FN_START:getDesktopBrowserWindowHandles
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
//@@FN_END:getDesktopBrowserWindowHandles

//@@FN_START:invalidateMonitorDesktopFrames
function invalidateMonitorDesktopFrames(...desktopIds) {

  // Every invalidation starts a new capture generation so an older in-flight

  // capture can never repopulate the cache after a move/layout change.

  // Generation invalidation is scoped below after the affected desktop IDs are known.

  // Thumbnail batch generation only changes for a full invalidation.

  const ids = monitorDesktopFrameGenerationController.invalidate(desktopIds);
  if (!ids.size) monitorThumbBatchGeneration += 1;

  for (const key of [...monitorFrameCache.keys()]) {

    // cacheKey = generation:desktopId:profile:hostHwnd

    const desktopId = String(key).split(":")[1] || "";

    if (!ids.size || ids.has(desktopId)) monitorFrameCache.delete(key);

  }

}
//@@FN_END:invalidateMonitorDesktopFrames

//@@FN_START:monitorActDesktopVisualForDesktop
function monitorActDesktopVisualForDesktop(desktopId, state = monitorLastAiState) {

  const visual = state?.node_state?.desktop_visual;

  if (String(visual?.authority || "") !== "ACT" || String(visual?.source || "") !== "ACT_NATIVE_OBSERVER") return null;

  const desk = (Array.isArray(visual?.desktops) ? visual.desktops : []).find((row) => String(row?.desktop_id || "") === String(desktopId || ""));

  if (!desk) return null;

  const viewport = desk?.viewport || {};

  const windows = (Array.isArray(desk?.windows) ? desk.windows : []).map((row) => ({

    hwnd:String(row?.hwnd||""), left:Number(row?.rect?.left||0), top:Number(row?.rect?.top||0),

    width:Number(row?.rect?.width||0), height:Number(row?.rect?.height||0), z:Number(row?.z||0),

    conversationKey:String(row?.conversation_key||"")

  })).filter((row) => /^\d+$/.test(row.hwnd) && row.hwnd !== "0");

  return {ok:true, authority:"ACT", desktopId:String(desktopId||""), windows,

    previewVirtualLeft:Number(viewport.left||0), previewVirtualTop:Number(viewport.top||0),

    previewVirtualWidth:Number(viewport.width||0), previewVirtualHeight:Number(viewport.height||0)};

}
//@@FN_END:monitorActDesktopVisualForDesktop

//@@FN_START:monitorApplySharedDesktopSelection
function monitorApplySharedDesktopSelection(desktopId) {

  const id = String(desktopId || "").trim(); monitorSharedSelectedDesktopId = id;

  if (!monitorSharedSelectionReady || !id || !monitorDesktopState.desktopIds.includes(id) || monitorDesktopState.observedDesktopId === id) return;

  monitorDesktopState.observedDesktopId = id;

  renderVirtualDesktops({ count:monitorDesktopState.count, currentIndex:monitorDesktopState.currentIndex, desktopIds:monitorDesktopState.desktopIds, currentDesktopId:monitorDesktopState.currentDesktopId, hostDesktopId:monitorDesktopState.hostDesktopId, hostWindowHwnd:monitorDesktopState.hostWindowHwnd });

  refreshObservedWindows();

}
//@@FN_END:monitorApplySharedDesktopSelection

//@@FN_START:monitorAttachDesktopManagementControl
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
//@@FN_END:monitorAttachDesktopManagementControl

//@@FN_START:monitorBctNodeDropAt
function monitorBctNodeDropAt(clientX, clientY, draggedKey) {
  if (monitorBctPointInsideScopeHeading(clientX, clientY)) return null;
  const hit = document.elementFromPoint(clientX, clientY);
  const list = monitorBctNodeDropListAt(clientX, clientY, hit);
  if (!list) return null;
  const scopeId = String(list.dataset.scopeId || "__unassigned__");
  const scopeName = String(list.dataset.scopeName || "").trim();
  const insertion = monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey);
  list.classList.add("monitor-bct-node-list-target");
  if (insertion) {
    const { row, position } = insertion;
    row.classList.add(position === "before" ? "monitor-bct-drop-before" : "monitor-bct-drop-after");
    row.dataset.dropPosition = position;
    return {
      scopeId,
      scopeName,
      targetConversationKey: String(row.dataset.conversationKey || ""),
      position,
    };
  }
  // An empty list (notably a newly empty 미소속 대화 list) still accepts the
  // node. There is no row to insert beside, so the destination appends it.
  return { scopeId, scopeName, targetConversationKey: "", position: "append" };
}
//@@FN_END:monitorBctNodeDropAt

//@@FN_START:monitorBctNodeDropListAt
function monitorBctNodeDropListAt(clientX, clientY, hit) {
  const direct = hit?.closest?.(".monitor-bct-node-list");
  const candidates = [...(monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list") || [])]
    .filter((list) => !list.hidden && monitorWorkers.contains(list))
    .map((list) => {
      const rect = list.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 ||
          clientX < rect.left - MONITOR_BCT_DROP_EDGE_X_PX ||
          clientX > rect.right + MONITOR_BCT_DROP_EDGE_X_PX ||
          clientY < rect.top - MONITOR_BCT_DROP_EDGE_Y_PX ||
          clientY > rect.bottom + MONITOR_BCT_DROP_EDGE_Y_PX) return null;
      const dx = Math.max(rect.left - clientX, 0, clientX - rect.right);
      const dy = Math.max(rect.top - clientY, 0, clientY - rect.bottom);
      return { list, distance: dx * dx + dy * dy };
    }).filter(Boolean);
  if (direct && candidates.some((candidate) => candidate.list === direct)) return direct;
  candidates.sort((a, b) => a.distance - b.distance);
  return candidates[0]?.list || null;
}
//@@FN_END:monitorBctNodeDropListAt

//@@FN_START:monitorBctStopDragInput
function monitorBctStopDragInput(drag) {
  if (monitorBctPointerDrag !== drag) return;
  monitorBctPointerDrag = null;
  document.removeEventListener("pointermove", updateMonitorBctNodePointerDrag, true);
  document.removeEventListener("pointerup", endMonitorBctNodePointerDrag, true);
  document.removeEventListener("pointercancel", cancelMonitorBctNodePointerDrag, true);
  window.removeEventListener("blur", cancelMonitorBctNodePointerDrag);
  drag.row?.removeEventListener("lostpointercapture", cancelMonitorBctNodePointerDrag);
  drag.row?.classList.remove("is-dragging");
  try { if (drag.row?.hasPointerCapture?.(drag.pointerId)) drag.row.releasePointerCapture(drag.pointerId); } catch (_) {}
}
//@@FN_END:monitorBctStopDragInput

//@@FN_START:monitorClosedConversationRecoveryItems
function monitorClosedConversationRecoveryItems(state = null) {

  const byKey=new Map();

  for(const g of monitorGhostCache.values()){const key=String(g?.conversation_key||"").trim();if(!g.open&&key&&!monitorTrashedConversationKeys.has(key))byKey.set(key,{...g,recovery_source:"일반 종료"});}

  const endpoints=Array.isArray(state?.endpoints)?state.endpoints:[]; let sharedChanged=false;

  const sharedItems=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).map((snap)=>{

    const key=String(snap?.conversation_key||"").trim(); if(!key)return snap; const ep=endpoints.find((x)=>String(x?.conversation_key||"").trim()===key)||null;

    const firstSeen=Number(monitorGhostTime(ep?.first_seen_at)||snap?.first_seen_ms||0); const closedAt=Number(monitorGhostTime(ep?.closed_at)||snap?.closed_at_ms||snap?.captured_at_ms||monitorRebootSnapshot?.captured_at_ms||0);

    if(firstSeen!==Number(snap?.first_seen_ms||0)||closedAt!==Number(snap?.closed_at_ms||0))sharedChanged=true;

    return {...snap,first_seen_ms:firstSeen,closed_at_ms:closedAt};

  });

  if(sharedChanged){monitorRebootSnapshot={...monitorRebootSnapshot,items:sharedItems};chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot});monitorPublishSharedRebootSnapshot();}

  const openKeys=new Set(endpoints.filter((x)=>String(x?.presence_state||"").toUpperCase()==="OPEN").map((x)=>String(x?.conversation_key||"").trim()).filter(Boolean));

  for(const snap of sharedItems){const key=String(snap?.conversation_key||"").trim();if(!key||monitorTrashedConversationKeys.has(key)||openKeys.has(key))continue;byKey.set(key,{...snap,open:false,recovery_source:"재부팅 이전"});}

  return [...byKey.values()].sort((a,b)=>{const ar=a.recovery_source==="재부팅 이전",br=b.recovery_source==="재부팅 이전";if(ar&&br)return Number(a.desktop||999)-Number(b.desktop||999)||Number(a.slot||999)-Number(b.slot||999);if(ar!==br)return ar?-1:1;return Number(b.closed_at_ms||b.captured_at_ms||0)-Number(a.closed_at_ms||a.captured_at_ms||0);});

}
//@@FN_END:monitorClosedConversationRecoveryItems

//@@FN_START:monitorCreateDesktopDropTargetAt
function monitorCreateDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.("#monitorCreateDesktop") === monitorCreateDesktop ? monitorCreateDesktop : null;

}
//@@FN_END:monitorCreateDesktopDropTargetAt

//@@FN_START:monitorDeletedDesktopDrawCover
function monitorDeletedDesktopDrawCover(ctx,image,width,height){

  if(!ctx||!image||!image.naturalWidth||!image.naturalHeight)return;

  const scale=Math.max(width/image.naturalWidth,height/image.naturalHeight);

  const drawWidth=image.naturalWidth*scale,drawHeight=image.naturalHeight*scale;

  ctx.drawImage(image,(width-drawWidth)/2,(height-drawHeight)/2,drawWidth,drawHeight);

}
//@@FN_END:monitorDeletedDesktopDrawCover

//@@FN_START:monitorDeletedDesktopLoadImage
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
//@@FN_END:monitorDeletedDesktopLoadImage

//@@FN_START:monitorDesktopDropTargetAt
function monitorDesktopDropTargetAt(clientX, clientY) {

  const hit = document.elementFromPoint(clientX, clientY);

  return hit?.closest?.(".monitor-desktop-thumb") || null;

}
//@@FN_END:monitorDesktopDropTargetAt

//@@FN_START:monitorDesktopFrameGeneration
function monitorDesktopFrameGeneration(desktopId) { return monitorDesktopFrameGenerationController.generation(desktopId); }
//@@FN_END:monitorDesktopFrameGeneration

//@@FN_START:monitorDesktopManagementMode
function monitorDesktopManagementMode(desktopId) { return monitorDesktopModeController.get(desktopId); }
//@@FN_END:monitorDesktopManagementMode

//@@FN_START:monitorDesktopManagementModeText
function monitorDesktopManagementModeText(mode) {
  if (mode === "MANAGED") return "관리";
  if (mode === "PROTECTED") return "보호";
  return "보기";
}
//@@FN_END:monitorDesktopManagementModeText

//@@FN_START:monitorDesktopManagementNextMode
function monitorDesktopManagementNextMode(mode) { return monitorDesktopModeController.next(mode); }
//@@FN_END:monitorDesktopManagementNextMode

//@@FN_START:monitorDesktopNodeSnapshots
function monitorDesktopNodeSnapshots(desktopId,index,state=monitorLastAiState){const targetDesktop=Number(index)+1,out=[];for(const worker of monitorWorkersForState(state||{})){const key=String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim();if(!key)continue;const loc=monitorCanonicalPhysicalLocation(worker,state||{}),actNode=monitorActBrowserNode(worker,state||{}),sameId=desktopId&&String(actNode?.desktop_id||"").trim()===String(desktopId);if(!(sameId||Number(loc?.desktop)===targetDesktop))continue;out.push({conversation_key:key,profile_id:String(worker?.profile_id||worker?.__endpoint?.profile_id||"").toUpperCase(),title:String(worker?.task_title||worker?.title||worker?.__endpoint?.title||""),node_label:String(actNode?.node_label||loc?.label||""),slot:Number(loc?.slot||0)||null,hwnd:String(loc?.hwnd||actNode?.hwnd||"")});}return out;}
//@@FN_END:monitorDesktopNodeSnapshots

//@@FN_START:monitorDesktopScrollStep
function monitorDesktopScrollStep(){const tile=monitorDesktopThumbs.querySelector(".monitor-desktop-thumb");return Math.max(132,Math.round(tile?.getBoundingClientRect?.().width||156)+8);}
//@@FN_END:monitorDesktopScrollStep

//@@FN_START:monitorIsActiveDesktopRenderer
function monitorIsActiveDesktopRenderer() {
  const hostDesktopId = String(monitorDesktopState.hostDesktopId || "").trim();
  const currentDesktopId = String(monitorDesktopState.currentDesktopId || "").trim();
  // Preserve startup/recovery until native host identity is known. After that,
  // only the Monitor on the current Windows virtual desktop may capture pixels.
  if (!hostDesktopId || !currentDesktopId) return true;
  return hostDesktopId === currentDesktopId;
}
//@@FN_END:monitorIsActiveDesktopRenderer

//@@FN_START:monitorMinimizedNodeSlotsByDesktop
function monitorMinimizedNodeSlotsByDesktop(state = monitorLastAiState) {
  return monitorMinimizedNodeBadgeContract?.slotsByDesktop?.({
    locations: monitorWindowDesktopLocations,
    numbersForHwnd: (hwnd) => monitorBadgeNodeNumbersForHwnd(hwnd, state),
  }) || new Map();
}
//@@FN_END:monitorMinimizedNodeSlotsByDesktop

//@@FN_START:monitorMinimizedNodeTokensByDesktop
function monitorMinimizedNodeTokensByDesktop(state = monitorLastAiState) {
  return monitorMinimizedNodeBadgeContract?.tokensByDesktop?.({
    locations: monitorWindowDesktopLocations,
    tokensForHwnd: (hwnd) => monitorBadgeNodeNumbersForHwnd(hwnd, state, { includeTabIds: true }),
  }) || new Map();
}
//@@FN_END:monitorMinimizedNodeTokensByDesktop
//@@FN_START:monitorObservedDesktopForHwnd
function monitorObservedDesktopForHwnd(hwnd, state = monitorLastAiState) {
  const key=String(hwnd||"").trim();
  if(!key||!state)return null;
  const observer=state?.node_state?.observer||null;
  if(String(observer?.source||"")==="ACT_NATIVE_OBSERVER"){
    const row=(Array.isArray(observer?.windows)?observer.windows:[]).find((item)=>String(item?.hwnd||"").trim()===key);
    if(row){
      const desktopId=String(row?.desktop_id||"").trim();
      const desktopRow=(Array.isArray(observer?.desktops)?observer.desktops:[]).find((item)=>String(item?.desktop_id||"").trim()===desktopId);
      const desktop=Number(desktopRow?.index)||0;
      if(desktopId)return {desktopId,desktop,authority:"ACT_NATIVE_OBSERVER"};
    }
  }
  const remembered=monitorWindowDesktopLocations.get(key);
  const desktopId=String(remembered?.desktopId||"").trim();
  if(!desktopId)return null;
  const desktop=monitorDesktopState.desktopIds.indexOf(desktopId)+1;
  return {desktopId,desktop:desktop>0?desktop:0,authority:"MONITOR_NATIVE_EVENT"};
}
//@@FN_END:monitorObservedDesktopForHwnd

//@@FN_START:monitorSetDesktopManagementMode
function monitorSetDesktopManagementMode(desktopId, nextMode) {
  const id = String(desktopId || "").trim();
  const mode = String(nextMode || "").toUpperCase();
  if (!monitorDesktopModeController.set(id, mode)) return;
  setMonitorStatus(`D${Math.max(1, monitorDesktopState.desktopIds.indexOf(id) + 1)} · ${monitorDesktopManagementModeText(mode)}`, true);
  syncDesktopSwitcher();
}
//@@FN_END:monitorSetDesktopManagementMode

//@@FN_START:monitorTrashDropTargetAt
function monitorTrashDropTargetAt(clientX, clientY) {

  if (monitorNodeTrash.hidden) return null;

  const hit=document.elementFromPoint(clientX,clientY);

  return hit?.closest?.("#monitorNodeTrash") || null;

}
//@@FN_END:monitorTrashDropTargetAt

//@@FN_START:monitorTrashRecordForKey
function monitorTrashRecordForKey(key,sourceKind="list"){

  key=String(key||"").trim(); if(!key)return null;

  const state=monitorLastAiState, ghost=monitorGhostCache.get(key)||{};

  const worker=state?monitorWorkersForState(state).find((x)=>String(x?.conversation_key||"").trim()===key):null;

  const endpoint=worker&&state?endpointForMonitorWorker(worker,state):(Array.isArray(state?.endpoints)?state.endpoints.find((x)=>String(x?.conversation_key||"").trim()===key):null);

  const em=endpoint?.metadata||{}; const desktop=Number(ghost?.desktop||em.desktop_id||em.desktop_index||0), slot=Number(ghost?.slot||em.slot_index||0);
  const bctNode=(Array.isArray(monitorBctWindowNodesCache)?monitorBctWindowNodesCache:[]).find((item)=>String(item?.conversationKey||"")===key)||{};

  return {...ghost,conversation_key:key,profile_id:String(ghost?.profile_id||worker?.profile_id||endpoint?.profile_id||"").toUpperCase(),title:String(ghost?.title||endpoint?.title||bctNode?.title||""),meaningful_title:String(ghost?.meaningful_title||worker?.task_title||endpoint?.title||bctNode?.title||""),node_label:String(bctNode?.nodeLabel||ghost?.node_label||""),network_id:String(bctNode?.scopeId||ghost?.network_id||""),network_name:String(bctNode?.scopeName||ghost?.network_name||""),role_tags:Array.isArray(bctNode?.roleTags)?[...bctNode.roleTags]:(Array.isArray(ghost?.role_tags)?ghost.role_tags:[]),desktop:Number.isInteger(desktop)&&desktop>0?desktop:null,slot:Number.isInteger(slot)&&slot>0?slot:null,first_seen_ms:Number(ghost?.first_seen_ms||monitorGhostTime(endpoint?.first_seen_at)||0),closed_at_ms:Number(ghost?.closed_at_ms||monitorGhostTime(endpoint?.closed_at)||0),trash_source:sourceKind==="thumbnail"?"thumbnail":"list",trashed_at_ms:Date.now()};

}
//@@FN_END:monitorTrashRecordForKey

//@@FN_START:moveMonitorNodeDragGhost
function moveMonitorNodeDragGhost(ghost, clientX, clientY) {

  if (!ghost) return;

  ghost.style.transform = `translate3d(${clientX}px, ${clientY}px, 0) translate(-50%, -50%)`;

}
//@@FN_END:moveMonitorNodeDragGhost

//@@FN_START:moveMonitorWindowToDesktop
async function moveMonitorWindowToDesktop(hwnd, sourceDesktopId, targetDesktopId) {

  if (!/^\d+$/.test(String(hwnd || "")) || !targetDesktopId) return false;

  const result = await monitorNative({ type: "moveWindowToDesktop", hwnd: String(hwnd), desktopId: targetDesktopId }).catch(() => null);

  if (!result?.ok) return false;

  const actualSourceDesktopId = sourceDesktopId || result.sourceDesktopId || "";

  invalidateMonitorDesktopFrames(actualSourceDesktopId, targetDesktopId);

  setTimeout(() => { refreshDesktopDropThumbnails(actualSourceDesktopId, targetDesktopId).catch(() => {}); }, 120);

  return true;

}
//@@FN_END:moveMonitorWindowToDesktop

//@@FN_START:openMonitorTrashRecovery
function openMonitorTrashRecovery() {
  if (!monitorNodeTrash || !monitorClosedRecoveryMenu) return;
  if (!monitorClosedConversationPickerOpen) monitorNodeTrash.click();
}
//@@FN_END:openMonitorTrashRecovery

//@@FN_START:peekDesktopUndoSnapshot
function peekDesktopUndoSnapshot(now = Date.now()) { return monitorRecoveryUndoSession.peek(now); }
//@@FN_END:peekDesktopUndoSnapshot

//@@FN_START:performMonitorWindowDrop
async function performMonitorWindowDrop(entries, targetDesktopId, copyMode) {

  return copyMode ? cloneMonitorWindowSet(entries, targetDesktopId) : moveMonitorWindowSet(entries, targetDesktopId);

}
//@@FN_END:performMonitorWindowDrop

//@@FN_START:persistMonitorTrashedDesktops
function persistMonitorTrashedDesktops(){chrome.storage.local.set({[MONITOR_TRASHED_DESKTOPS_KEY]:[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,30)});}
//@@FN_END:persistMonitorTrashedDesktops

//@@FN_START:persistMonitorTrashedNodes
function persistMonitorTrashedNodes(){

  const records=[...monitorTrashRecords.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX);

  chrome.storage.local.set({[MONITOR_TRASHED_NODES_KEY]:[...monitorTrashedConversationKeys],[MONITOR_TRASH_RECORDS_KEY]:records});

}
//@@FN_END:persistMonitorTrashedNodes

//@@FN_START:positionMonitorTrashRecoveryMenu
function positionMonitorTrashRecoveryMenu(){

  if(!monitorClosedRecoveryMenu||!monitorNodeTrash)return; const r=monitorNodeTrash.getBoundingClientRect();

  const width=Math.min(760,Math.max(420,window.innerWidth-24)); const left=Math.max(12,Math.min(window.innerWidth-width-12,r.right-width));

  const bottom=Math.max(12,window.innerHeight-r.top+8); const available=Math.max(180,r.top-18);

  monitorClosedRecoveryMenu.style.width=`${width}px`; monitorClosedRecoveryMenu.style.left=`${left}px`; monitorClosedRecoveryMenu.style.right="auto"; monitorClosedRecoveryMenu.style.top="auto"; monitorClosedRecoveryMenu.style.bottom=`${bottom}px`; monitorClosedRecoveryMenu.style.height=`${available}px`; monitorClosedRecoveryMenu.style.setProperty("max-height",`${available}px`,"important");

}
//@@FN_END:positionMonitorTrashRecoveryMenu

//@@FN_START:primeSelectedDesktopPreview
function primeSelectedDesktopPreview(desktopId) {
  const id = String(desktopId || "");
  if (!id) return;
  const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === id);
  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
  monitorWindowLayer.replaceChildren();
  monitorWindowLayer.dataset.desktopId = id;
  monitorPreviewBackground.begin(id);
  if (!visual) return;
  syncMonitorPreviewBackground(visual,id);
  for (const source of visual.querySelectorAll(".monitor-desktop-thumb-window")) {
    const img = source.cloneNode(false);
    img.className = "monitor-window-preview";
    img.dataset.hwnd = String(source.dataset.hwnd || "");
    monitorWindowLayer.append(img);
  }
}
//@@FN_END:primeSelectedDesktopPreview

//@@FN_START:pushDesktopUndoSnapshot
function pushDesktopUndoSnapshot(snapshot, now = Date.now()) { monitorRecoveryUndoSession.push(snapshot, now); }
//@@FN_END:pushDesktopUndoSnapshot

//@@FN_START:refreshMonitorRecoveryMenu
function refreshMonitorRecoveryMenu(){

  if(!(monitorClosedConversationPickerOpen&&monitorClosedRecoveryMenu&&monitorLastAiState))return;

  const panes=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane-scroll')].map((el)=>({cls:el.parentElement?.className||'',top:el.scrollTop}));

  monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));

  for(const saved of panes){const pane=[...monitorClosedRecoveryMenu.querySelectorAll('.monitor-trash-pane')].find((el)=>(el.className||'')===saved.cls);const scroll=pane?.querySelector('.monitor-trash-pane-scroll');if(scroll)scroll.scrollTop=saved.top;}

}
//@@FN_END:refreshMonitorRecoveryMenu

//@@FN_START:refreshVirtualDesktops
async function refreshVirtualDesktops() {

  try {

    if (!monitorInitialThumbBatchDone) monitorInitialThumbStage = "topology-requesting";
    const currentWindow = await chrome.windows.getCurrent();

    const topology = await monitorNative({

      type: "getVirtualDesktops", hostTitle: document.title,

      left: currentWindow?.left, top: currentWindow?.top,

      width: currentWindow?.width, height: currentWindow?.height

    });

    if (topology?.ok) {

      if (!monitorInitialThumbBatchDone) monitorInitialThumbStage = "cards-rendering";
      try {
        renderVirtualDesktops(topology);
      } catch (error) {
        // Card extras must never prevent the independent exact-GUID
        // background layer from reaching its Native source.
        monitorInitialThumbStage = "cards-partial";
        monitorInitialThumbError = String(error?.message || error || "CARD_RENDER_EXCEPTION").slice(0,160);
      }

      if (!monitorInitialThumbBatchDone) await refreshInitialSelectedThumb({ allowWindows: false });

      // Window ownership is a separate, later layer. It must not delay card
      // creation or exact-GUID wallpaper acceptance.
      const state = await globalThis.MonitorHostWindowIdentity.resolve(topology, {
        title: document.title,
        bounds: {left:currentWindow?.left,top:currentWindow?.top,
          width:currentWindow?.width,height:currentWindow?.height},
        requestNative: query => monitorNative(query),
        isOwnTitle: monitorIsOwnWindowTitle,
      });
      if (state !== topology) {
        try { renderVirtualDesktops(state); }
        catch (error) {
          monitorInitialThumbError = String(error?.message || error || "HOST_RENDER_EXCEPTION").slice(0,160);
        }
      }

      const resolved = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0";

      if (resolved) {

        if (!monitorInitialWindowBatchDone) await refreshInitialSelectedThumb({ allowWindows: true });

        monitorHostResolveRetryCount = 0;

        if (monitorHostResolveRetryTimer) clearTimeout(monitorHostResolveRetryTimer);

        monitorHostResolveRetryTimer = 0;

      } else if (monitorHostResolveRetryCount < 8 && !monitorHostResolveRetryTimer) {

        monitorHostResolveRetryCount += 1;

        monitorHostResolveRetryTimer = setTimeout(() => {

          monitorHostResolveRetryTimer = 0;

          refreshVirtualDesktops();

        }, Math.min(1200, 250 + monitorHostResolveRetryCount * 150));

      }

    } else if (!monitorHostResolveRetryTimer) {

      monitorInitialThumbStage = "topology-failed";
      monitorInitialThumbError = String(topology?.error || "GET_VIRTUAL_DESKTOPS_FAILED").slice(0,160);
      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  } catch (error) {

    monitorInitialThumbStage = "topology-exception";
    monitorInitialThumbError = String(error?.message || error || "TOPOLOGY_EXCEPTION").slice(0,160);
    if (!monitorHostResolveRetryTimer) {

      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  }

}
//@@FN_END:refreshVirtualDesktops

//@@FN_START:rememberMonitorDesktopWindows
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
//@@FN_END:rememberMonitorDesktopWindows

//@@FN_START:removeCreatedDesktopIfSafe
async function removeCreatedDesktopIfSafe(snapshot) {

  const createdId = String(snapshot?.createdId || ""); if (!createdId) return;

  await new Promise((resolve) => setTimeout(resolve, 260));

  const check = await monitorNative({ type: "getDesktopWindowHandles", desktopId: createdId }).catch(() => null);

  if (!check?.ok || (Array.isArray(check.hwnds) && check.hwnds.length)) return;

  await refreshVirtualDesktops();

  const index = monitorDesktopState.desktopIds.indexOf(createdId); if (index < 0 || monitorDesktopState.count <= 1) return;

  const sourceIndex = Math.max(0, monitorDesktopState.desktopIds.indexOf(String(snapshot.sourceDesktopId || "")));

  const fallbackIndex = sourceIndex === index ? (index > 0 ? index - 1 : Math.min(1, monitorDesktopState.count - 1)) : sourceIndex;

  await monitorNative({ type: "removeVirtualDesktop", index, fallbackIndex }).catch(() => null);

  await refreshVirtualDesktops();

}
//@@FN_END:removeCreatedDesktopIfSafe

//@@FN_START:removeVirtualDesktopPreview
async function removeVirtualDesktopPreview(index, options={}) {

  if (monitorDesktopState.count <= 1 || index < 0 || index >= monitorDesktopState.count) return;

  const desktopId = monitorDesktopState.desktopIds[index] || null;

  const fallbackIndex = index < monitorDesktopState.count - 1 ? index + 1 : index - 1;

  try {

    const nodeSnapshots = monitorDesktopNodeSnapshots(desktopId,index);

    const snapshot = desktopId ? await monitorNative({ type: "getDesktopWindowHandles", desktopId }) : null;

    const wallpaperDataUri = desktopId ? await getObservedWallpaper(desktopId, true) : "";

    const thumbnail = desktopId ? await monitorFreezeDesktopThumbnail(desktopId, wallpaperDataUri).catch(() => "") : "";

    const hwnds = Array.isArray(snapshot?.hwnds) ? snapshot.hwnds.map(String).filter(Boolean) : [];

    const result = await monitorNative({ type: "removeVirtualDesktop", index, fallbackIndex });

    if (!result?.ok) throw new Error(result?.error || "데스크톱 삭제 실패");

    monitorFrameCache.clear(); monitorWallpaperCache.delete(desktopId); monitorWallpaperActuals.delete(desktopId);

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    if (monitorDesktopState.observedDesktopId === desktopId) {

      monitorDesktopState.observedDesktopId = resultIds[Math.min(index, Math.max(0, resultIds.length - 1))] || resultIds[0] || null;

    }

    renderVirtualDesktops(result);

    const undoSnapshot={kind:"desktop-delete",desktopId,index,hwnds,nodes:nodeSnapshots,wallpaperDataUri,thumbnail};

    storeMonitorTrashedDesktop({desktopId,index,desktop_number:index+1,thumbnail,hwnds,nodes:nodeSnapshots});

    showDeletedDesktopTrashUndo(undoSnapshot);

    flashDesktopTransition();

  } catch (error) { setMonitorStatus(`데스크톱 삭제 실패 · ${error?.message || error}`, false); }

}
//@@FN_END:removeVirtualDesktopPreview

//@@FN_START:renderLightweightDesktopCards
function renderLightweightDesktopCards(reason = "EXPLICIT") {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) { monitorDesktopThumbs.replaceChildren(); return true; }

  const ids = Array.isArray(monitorDesktopState.desktopIds) ? monitorDesktopState.desktopIds.filter(Boolean) : [];

  if (!ids.length) return false;

  monitorDesktopThumbs.replaceChildren();
  monitorDesktopThumbs.dataset.thumbnailCardRenderer = "lightweight";
  monitorDesktopThumbs.dataset.thumbnailCardRendererReason = String(reason || "EXPLICIT");
  const createdVisuals = [];

  ids.forEach((desktopId, index) => {

    const button = document.createElement("button");

    button.type = "button"; button.className = "monitor-desktop-thumb monitor-desktop-thumb-lite";

    button.dataset.desktopId = desktopId; button.dataset.index = String(index);

    button.classList.toggle("selected", index === monitorDesktopState.selectedIndex);

    button.classList.toggle("current", index === monitorDesktopState.currentIndex);

    const visual = document.createElement("span");

    visual.className = "monitor-desktop-thumb-visual"; visual.dataset.desktopId = desktopId;

    const label = document.createElement("span"); label.className = "monitor-desktop-thumb-label";

    const badge = document.createElement("span"); badge.className = "monitor-desktop-number-badge"; badge.textContent = `D${index + 1}`;

    const text = document.createElement("span"); text.className = "monitor-desktop-label-text"; text.textContent = `???? ${index + 1}`;

    const minimizedNodes = document.createElement("span");
    minimizedNodes.className = "monitor-desktop-minimized-nodes";
    minimizedNodes.hidden = true;
    label.append(badge, text, minimizedNodes); button.append(visual, label); monitorAttachDesktopManagementControl(label, desktopId);

    button.addEventListener("click", () => selectVirtualDesktopPreview(index));

    button.addEventListener("dblclick", async (event) => {

      event.preventDefault();

      const result = await monitorNative({ type:"switchVirtualDesktop", index }).catch(() => null);

      if (result?.ok) { renderVirtualDesktops(result); selectVirtualDesktopPreview(index); }

    });

    monitorDesktopThumbs.append(button);
    createdVisuals.push({visual, desktopId});

  });

  requestAnimationFrame(() => {
    const renderer = globalThis.MonitorDesktopThumbnailV2;
    for (const entry of createdVisuals) {
      if (entry.visual.isConnected) void renderer?.refreshBackground?.(entry.visual, entry.desktopId).catch(() => null);
    }
  });
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") !== false) syncMonitorMinimizedNodeBadges();
  return true;

}
//@@FN_END:renderLightweightDesktopCards

//@@FN_START:renderMonitorClosedConversationRecoveryPanel
function renderMonitorClosedConversationRecoveryPanel(state) {

  const panel=document.createElement("div"); panel.className="monitor-closed-conversation-panel monitor-trash-recovery-panel";

  const items=monitorClosedConversationRecoveryItems(state);

  const makeHeader=(label,count,onClear,extras=[])=>{const head=document.createElement("div");head.className="monitor-trash-pane-header";const title=document.createElement("strong");title.textContent=`${label} (${count})`;const actions=document.createElement("span");actions.className="monitor-trash-pane-actions";for(const button of extras)if(button)actions.append(button);const clear=document.createElement("button");clear.type="button";clear.className="monitor-trash-clear-all";clear.textContent="다 비움";clear.disabled=!count;clear.addEventListener("click",(e)=>{e.stopPropagation();if(confirm(`${label} 항목을 모두 비울까요?`))onClear();});actions.append(clear);head.append(title,actions);return head;};

  const recoveryWorkers=monitorWorkersForState(state||{});

  const recoveryWorkerByKey=new Map(recoveryWorkers.map((worker)=>[String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim(),worker]).filter(([key])=>key));

  const recoveryEndpoints=Array.isArray(state?.endpoints)?state.endpoints:[];

  const recoveryNodeStatus=(key,record=null)=>{

    key=String(key||"").trim();

    const endpoint=recoveryEndpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key)||null;

    const open=String(endpoint?.presence_state||"").toUpperCase()==="OPEN";

    const worker=recoveryWorkerByKey.get(key)||null;

    const work=String(worker?resolveWorkerWorkState(worker,state):(record?.work_status||record?.task_status||"")).trim().toLowerCase();

    if(["running","working","busy","executing","in_progress"].includes(work))return {label:"처리 중",tone:"processing"};

    if(["waiting_resource","waiting","paused","queued","pending"].includes(work))return {label:"대기 중",tone:"waiting"};

    if(["needs_review","failed","failure","blocked","recovery","recovery_pending","degraded"].includes(work))return {label:"확인 필요",tone:"attention"};

    if(["succeeded","completed","complete","done"].includes(work))return {label:"완료",tone:"complete"};

    if(open)return {label:"활동 중",tone:"active"};

    return {label:"닫힘",tone:"closed"};

  };

  const appendRecoveryStatus=(row,key,record=null)=>{const status=recoveryNodeStatus(key,record);const badge=document.createElement("span");badge.className=`monitor-trash-node-status monitor-trash-node-status-${status.tone}`;badge.textContent=status.label;badge.title=`현재 상태: ${status.label}`;row.append(badge);};

  const noteRecords=[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const notePane=document.createElement("section");notePane.className="monitor-trash-pane monitor-trash-note-pane";notePane.append(makeHeader("삭제된 메모",noteRecords.length,clearMonitorTrashedNotes));const noteScroll=document.createElement("div");noteScroll.className="monitor-trash-pane-scroll";

  if(!noteRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";noteScroll.append(empty);}else for(const note of noteRecords){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-note-row";const info=document.createElement("div");info.className="monitor-closed-conversation-info monitor-trash-note-info";const noteTitle=document.createElement("strong");noteTitle.textContent=note.title||monitorNotesFeature.titleFromText(note.body)||"메모";const lines=String(note.body||"").split(/\r?\n/);const firstLineIndex=lines.findIndex((line)=>line.trim());const notePreview=document.createElement("span");notePreview.textContent=(firstLineIndex>=0?lines.slice(firstLineIndex+1).join(" "):"").replace(/\s+/g," ").trim()||"내용 없음";info.append(noteTitle,notePreview);const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashedNote(note.id);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedNote(note.id);});row.append(info,restore,del);noteScroll.append(row);}notePane.append(noteScroll);panel.append(notePane);

  const renderTrashRows=(source,container)=>{const records=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")===source).sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));if(!records.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";container.append(empty);return;}for(const ghost of records){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-record-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost),at=Number(ghost?.trashed_at_ms||0),scope=String(ghost?.network_name||"미소속"),roles=Array.isArray(ghost?.role_tags)&&ghost.role_tags.length?` · ${ghost.role_tags.join(", ")}`:"";info.textContent=`${String(ghost?.node_label||"")} ${context} · ${scope}${roles} · ${location} · ${at?new Date(at).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"?"}`.trim();const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashRecord(ghost.conversation_key);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorTrashRecord(ghost.conversation_key),140);});row.append(info);if(source==="list")appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);container.append(row);}};

  const thumbRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")==="thumbnail");

  const desktopRecords=[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const thumbPane=document.createElement("section");thumbPane.className="monitor-trash-pane monitor-trash-thumbnail-pane";thumbPane.append(makeHeader("삭제된 데스크",thumbRecords.length+desktopRecords.length,clearMonitorThumbnailRecovery));const thumbScroll=document.createElement("div");thumbScroll.className="monitor-trash-pane-scroll";

  if(desktopRecords.length){

    const desktopGrid=document.createElement("div");desktopGrid.className="monitor-trash-desktop-grid";

    for(const item of desktopRecords){

      const card=document.createElement("div");card.className="monitor-trash-desktop-card";

      const visual=document.createElement("div");visual.className="monitor-trash-desktop-card-visual";

      const desktopNumber=Math.max(1,Number(item.desktop_number??item.desktopNumber??(Number(item.index||0)+1))||1);

      const badge=document.createElement("span");badge.className="monitor-desktop-number-badge monitor-trash-desktop-number";badge.textContent=`D${desktopNumber}`;

      const thumbnail=String(item.thumbnail||item.thumbnailDataUri||"");

      if(thumbnail){const image=document.createElement("img");image.className="monitor-trash-desktop-card-image";image.src=thumbnail;image.alt="";visual.append(image);}

      else{const placeholder=document.createElement("span");placeholder.className="monitor-trash-desktop-placeholder";placeholder.textContent="미리보기 없음";visual.append(placeholder);}

      visual.append(badge);

      const actions=document.createElement("div");actions.className="monitor-trash-desktop-card-actions";

      const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorTrashedDesktop(item.id,restore);});

      const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedDesktop(item.id);});

      actions.append(restore,del);card.append(visual,actions);desktopGrid.append(card);

    }

    thumbScroll.append(desktopGrid);

  }

  renderTrashRows("thumbnail",thumbScroll);thumbPane.append(thumbScroll);

  let listRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")!=="thumbnail").sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const combined=[...listRecords.map((x)=>({kind:"trash",item:x,at:Number(x?.trashed_at_ms||0)})),...items.map((x)=>({kind:"closed",item:x,at:Number(x?.closed_at_ms||x?.captured_at_ms||0)}))].sort((a,b)=>b.at-a.at);

  const kept=combined.slice(0,20), dropped=combined.slice(20), keptKeys=new Set(kept.map((x)=>String(x.item?.conversation_key||"")));

  if(dropped.length){const dropKeys=new Set(dropped.map((x)=>String(x.item?.conversation_key||"")).filter(Boolean));for(const key of dropKeys){monitorTrashRecords.delete(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);monitorTrashedConversationKeys.add(key);}monitorRebootSnapshot={...monitorRebootSnapshot,items:(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!dropKeys.has(String(x?.conversation_key||"")))};chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot});monitorPublishSharedRebootSnapshot();monitorGhostPersist(true);persistMonitorTrashedNodes();}

  listRecords=listRecords.filter((x)=>keptKeys.has(String(x?.conversation_key||"")));

  const visibleItems=kept.filter((x)=>x.kind==="closed").map((x)=>x.item);

  const convoCount=listRecords.length+visibleItems.length;

  const snapItems=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!monitorTrashedConversationKeys.has(String(x?.conversation_key||"")));

  const full=document.createElement("button");full.type="button";full.className="monitor-detached-restore monitor-recovery-full";full.textContent=`전체 복원${convoCount?` (${convoCount})`:""}`;full.disabled=!convoCount||monitorRebootRestoreActive;full.title="삭제된 노드 복구 목록 전체 복원";full.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorAllRecovery(full,listRecords,visibleItems);});

  const reboot=document.createElement("button");reboot.type="button";reboot.className="monitor-detached-restore monitor-recovery-full";reboot.textContent=`재부팅 복원${snapItems.length?` (${snapItems.length})`:""}`;reboot.disabled=!snapItems.length||monitorRebootRestoreActive;reboot.title="재부팅 전 저장된 대화만 복원";reboot.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorRebootSnapshot(reboot);});

  const convoPane=document.createElement("section");convoPane.className="monitor-trash-pane monitor-trash-conversation-pane";convoPane.append(makeHeader("삭제된 노드",convoCount,clearMonitorConversationRecovery,[full,reboot]));const convoScroll=document.createElement("div");convoScroll.className="monitor-trash-pane-scroll";

  if(listRecords.length)renderTrashRows("list",convoScroll);

  if(!visibleItems.length&&!listRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";convoScroll.append(empty);}

  for(const ghost of visibleItems){const row=document.createElement("div");row.className="monitor-closed-conversation-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost);const created=Number(ghost?.first_seen_ms||0),closed=Number(ghost?.closed_at_ms||ghost?.captured_at_ms||0),rec=monitorContextTitleRecord(String(ghost?.conversation_key||""));const displayContext=(rec.manual_locked&&rec.manual_title)||rec.context_title||ghost.meaningful_title||context;const source=ghost.recovery_source||"일반 종료";const fmtDateTime=(ms)=>ms?new Date(ms).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).replace(/\. /g,".").replace(/\.$/,""):"?";const fmtTime=(ms)=>ms?new Date(ms).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false}):"?";const sameDay=created&&closed&&new Date(created).toDateString()===new Date(closed).toDateString();info.textContent=`${location} · ${displayContext} · ${fmtDateTime(created)} - ${sameDay?fmtTime(closed):fmtDateTime(closed)}`;info.title=`이전 위치 ${location} · ${source}`;const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";const restoring=monitorDetachedRestorePending.has(String(ghost?.conversation_key||""));restore.textContent=restoring?"복구 중…":"복구";restore.disabled=restoring;restore.addEventListener("click",(event)=>{event.stopPropagation();void restoreMonitorDetachedTask(ghost,restore);});row.addEventListener("contextmenu",(event)=>{event.preventDefault();event.stopPropagation();const existing=row.querySelector(".monitor-recovery-details");if(existing){existing.remove();return;}panel.querySelectorAll(".monitor-recovery-details").forEach((node)=>node.remove());const detail=document.createElement("div");detail.className="monitor-recovery-details";const key=String(ghost?.conversation_key||"");for(const [label,value] of [["이전 위치",location],["제목",displayContext],["복구 출처",source],["생성",created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"],["소멸",closed?new Date(closed).toLocaleString("ko-KR"):"알 수 없음"],["프로필",ghost.profile_id||"-"],["conversationKey",key||"-"]]){const line=document.createElement("div");line.className="monitor-recovery-detail-line";const k=document.createElement("b");k.textContent=label;const v=document.createElement("span");v.textContent=String(value);line.append(k,v);detail.append(line);}row.append(detail);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(event)=>{event.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorRecoveryRecord(ghost.conversation_key),140);});row.append(info);appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);convoScroll.append(row);}

  const contextRows = new Map([...convoScroll.querySelectorAll('.monitor-closed-conversation-row[data-recovery-key]')]
    .map(row => [row.dataset.recoveryKey, row]));
  for (const ghost of visibleItems) {
    const row = contextRows.get(String(ghost?.conversation_key || ''));
    if (row) row.append(createMonitorContextContinueButton(ghost));
  }
  const recoveryRowsByKey=new Map([...convoScroll.querySelectorAll(".monitor-closed-conversation-row[data-recovery-key]")].map((row)=>[String(row.dataset.recoveryKey||""),row]));for(const entry of kept){const key=String(entry?.item?.conversation_key||"");const row=recoveryRowsByKey.get(key);if(row)convoScroll.append(row);}convoPane.append(convoScroll);panel.append(convoPane,thumbPane);return panel;

}
//@@FN_END:renderMonitorClosedConversationRecoveryPanel

//@@FN_START:renderVirtualDesktops
function renderVirtualDesktops(state) {

  const reportedHostTitle = String(state?.hostWindowTitle || "").trim();

  if (reportedHostTitle && reportedHostTitle !== monitorLocalHostWindowTitle) monitorLocalHostWindowTitle = reportedHostTitle;

  const desktopIds = Array.isArray(state?.desktopIds) ? state.desktopIds : [];

  const count = Math.max(1, Number(state?.count) || desktopIds.length || 1);

  const currentIndex = Math.min(Math.max(0, Number(state?.currentIndex) || 0), Math.max(0, count - 1));

  const currentDesktopId = desktopIds[currentIndex] || null;

  const reportedHostId = typeof state?.hostDesktopId === "string" && desktopIds.includes(state.hostDesktopId) ? state.hostDesktopId : null;

  const hostAmbiguous = state?.hostWindowAmbiguous === true;

  const previousCurrentDesktopId = monitorDesktopState.currentDesktopId;
  const previousHostId = monitorDesktopState.hostDesktopId;

  const hostDesktopId = hostAmbiguous ? null : (reportedHostId || (previousHostId && desktopIds.includes(previousHostId) ? previousHostId : null));

  const previousHostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  const reportedHostHwnd = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0" ? String(state.hostWindowHwnd) : null;

  const hostWindowHwnd = hostAmbiguous ? null : (reportedHostHwnd || monitorDesktopState.hostWindowHwnd || null);

  const hostWindowChanged = hostAmbiguous ? Boolean(previousHostHwnd) : Boolean(reportedHostHwnd && reportedHostHwnd !== previousHostHwnd);

  const previousObservedId = monitorDesktopState.observedDesktopId;

  const sharedObservedId = monitorSharedSelectionReady && monitorSharedSelectedDesktopId && desktopIds.includes(monitorSharedSelectedDesktopId) ? monitorSharedSelectedDesktopId : null;

  const observedDesktopId = sharedObservedId || (previousObservedId && desktopIds.includes(previousObservedId) ? previousObservedId : (reportedHostId || currentDesktopId || desktopIds[0] || null));

  const selectedIndex = Math.max(0, desktopIds.indexOf(observedDesktopId));

  monitorDesktopState = { count, currentIndex, selectedIndex, currentDesktopId, hostDesktopId, hostWindowHwnd, observedDesktopId, desktopIds };
  // BCT node state can arrive before Native desktop topology. Once the
  // desktop IDs exist, perform only a bounded exact identity reconciliation
  // so the semantic thumbnail overlay has a verified HWND to project onto.
  scheduleMonitorBctProjectionConvergence("desktop-topology");
  if (currentDesktopId && currentDesktopId !== previousCurrentDesktopId) void ensureMonitorCurrentWallpaperSnapshot(currentDesktopId);
  if (hostDesktopId && /^\d+$/.test(String(hostWindowHwnd || "")) && String(hostWindowHwnd) !== "0") {
    void chrome.runtime.sendMessage({ type:"monitor-update-popup-runtime", desktopId:hostDesktopId, hwnd:String(hostWindowHwnd) }).catch(() => null);
    void ensureMonitorOwnFrozenSnapshot();
  }

  document.body.dataset.monitorActiveDesktopId = currentDesktopId || "";

  document.body.dataset.monitorHostDesktopId = hostDesktopId || "";

  document.body.dataset.monitorObservedDesktopId = observedDesktopId || "";

  document.body.classList.toggle("monitor-preview-remote", selectedIndex !== currentIndex);

  document.body.dataset.monitorPreviewDesktop = String(selectedIndex + 1);

  const selectedId = observedDesktopId;
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) {
    monitorDesktopThumbs.replaceChildren();
    monitorPreviewBackground.clear(selectedId || "");
    monitorWindowLayer.replaceChildren();
    monitorFrameCache.clear();
    scheduleMonitorExternalWindowDropTargets();
    if (hostWindowChanged) void monitorPublishSharedInstance("host-hwnd-changed");
    return;
  }

  try {

    syncDesktopSwitcher();
    monitorDesktopThumbs.dataset.thumbnailCardRenderer = "canonical";
    monitorDesktopThumbs.dataset.thumbnailCardRendererReason = "";
    monitorDesktopThumbs.dataset.thumbnailCardRendererError = "";

  } catch (error) {

    console.warn("DesktopWindow Monitor desktop card renderer failed; using lightweight fallback", error);

    monitorDesktopThumbs.dataset.thumbnailCardRendererError = String(error?.message || error || "RENDER_EXCEPTION");
    renderLightweightDesktopCards("RENDER_EXCEPTION");

  }

  if (desktopIds.length && monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb[data-desktop-id]").length < desktopIds.length) {

    monitorDesktopThumbs.dataset.thumbnailCardRendererError = "";
    renderLightweightDesktopCards("CARD_COUNT_MISMATCH");

  }

  if (hostWindowChanged) {

    void monitorPublishSharedInstance("host-hwnd-changed");

    monitorFrameCache.clear();

    for (const visual of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb-visual")) delete visual.dataset.monitorFrameReady;

    if (monitorInitialWindowBatchDone) {

      setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); }, 0);

    }

  }

  if (selectedId) {

    const wallpaperChangedDesktop = monitorPreviewBackground.desktopId !== String(selectedId).toLowerCase();

    applyObservedWallpaper(selectedId, wallpaperChangedDesktop);

  }

  if (selectedId && monitorWindowLayer.dataset.desktopId !== selectedId) {

    refreshObservedWindows();

  }

  if (monitorStructureOpen && document.getElementById("monitorStructureManagers")) renderMonitorStructure();

  scheduleMonitorExternalWindowDropTargets();

}
//@@FN_END:renderVirtualDesktops



//@@FN_START:restoreMonitorAllRecovery
async function restoreMonitorAllRecovery(button,listRecords,items){

  if(!button||button.disabled)return; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  try{for(const item of listRecords||[])restoreMonitorTrashRecord(item?.conversation_key);for(const item of items||[]){const temp=document.createElement("button");temp.textContent="복구";await restoreMonitorDetachedTask(item,temp);}}

  finally{button.textContent=old;button.disabled=false;refreshMonitorRecoveryMenu();}

}
//@@FN_END:restoreMonitorAllRecovery

//@@FN_START:restoreMonitorDesktopNodeSnapshots
function restoreMonitorDesktopNodeSnapshots(nodes){for(const item of Array.isArray(nodes)?nodes:[]){const key=String(item?.conversation_key||"");if(!key)continue;monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);monitorHiddenGhosts.delete(key);}persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);}
//@@FN_END:restoreMonitorDesktopNodeSnapshots

//@@FN_START:restoreMonitorDetachedTask
async function restoreMonitorDetachedTask(item, button) {

  const key=String(item?.conversation_key||"").trim();

  let profile=String(item?.profile_id||"").trim().toUpperCase();

  const nodeLabel=String(item?.node_label||"").trim();

  if(!key||!button)return {ok:false,status:"INVALID",conversationKey:key,profileId:profile,nodeLabel,error:"복구 대상 정보 없음"};

  if(button.disabled||monitorDetachedRestorePending.has(key))return {ok:false,status:"BUSY",conversationKey:key,profileId:profile,nodeLabel,error:"이미 복구 진행 중"};

  monitorDetachedRestorePending.add(key);

  button.disabled=true; const original=button.textContent; button.textContent="복구 중…";

  try{

    const preResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

    if(!preResponse?.ok)throw new Error("ACT 상태 확인 실패");

    const preState=await preResponse.json().catch(()=>null);

    if(!preState)throw new Error("ACT 상태 응답 해석 실패");

    const exactEndpoints=(Array.isArray(preState?.endpoints)?preState.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key);
    const observedProfiles=[...new Set(exactEndpoints.map((candidate)=>String(candidate?.profile_id||"").trim().toUpperCase()).filter(Boolean))];
    if(!profile){
      if(observedProfiles.length!==1)throw new Error(observedProfiles.length ? "복구 대상 Chrome 프로필이 여러 개라 자동으로 선택할 수 없음" : "복구 대상 Chrome 프로필이 ACT에 기록되어 있지 않음");
      profile=observedProfiles[0];
    }else if(observedProfiles.length&& !observedProfiles.includes(profile))throw new Error("기록의 Chrome 프로필이 ACT endpoint 기록과 다름");
    const alreadyOpen=exactEndpoints.filter((candidate)=>String(candidate?.presence_state||"").toUpperCase()==="OPEN");

    if(alreadyOpen.length>1)throw new Error("같은 대화의 OPEN endpoint가 여러 개임");    let endpoint=alreadyOpen[0]||null;

    let status=endpoint?"ALREADY_OPEN":"RESTORED";

    if(endpoint&&profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("이미 열린 대화의 Chrome 프로필이 복구 기록과 다름");

    if(!endpoint){

      const launch=await monitorNative({type:"restoreChatGptConversation",profileId:profile,conversationKey:key}).catch((error)=>({ok:false,error:String(error?.message||error)}));

      if(!launch?.ok||!launch?.launched)throw new Error(`브라우저 복구 실행 실패 · ${launch?.error||"Native Host 응답 없음"}`);

      for(let i=0;i<30&&!endpoint;i+=1){

        await new Promise((resolve)=>setTimeout(resolve,500));

        const response=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

        const state=response?.ok?await response.json().catch(()=>null):null;

        const matches=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key&&String(candidate?.presence_state||"").toUpperCase()==="OPEN");

        if(matches.length>1)throw new Error("Ambiguous OPEN endpoints after restore.");

        if(matches.length===1)endpoint=matches[0];

      }

      if(!endpoint)throw new Error("브라우저는 실행했지만 15초 안에 ACT endpoint가 등록되지 않음");

      if(profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("Restored endpoint profile mismatch.");

    }

    monitorHiddenGhosts.delete(key); monitorGhostPersist();

    if(!item?.__reboot_restore)monitorClosedConversationPickerOpen=false;

    await refreshAiMonitor();

    if(!item?.__reboot_restore)setMonitorStatus(`${nodeLabel||"대화"} 복구 완료${status==="ALREADY_OPEN"?" · 이미 열려 있음":""}`,true);

    return {ok:true,status,conversationKey:key,profileId:profile,nodeLabel,endpoint};

  }catch(error){

    const message=String(error?.message||error);

    setMonitorStatus(`${nodeLabel||"대화"} 복구 실패 · ${message}`,false);

    button.title=message;

    console.warn("DesktopWindow Monitor conversation recovery failed",{conversationKey:key,profileId:profile,nodeLabel,error:message});

    return {ok:false,status:"FAILED",conversationKey:key,profileId:profile,nodeLabel,error:message};  }finally{

    monitorDetachedRestorePending.delete(key);

    button.textContent=original; button.disabled=false;

    if(monitorLastAiState)renderWorkers(monitorLastAiState);

  }

}
//@@FN_END:restoreMonitorDetachedTask

//@@FN_START:restoreMonitorNodeChatChange
async function restoreMonitorNodeChatChange(worker,nodeState,button){

  const binding=nodeState?.nodeBinding||{}; const key=String(binding.conversation_key||nodeState?.previousConversationKey||"").trim(); const profile=String(binding.profile_id||worker?.profile_id||"").toUpperCase(); const targetDesktopId=String(binding.desktop_id||"");

  if(!key||!profile){setMonitorStatus("원래 창 복구 실패 · 원래 대화 정보 없음",false);return;}

  button.disabled=true; const oldText=button.textContent; button.textContent="…";

  try{

    const stateResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}); const state=stateResponse?.ok?await stateResponse.json():null;

    const open=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===key);

    if(open.length>1)throw new Error("원래 대화가 여러 창에 열려 있음");

    const currentEndpoint=nodeState?.endpoint||worker?.__endpoint||null;
    const targetTabId=Number(currentEndpoint?.tab_id||binding?.tab_id||0);
    if(!Number.isInteger(targetTabId)||targetTabId<=0)throw new Error("현재 탭 ID 확인 실패");
    const otherOpen=open.filter(ep=>Number(ep?.tab_id||0)!==targetTabId);
    if(otherOpen.length)throw new Error("원래 대화가 다른 탭에 이미 열려 있음");
    let endpoint=String(currentEndpoint?.conversation_key||"").trim()===key ? currentEndpoint : null;

    if(!endpoint){
      const nav=await chrome.runtime.sendMessage({type:"monitor-navigate-chat-tab",tabId:targetTabId,conversationKey:key}).catch(error=>({ok:false,error:error?.message||String(error)}));
      if(!nav?.ok)throw new Error(nav?.error||"현재 탭 복구 실패");
    }

    for(let i=0;i<24&&!endpoint;i++){
      await new Promise(r=>setTimeout(r,250));
      const rr=await actFetch(ORCHESTRATOR_MONITOR_STATE_URL,{cache:"no-store"});
      const ss=rr?.ok?await rr.json():null;
      const matches=(Array.isArray(ss?.endpoints)?ss.endpoints:[]).filter(ep=>
        String(ep?.presence_state||"").toUpperCase()==="OPEN"
        && String(ep?.conversation_key||"").trim()===key
        && Number(ep?.tab_id||0)===targetTabId
      );
      if(matches.length>1)throw new Error("복구 endpoint 중복");
      if(matches.length===1)endpoint=matches[0];
    }

    if(!endpoint)throw new Error("복구된 대화가 ACT에 등록되지 않음");

    const hwnd=endpointOsWindowHandle(endpoint); if(!hwnd)throw new Error("복구된 창 HWND 확인 실패");

    if(targetDesktopId)await moveMonitorWindowToDesktop(hwnd,"",targetDesktopId);

    const next={...binding,conversation_key:key,profile_id:profile,title:String(endpoint?.title||binding.title||""),window_instance_id:String(endpoint?.window_instance_id||endpoint?.metadata?.window_instance_id||binding.window_instance_id||"")};

    monitorStoreNodeBinding(next,endpoint); await refreshAiMonitor(); setMonitorStatus(`${next.node_label||"노드"} 복구 · 현재 탭을 원래 챗으로 되돌림`,true);

  }catch(error){setMonitorStatus(`원래 챗 복구 실패 · ${error?.message||error}`,false);}finally{button.textContent=oldText;button.disabled=false;}

}
//@@FN_END:restoreMonitorNodeChatChange

//@@FN_START:restoreMonitorRebootSnapshot
async function restoreMonitorRebootSnapshot(button) {

  const items=[...(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[])];

  if(!items.length||monitorRebootRestoreActive||!button)return {ok:false,status:"IGNORED",results:[]};

  monitorRebootRestoreActive=true; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  const results=[];

  try{    for(const item of items){

      const key=String(item?.conversation_key||"").trim(); if(!key)continue;

      monitorRebootRestorePendingKeys.add(key);

      const temp=document.createElement("button");temp.textContent="복구";

      const result=await restoreMonitorDetachedTask({...item,__reboot_restore:true},temp);

      results.push(result||{ok:false,status:"FAILED",conversationKey:key,error:"복구 결과 없음"});

      if(result?.ok){

        const r=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null),state=r?.ok?await r.json().catch(()=>null):null;

        const ep=(Array.isArray(state?.endpoints)?state.endpoints:[]).find((x)=>String(x?.conversation_key||"").trim()===key&&String(x?.presence_state||"").toUpperCase()==="OPEN");

        if(ep){

          const resolved=monitorExactConversationWindow(key,state,Date.now(),ep);

          const hwnd=String(resolved?.location?.hwnd||endpointOsWindowHandle(ep)||"").trim();

          const target=monitorDesktopState.desktopIds[Math.max(0,Number(item.desktop||1)-1)]||String(item.desktop_id||"");

          if(/^\d+$/.test(hwnd)&&hwnd!=="0"&&target){

            const moved=await monitorNative({type:"moveWindowToDesktop",hwnd,desktopId:target}).catch(()=>null);

            if(moved&&moved.ok===false)result.positionWarning=String(moved.error||"원래 데스크톱 이동 실패");

          }

        }

      }

      monitorRebootRestorePendingKeys.delete(key); await refreshAiMonitor();

    }

    const failed=results.filter((row)=>!row?.ok);

    const opened=results.filter((row)=>row?.ok&&row?.status==="RESTORED").length;

    const existing=results.filter((row)=>row?.ok&&row?.status==="ALREADY_OPEN").length;

    if(failed.length){

      const names=failed.slice(0,3).map((row)=>row?.nodeLabel||String(row?.conversationKey||"").slice(0,8)).join(", ");

      setMonitorStatus(`전체 복원 일부 실패 · 새로 ${opened} · 이미 열림 ${existing} · 실패 ${failed.length}${names?` · ${names}`:""}`,false);

    }else setMonitorStatus(`이전 상태 전체 복원 완료 · 새로 ${opened} · 이미 열림 ${existing}`,true);

    return {ok:failed.length===0,status:failed.length?"PARTIAL":"COMPLETE",results};  }catch(error){

    setMonitorStatus(`전체 복원 실패 · ${error?.message||error}`,false);

    return {ok:false,status:"FAILED",error:String(error?.message||error),results};

  }finally{

    for(const item of items)monitorRebootRestorePendingKeys.delete(String(item?.conversation_key||""));

    monitorRebootRestoreActive=false;

    const expected=items.filter((item)=>String(item?.conversation_key||"").trim()).length;

    const allVerified=results.length===expected&&results.every((row)=>row?.ok);

    button.disabled=false; button.textContent=old;

    if(monitorLastAiState){if(allVerified)monitorCaptureRebootSnapshot(monitorLastAiState);renderWorkers(monitorLastAiState);}

  }

}
//@@FN_END:restoreMonitorRebootSnapshot

//@@FN_START:restoreMonitorTrashRecord
function restoreMonitorTrashRecord(key){key=String(key||"");monitorTrashedConversationKeys.delete(key);monitorTrashRecords.delete(key);persistMonitorTrashedNodes();if(monitorLastAiState)renderWorkers(monitorLastAiState);refreshMonitorRecoveryMenu();}
//@@FN_END:restoreMonitorTrashRecord

//@@FN_START:restoreMonitorTrashedDesktop
async function restoreMonitorTrashedDesktop(id,button){const item=monitorTrashedDesktops.get(String(id||""));if(!item)return;if(button)button.disabled=true;try{const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:item.hwnds||[]});if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");restoreMonitorDesktopNodeSnapshots(item.nodes);deleteMonitorTrashedDesktop(id);renderVirtualDesktops(result);}catch(error){setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false);if(button)button.disabled=false;}}
//@@FN_END:restoreMonitorTrashedDesktop

//@@FN_START:scheduleMonitorStartupRecovery
function scheduleMonitorStartupRecovery() {

  if (monitorStartupRecoveryUsed || monitorStartupRecoveryTimer) return;

  if (monitorStartupStateConfirmed && monitorStartupSharedRuntimeConfirmed && monitorStartupEndpointFreshConfirmed) return;

  monitorStartupRecoveryUsed = true;

  monitorStartupRecoveryTimer = setTimeout(async () => {

    monitorStartupRecoveryTimer = null;

    try { await monitorSyncSharedState("startup-settle", false); } catch (_) {}

    try { await refreshActHealth(); } catch (_) {}

    try { await refreshAiMonitor(); } catch (_) {}

  }, MONITOR_STARTUP_SETTLE_MS);

}
//@@FN_END:scheduleMonitorStartupRecovery

//@@FN_START:selectVirtualDesktopPreview
function selectVirtualDesktopPreview(index) {

  const bounded = Math.min(Math.max(0, index), monitorDesktopState.count - 1);

  const changed = bounded !== monitorDesktopState.selectedIndex;

  monitorDesktopState.selectedIndex = bounded;

  const desktopId = monitorDesktopState.desktopIds[bounded] || null;

  monitorSharedSelectedDesktopId = desktopId || "";

  monitorDesktopState.observedDesktopId = desktopId;

  publishMonitorSharedSelection();

  document.body.dataset.monitorObservedDesktopId = desktopId || "";

  if (changed) flashDesktopTransition();

  document.body.classList.toggle("monitor-preview-remote", bounded !== monitorDesktopState.currentIndex);

  document.body.dataset.monitorPreviewDesktop = String(bounded + 1);

  if (changed && desktopId) {
    primeSelectedDesktopPreview(desktopId);
    void applyObservedWallpaper(desktopId, true);
  }

  window.dispatchEvent(new CustomEvent("desktopwindow-monitor-preview", {

    detail: { index: bounded, desktopId, currentIndex: monitorDesktopState.currentIndex }

  }));

  renderVirtualDesktops({

    count: monitorDesktopState.count,

    currentIndex: monitorDesktopState.currentIndex,

    desktopIds: monitorDesktopState.desktopIds

  });

  // Selecting a preview does not change Windows topology.  Do not invalidate
  // other desktop captures here: rapid D1/D2 navigation used to cancel valid
  // in-flight card frames and temporarily blank their accepted pixels.
  void refreshObservedWindows();
  void refreshSelectedThumb();

}
//@@FN_END:selectVirtualDesktopPreview

//@@FN_START:showDeletedDesktopTrashUndo
function showDeletedDesktopTrashUndo(snapshot) {

  monitorDeletedDesktopUndo={...snapshot}; monitorDeletedDesktopUndoExpiresAt=Date.now()+MONITOR_DESKTOP_TRASH_UNDO_MS; updateDeletedDesktopTrashUi();

}
//@@FN_END:showDeletedDesktopTrashUndo

//@@FN_START:showDesktopUndo
function showDesktopUndo(snapshot) {

  pushDesktopUndoSnapshot(snapshot);

  updateDesktopUndoUi();

}
//@@FN_END:showDesktopUndo

//@@FN_START:storeMonitorTrashedDesktop
function storeMonitorTrashedDesktop(snapshot){const id=String(snapshot?.desktopId||`desktop-${Date.now()}`);monitorTrashedDesktops.set(id,{...snapshot,id,trashed_at_ms:Date.now()});persistMonitorTrashedDesktops();refreshMonitorRecoveryMenu();}
//@@FN_END:storeMonitorTrashedDesktop

//@@FN_START:syncDesktopSwitcher
function syncDesktopSwitcher() {
  const createdDesktopIds = [];

  const existing = new Map([...monitorDesktopThumbs.children].filter(button => !button.dataset.deletedPlaceholder).map(button => [button.dataset.desktopId, button]));

  for (let index = 0; index < monitorDesktopState.count; index += 1) {

    const desktopId = monitorDesktopState.desktopIds[index] || `index-${index}`;

    let button = existing.get(desktopId);

    if (!button) {

      button = document.createElement("button"); button.type = "button"; button.className = "monitor-desktop-thumb"; button.dataset.desktopId = desktopId;

      const visual = document.createElement("span"); visual.className = "monitor-desktop-thumb-visual"; visual.dataset.desktopId = desktopId;

      const label = document.createElement("span"); label.className = "monitor-desktop-thumb-label";

      const desktopBadge = document.createElement("span"); desktopBadge.className = "monitor-desktop-number-badge";

      const labelText = document.createElement("span"); labelText.className = "monitor-desktop-label-text";

      const minimizedNodes = document.createElement("span"); minimizedNodes.className = "monitor-desktop-minimized-nodes"; minimizedNodes.hidden = true;

      label.append(desktopBadge, labelText, minimizedNodes);
      monitorAttachDesktopManagementControl(label, desktopId);

      button.append(visual, label);

      button.addEventListener("pointerdown", beginMonitorDesktopPointerDrag);

      button.addEventListener("click", (event) => {

        if (button.dataset.monitorDropSuppressClick === "1") { event.preventDefault(); event.stopPropagation(); return; }

        selectVirtualDesktopPreview(Number(button.dataset.index || 0));

      });

      button.addEventListener("dblclick", async (event) => {

        event.preventDefault();

        const index = Number(button.dataset.index || 0);

        button.classList.add("monitor-desktop-switch-pending");

        try {

          const result = await monitorNative({ type: "switchVirtualDesktop", index });

          if (!result?.ok) throw new Error(result?.error || "데스크톱 전환 실패");

          renderVirtualDesktops(result);

          selectVirtualDesktopPreview(index);

        } catch (error) { setMonitorStatus(`데스크톱 전환 실패 · ${error?.message || error}`, false); }

        finally { setTimeout(() => button.classList.remove("monitor-desktop-switch-pending"), 350); }

      });

      bindDesktopDropTarget(button);

      monitorDesktopThumbs.append(button);
      createdDesktopIds.push(desktopId);

    }

    button.dataset.index = String(index); button.classList.toggle("selected", index === monitorDesktopState.selectedIndex); button.classList.toggle("current", index === monitorDesktopState.currentIndex);
    monitorAttachDesktopManagementControl(button.querySelector(".monitor-desktop-thumb-label"), desktopId);

    const displayIndex = monitorDeletedDesktopUndo && Date.now() < monitorDeletedDesktopUndoExpiresAt && index >= Number(monitorDeletedDesktopUndo.index) ? index + 1 : index;

    const labelText=button.querySelector(".monitor-desktop-label-text"); if(labelText)labelText.textContent=`데스크톱 ${displayIndex + 1}`; const desktopBadge=button.querySelector(".monitor-desktop-number-badge"); if(desktopBadge)desktopBadge.textContent=`D${displayIndex + 1}`;

    existing.delete(desktopId);

  }

  for (const stale of existing.values()) { const key=String(stale.dataset.hwnd||""); stale.parentElement?.querySelectorAll(".monitor-window-pause-overlay").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();}); stale.remove(); }

  for (const stalePlaceholder of [...monitorDesktopThumbs.querySelectorAll(".monitor-desktop-trash-placeholder")]) stalePlaceholder.remove();

  if (monitorDeletedDesktopUndo && Date.now() < monitorDeletedDesktopUndoExpiresAt) {

    const placeholder=document.createElement("div"); placeholder.className="monitor-desktop-thumb monitor-desktop-trash-placeholder"; placeholder.dataset.deletedPlaceholder="1";

    const undo=document.createElement("button"); undo.type="button"; undo.className="monitor-desktop-trash-placeholder-undo"; undo.title="삭제한 데스크톱 되돌리기"; undo.setAttribute("aria-label","삭제한 데스크톱 되돌리기");

    const icon=document.createElement("span"); icon.className="monitor-desktop-trash-placeholder-icon"; icon.textContent="↶";

    const countdown=document.createElement("span"); countdown.className="monitor-desktop-trash-placeholder-countdown"; countdown.textContent=`${Math.max(0,Math.ceil((monitorDeletedDesktopUndoExpiresAt-Date.now())/1000))}s`;

    undo.append(icon,countdown); undo.addEventListener("click", undoDeletedDesktopTrash); placeholder.append(undo);

    const at=Math.max(0,Math.min(Number(monitorDeletedDesktopUndo.index)||0,monitorDesktopThumbs.children.length));

    monitorDesktopThumbs.insertBefore(placeholder,monitorDesktopThumbs.children[at]||null);

  }

  // Background identity is the desktop GUID, not the Monitor popup's owning
  // desktop. Every new canonical card enters the same bottom-layer port used
  // by the lightweight renderer; V2 coalesces startup overlap per tile.
  if (createdDesktopIds.length) requestAnimationFrame(() => {
    const renderer = globalThis.MonitorDesktopThumbnailV2;
    for (const desktopId of createdDesktopIds) {
      const tile = [...monitorDesktopThumbs.children].find((item) => (
        String(item.dataset.desktopId || "") === String(desktopId)
      ));
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (visual?.isConnected) void renderer?.refreshBackground?.(visual, desktopId).catch(() => null);
    }
  });
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("summary") !== false) syncMonitorMinimizedNodeBadges();
  requestAnimationFrame(syncMonitorDesktopScrollArrows);

}
//@@FN_END:syncDesktopSwitcher

//@@FN_START:syncMonitorDesktopNumberBadge
function syncMonitorDesktopNumberBadge(img, hwnd) {

  if (!img?.parentElement) return;

  const key=String(hwnd||""), state=monitorLastAiState;

  let badge=[...img.parentElement.querySelectorAll(".monitor-window-desktop-badge")].find((node)=>node.dataset.hwnd===key);
  if(img.classList.contains("monitor-desktop-thumb-window")){
    badge?.remove();
    // Render once after the full Native frame is reconciled. Re-entering the
    // renderer here used to apply the window's physical offset to its child
    // badge a second time and made the result depend on image iteration order.
    return;
  }

  if(!state){badge?.remove();return;}

  const unique=monitorBadgeNodeNumbersForHwnd(key,state);

  if(!unique.length){ badge?.remove(); return; }

  if(!badge){badge=document.createElement("span");badge.className="monitor-node-number-badge monitor-window-desktop-badge";badge.dataset.hwnd=key;img.parentElement.append(badge);}

  badge.textContent=unique.length>1?unique.join("/"):String(unique[0]);

  badge.title=unique.length>1?`ACT 탭 노드 ${unique.join(" / ")}`:`ACT 노드 ${unique[0]}`;

  badge.style.left=img.style.left;badge.style.top=img.style.top;badge.style.zIndex=String(Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)));

}
//@@FN_END:syncMonitorDesktopNumberBadge

//@@FN_START:syncMonitorDesktopScrollArrows
function syncMonitorDesktopScrollArrows(){const max=Math.max(0,monitorDesktopScrollViewport.scrollWidth-monitorDesktopScrollViewport.clientWidth);const overflow=max>4;monitorDesktopScrollLeft.hidden=!overflow;monitorDesktopScrollRight.hidden=!overflow;if(!overflow)return;monitorDesktopScrollLeft.disabled=monitorDesktopScrollViewport.scrollLeft<=2;monitorDesktopScrollRight.disabled=monitorDesktopScrollViewport.scrollLeft>=max-2;}
//@@FN_END:syncMonitorDesktopScrollArrows

//@@FN_START:syncMonitorPanelToDesktopSwitcher
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
//@@FN_END:syncMonitorPanelToDesktopSwitcher

//@@FN_START:trashMonitorConversationKeys
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
//@@FN_END:trashMonitorConversationKeys

//@@FN_START:undoDeletedDesktopTrash
async function undoDeletedDesktopTrash() {

  const snapshot=monitorDeletedDesktopUndo; if(!snapshot||Date.now()>=monitorDeletedDesktopUndoExpiresAt)return;

  const button=monitorDesktopThumbs.querySelector(".monitor-desktop-trash-placeholder-undo"); if(button)button.disabled=true;

  try {

    const beforeIds=new Set(monitorDesktopState.desktopIds);

    const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:snapshot.hwnds});

    if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");

    const resultIds=Array.isArray(result.desktopIds)?result.desktopIds:[];

    const restoredId=resultIds.find((id)=>!beforeIds.has(id))||resultIds[resultIds.length-1]||null;

    monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; clearTimeout(monitorDeletedDesktopUndoTimer);

    restoreMonitorDesktopNodeSnapshots(snapshot.nodes);

    if(snapshot.desktopId) deleteMonitorTrashedDesktop(snapshot.desktopId);

    monitorDesktopState.observedDesktopId=restoredId; renderVirtualDesktops(result); if(restoredId)settleNewDesktopWallpaper(restoredId).catch(()=>{});

  } catch(error) { setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false); if(button)button.disabled=false; }

}
//@@FN_END:undoDeletedDesktopTrash

//@@FN_START:updateDeletedDesktopTrashUi
function updateDeletedDesktopTrashUi() {

  clearTimeout(monitorDeletedDesktopUndoTimer);

  if (!monitorDeletedDesktopUndo) return;

  const now=Date.now();

  if (now >= monitorDeletedDesktopUndoExpiresAt) { monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; syncDesktopSwitcher(); return; }

  syncDesktopSwitcher();

  monitorDeletedDesktopUndoTimer=setTimeout(updateDeletedDesktopTrashUi,250);

}
//@@FN_END:updateDeletedDesktopTrashUi

//@@FN_START:updateDesktopUndoUi
function updateDesktopUndoUi() {

  const now = Date.now();

  expireDesktopUndoSession(now);

  clearTimeout(monitorUndoTimer);

  const latest = monitorRecoveryUndoSession.peek(now);

  monitorDesktopUndo.hidden = !latest;

  if (!latest) return;

  const seconds = Math.max(0, Math.ceil(monitorRecoveryUndoSession.remainingMs(now) / 1000));

  monitorDesktopUndoCountdown.textContent = `${seconds}s`;

  const label = latest.kind === "window-move" ? "window move" : latest.kind === "window-copy" ? "window copy" : latest.kind === "create-move" ? "new desktop move" : latest.kind === "create-copy" ? "new desktop copy" : `desktop ${Number(latest.index) + 1}`;

  monitorDesktopUndoButton.title = `Undo ${label} - ${seconds}s left`;

  monitorUndoTimer = setTimeout(updateDesktopUndoUi, Math.min(250, Math.max(50, monitorRecoveryUndoSession.remainingMs(now))));

}
//@@FN_END:updateDesktopUndoUi

//@@FN_START:updateMonitorBctNodePointerDrag
function updateMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  if (!drag.active && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 7) return;
  if (!drag.active) {
    drag.active = true;
    monitorBctSuppressScopeClickUntil = Date.now() + 1000;
    monitorBctDraggedNodeKey = drag.node.conversationKey;
    monitorBctSuppressedClickKey = monitorBctNodeSelectionKey(drag.node);
    drag.row.classList.add("is-dragging");
    document.documentElement.classList.add("monitor-bct-node-drag-active");
    monitorWorkers?.querySelectorAll?.(".monitor-bct-node-list")
      .forEach((list) => list.classList.add("monitor-bct-node-list-available"));
    monitorBctDragGhost?.remove?.();
    monitorBctDragGhost = createMonitorNodeDragGhost(drag.row, event);
    monitorBctDragGhost.classList.add("monitor-bct-node-drag-ghost");
    monitorBctDragGhost.textContent = `${drag.node.nodeLabel || "N?"}  ${drag.node.title || "ChatGPT"}`;
    const previewToken = `${Date.now()}-${event.pointerId}-${++monitorBctNativePreviewSequence}`;
    monitorBctNativePreviewToken = previewToken;
    void monitorNative({
      type:"monitorDragPreviewStart",
      token:previewToken,
      label:monitorBctDragGhost.textContent,
      sourceHwnd:String(monitorDesktopState?.hostWindowHwnd || ""),
    }).catch(() => {}); // An older installed Host keeps the DOM-only preview.
  }
  event.preventDefault();
  moveMonitorNodeDragGhost(monitorBctDragGhost, event.clientX, event.clientY);
  clearMonitorBctNodeDropFeedback();
  drag.drop = monitorBctNodeDropAt(event.clientX, event.clientY, drag.node.conversationKey);
}
//@@FN_END:updateMonitorBctNodePointerDrag

//@@FN_START:updateMonitorDesktopPointerDrag
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
//@@FN_END:updateMonitorDesktopPointerDrag

//@@FN_START:updateMonitorNodeTrashUndoUi
function updateMonitorNodeTrashUndoUi(){

  clearTimeout(monitorNodeTrashUndoTimer); const now=Date.now(); monitorNodeTrash.hidden=false;

  if(!monitorNodeTrashUndoSnapshot||now>=monitorNodeTrashUndoExpiresAt){monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;monitorNodeTrashUndo.hidden=true;return;}

  monitorNodeTrashUndo.hidden=false; const seconds=Math.max(0,Math.ceil((monitorNodeTrashUndoExpiresAt-now)/1000)); monitorNodeTrashUndoCountdown.textContent=`${seconds}s`;

  monitorNodeTrashUndoTimer=setTimeout(updateMonitorNodeTrashUndoUi,250);

}
//@@FN_END:updateMonitorNodeTrashUndoUi

//@@FN_START:updateMonitorWindowPointerDrag
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
//@@FN_END:updateMonitorWindowPointerDrag

//@@FN_START:updateMonitorWorkerRowPointerDrag
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
//@@FN_END:updateMonitorWorkerRowPointerDrag
