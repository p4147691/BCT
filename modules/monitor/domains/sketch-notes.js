//@@FN_START:clearMonitorTrashedNotes
function clearMonitorTrashedNotes(){monitorTrashedNotes.clear();persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}
//@@FN_END:clearMonitorTrashedNotes

//@@FN_START:deleteMonitorTrashedNote
function deleteMonitorTrashedNote(id){monitorTrashedNotes.delete(String(id));persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}
//@@FN_END:deleteMonitorTrashedNote

//@@FN_START:persistMonitorTrashedNotes
function persistMonitorTrashedNotes(){
  chrome.storage.local.set({[MONITOR_TRASHED_NOTES_KEY]:[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,100)});
}
//@@FN_END:persistMonitorTrashedNotes

//@@FN_START:restoreMonitorTrashedNote
function restoreMonitorTrashedNote(id){
  const key=String(id),note=monitorTrashedNotes.get(key);if(!note)return;
  if(!monitorNotesFeature.restoreNote(note))return;
  monitorTrashedNotes.delete(key);persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();
}
//@@FN_END:restoreMonitorTrashedNote

//@@FN_START:syncMonitorSideNote
function syncMonitorSideNote(){
  const boardCollapsed=monitorRoot.classList.contains("collapsed");
  if(boardCollapsed){
    monitorNotesFeature.layout({boardCollapsed:true});
    monitorSketchFeature.layout({boardCollapsed:true});
    return;
  }
  const rootRect=monitorRoot.getBoundingClientRect();
  const noteLayout=monitorNotesFeature.layout({boardCollapsed:false,rootRect});
  monitorSketchFeature.layout({boardCollapsed:false,rootRect,noteLeft:noteLayout.left});
}
//@@FN_END:syncMonitorSideNote

//@@FN_START:trashMonitorNote
function trashMonitorNote(note){
  if(!note?.id)return;monitorTrashedNotes.set(String(note.id),{...note,trashed_at_ms:Date.now()});persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();
}
//@@FN_END:trashMonitorNote
