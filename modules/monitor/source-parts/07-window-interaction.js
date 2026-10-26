/*@@MONITOR_FUNCTION:syncMonitorThumbnailTabBadges@@*/
/*@@MONITOR_FUNCTION:syncMonitorBctNodeLocationLabels@@*/
let monitorThumbnailProjectionPublishSignature="";
let monitorThumbnailProjectionPublishTimer=0;
/*@@MONITOR_FUNCTION:monitorThumbnailProjectionRuntimeDiagnostics@@*/
/*@@MONITOR_FUNCTION:scheduleMonitorThumbnailProjectionReceipt@@*/
/*@@MONITOR_FUNCTION:syncMonitorAllDesktopThumbnailNodeBadges@@*/

let monitorWindowPointerDrag = null;

let monitorDesktopPointerDrag = null;

let monitorCreateDesktopDropBusy = false;

let monitorCreateDesktopDropConsumedUntil = 0;

/*@@MONITOR_FUNCTION:syncMonitorNativeZOrder@@*/

/*@@MONITOR_FUNCTION:monitorSelectedEntries@@*/

/*@@MONITOR_FUNCTION:monitorProfileIdForHwnd@@*/

/*@@MONITOR_FUNCTION:moveMonitorWindowSet@@*/

/*@@MONITOR_FUNCTION:snapshotAllChromeHwnds@@*/

/*@@MONITOR_FUNCTION:waitForNewChromeHwnd@@*/

/*@@MONITOR_FUNCTION:cloneMonitorWindowSet@@*/

/*@@MONITOR_FUNCTION:performMonitorWindowDrop@@*/

/*@@MONITOR_FUNCTION:createMonitorNodeDragGhost@@*/

/*@@MONITOR_FUNCTION:moveMonitorNodeDragGhost@@*/

/*@@MONITOR_FUNCTION:destroyMonitorNodeDragGhost@@*/

/*@@MONITOR_FUNCTION:monitorTrashDropTargetAt@@*/

/*@@MONITOR_FUNCTION:clearMonitorTrashDropTarget@@*/

/*@@MONITOR_FUNCTION:monitorConversationKeysForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorTrashRecordForKey@@*/

/*@@MONITOR_FUNCTION:persistMonitorTrashedNodes@@*/

/*@@MONITOR_FUNCTION:updateMonitorNodeTrashUndoUi@@*/

/*@@MONITOR_FUNCTION:trashMonitorConversationKeys@@*/

/*@@MONITOR_FUNCTION:refreshMonitorRecoveryMenu@@*/

/*@@MONITOR_FUNCTION:restoreMonitorTrashRecord@@*/

/*@@MONITOR_FUNCTION:deleteMonitorTrashRecord@@*/

/*@@MONITOR_FUNCTION:deleteMonitorRecoveryRecord@@*/

/*@@MONITOR_FUNCTION:monitorDeletedDesktopLoadImage@@*/

/*@@MONITOR_FUNCTION:monitorDeletedDesktopDrawCover@@*/

/*@@MONITOR_FUNCTION:monitorFreezeDesktopThumbnail@@*/

/*@@MONITOR_FUNCTION:persistMonitorTrashedDesktops@@*/

/*@@MONITOR_FUNCTION:monitorDesktopNodeSnapshots@@*/

/*@@MONITOR_FUNCTION:restoreMonitorDesktopNodeSnapshots@@*/

/*@@MONITOR_FUNCTION:storeMonitorTrashedDesktop@@*/

/*@@MONITOR_FUNCTION:deleteMonitorTrashedDesktop@@*/

/*@@MONITOR_FUNCTION:restoreMonitorTrashedDesktop@@*/

/*@@MONITOR_FUNCTION:clearMonitorThumbnailRecovery@@*/

/*@@MONITOR_FUNCTION:clearMonitorConversationRecovery@@*/

monitorNodeTrashUndoButton.addEventListener("click",()=>{const snap=monitorNodeTrashUndoSnapshot;if(!snap||Date.now()>=monitorNodeTrashUndoExpiresAt)return;for(const key of snap.keys||[]){monitorTrashedConversationKeys.delete(String(key));monitorTrashRecords.delete(String(key));}persistMonitorTrashedNodes();monitorNodeTrashUndoSnapshot=null;monitorNodeTrashUndoExpiresAt=0;updateMonitorNodeTrashUndoUi();if(monitorLastAiState)renderWorkers(monitorLastAiState);});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_TRASHED_NODES_KEY,MONITOR_TRASH_RECORDS_KEY,MONITOR_TRASHED_NOTES_KEY,MONITOR_TRASHED_DESKTOPS_KEY],(data)=>{for(const key of Array.isArray(data?.[MONITOR_TRASHED_NODES_KEY])?data[MONITOR_TRASHED_NODES_KEY]:[])monitorTrashedConversationKeys.add(String(key));for(const item of Array.isArray(data?.[MONITOR_TRASH_RECORDS_KEY])?data[MONITOR_TRASH_RECORDS_KEY]:[])if(item?.conversation_key)monitorTrashRecords.set(String(item.conversation_key),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_NOTES_KEY])?data[MONITOR_TRASHED_NOTES_KEY]:[])if(item?.id)monitorTrashedNotes.set(String(item.id),item);for(const item of Array.isArray(data?.[MONITOR_TRASHED_DESKTOPS_KEY])?data[MONITOR_TRASHED_DESKTOPS_KEY]:[])if(item?.id)monitorTrashedDesktops.set(String(item.id),item);if(monitorLastAiState)renderWorkers(monitorLastAiState);});

/*@@MONITOR_FUNCTION:monitorDesktopDropTargetAt@@*/

/*@@MONITOR_FUNCTION:monitorCreateDesktopDropTargetAt@@*/

/*@@MONITOR_FUNCTION:clearMonitorDesktopDropTargets@@*/

let monitorWorkerRowPointerDrag = null;

let monitorWorkerRowSuppressClickUntil = 0;

/*@@MONITOR_FUNCTION:monitorWorkerRowOrderTargetAt@@*/

/*@@MONITOR_FUNCTION:clearMonitorWorkerOrderTargets@@*/

/*@@MONITOR_FUNCTION:beginMonitorWorkerRowPointerDrag@@*/

/*@@MONITOR_FUNCTION:updateMonitorWorkerRowPointerDrag@@*/

/*@@MONITOR_FUNCTION:finishMonitorWorkerRowPointerDrag@@*/

/*@@MONITOR_FUNCTION:cancelMonitorWorkerRowPointerDrag@@*/

/*@@MONITOR_FUNCTION:beginMonitorWindowPointerDrag@@*/

/*@@MONITOR_FUNCTION:updateMonitorWindowPointerDrag@@*/

/*@@MONITOR_FUNCTION:finishMonitorWindowPointerDrag@@*/

/*@@MONITOR_FUNCTION:cancelMonitorWindowPointerDrag@@*/

/*@@MONITOR_FUNCTION:beginMonitorDesktopPointerDrag@@*/

/*@@MONITOR_FUNCTION:updateMonitorDesktopPointerDrag@@*/

/*@@MONITOR_FUNCTION:finishMonitorDesktopPointerDrag@@*/

/*@@MONITOR_FUNCTION:cancelMonitorDesktopPointerDrag@@*/

document.addEventListener("pointermove", updateMonitorWindowPointerDrag, true);

document.addEventListener("pointerup", finishMonitorWindowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWindowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointerup", finishMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorWorkerRowPointerDrag, true);

document.addEventListener("pointermove", updateMonitorDesktopPointerDrag, true);

document.addEventListener("pointerup", finishMonitorDesktopPointerDrag, true);

document.addEventListener("pointercancel", cancelMonitorDesktopPointerDrag, true);

/*@@MONITOR_FUNCTION:invalidateMonitorDesktopFrames@@*/

/*@@MONITOR_FUNCTION:moveMonitorWindowToDesktop@@*/

/*@@MONITOR_FUNCTION:getDesktopBrowserWindowHandles@@*/

/*@@MONITOR_FUNCTION:refreshDesktopDropThumbnails@@*/

/*@@MONITOR_FUNCTION:createDesktopForDrop@@*/

/*@@MONITOR_FUNCTION:bindDesktopDropTarget@@*/

/*@@MONITOR_FUNCTION:decorateMonitorThumbnailWindows@@*/

/*@@MONITOR_FUNCTION:refreshDesktopThumb@@*/

/*@@MONITOR_FUNCTION:monitorThumbnailBackgroundRuntimeDiagnostics@@*/

/*@@MONITOR_FUNCTION:syncMonitorMinimizedNodeBadges@@*/
