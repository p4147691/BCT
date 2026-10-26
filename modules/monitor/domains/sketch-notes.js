//@@FN_START:clearMonitorTrashedNotes
function clearMonitorTrashedNotes(){monitorTrashedNotes.clear();persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}
//@@FN_END:clearMonitorTrashedNotes

//@@FN_START:deleteMonitorTrashedNote
function deleteMonitorTrashedNote(id){monitorTrashedNotes.delete(String(id));persistMonitorTrashedNotes();refreshMonitorRecoveryMenu();}
//@@FN_END:deleteMonitorTrashedNote

//@@FN_START:monitorActiveNote
function monitorActiveNote() { return monitorNotes.find(n=>n.id===monitorActiveNoteId) || null; }
//@@FN_END:monitorActiveNote

//@@FN_START:monitorBindNoteDrag
function monitorBindNoteDrag(row,noteId) {

  row.addEventListener("pointerdown",ev=>{

    if(ev.button!==0||ev.target.closest(".monitor-note-item-delete")||monitorNoteDragState)return;

    const startX=ev.clientX,startY=ev.clientY;

    const state={row,noteId,pointerId:ev.pointerId,startX,startY,lastClientY:startY,active:false,scrollVelocity:0,offsetY:0,height:0,ghost:null,insertLine:null,beforeId:noteId};

    monitorNoteDragState=state;

    const onMove=e=>{

      if(e.pointerId!==state.pointerId)return;

      state.lastClientY=e.clientY;

      if(!state.active&&Math.hypot(e.clientX-startX,e.clientY-startY)<6)return;

      if(!state.active){

        state.active=true; monitorNoteSuppressOpenUntil=Date.now()+500;

        const r=row.getBoundingClientRect(); state.offsetY=startY-r.top; state.height=r.height;

        const ghost=row.cloneNode(true); ghost.classList.add("monitor-note-drag-ghost"); ghost.removeAttribute("data-note-id");

        Object.assign(ghost.style,{position:"fixed",left:`${r.left}px`,top:`${r.top}px`,width:`${r.width}px`,height:`${r.height}px`,margin:"0",zIndex:"2147483646",pointerEvents:"none"});

        state.ghost=ghost; document.body.appendChild(ghost); row.classList.add("monitor-note-drag-source");

        const line=document.createElement("div"); line.className="monitor-note-insert-line"; state.insertLine=line; monitorNoteList.appendChild(line);

        monitorNoteList.classList.add("monitor-note-reordering"); monitorUpdateNoteInsertLine(startY);

        if(!monitorNoteDragRaf)monitorNoteDragRaf=requestAnimationFrame(monitorNoteDragScrollTick);

      }

      e.preventDefault();

      const listRect=monitorNoteList.getBoundingClientRect();

      const top=Math.max(listRect.top,Math.min(e.clientY-state.offsetY,listRect.bottom-state.height));

      state.ghost.style.top=`${top}px`;

      const edge=Math.min(48,Math.max(30,listRect.height*.16));

      if(e.clientY<listRect.top+edge) state.scrollVelocity=-Math.min(14,Math.max(2,(listRect.top+edge-e.clientY)*.34));

      else if(e.clientY>listRect.bottom-edge) state.scrollVelocity=Math.min(14,Math.max(2,(e.clientY-(listRect.bottom-edge))*.34));

      else state.scrollVelocity=0;

      monitorUpdateNoteInsertLine(e.clientY);

    };

    const finish=e=>{

      if(e.pointerId!==state.pointerId)return;

      document.removeEventListener("pointermove",onMove); document.removeEventListener("pointerup",finish); document.removeEventListener("pointercancel",finish);

      if(state.active){

        state.scrollVelocity=0; if(monitorNoteDragRaf){cancelAnimationFrame(monitorNoteDragRaf);monitorNoteDragRaf=0;}

        state.ghost?.remove(); state.insertLine?.remove(); row.classList.remove("monitor-note-drag-source"); monitorNoteList.classList.remove("monitor-note-reordering");

        const currentIds=monitorNotes.map(n=>n.id); const filtered=currentIds.filter(id=>id!==state.noteId);

        let insertAt=state.beforeId ? filtered.indexOf(state.beforeId) : filtered.length;

        if(insertAt<0)insertAt=filtered.length; filtered.splice(insertAt,0,state.noteId);

        const byId=new Map(monitorNotes.map(note=>[note.id,note]));

        if(filtered.length===monitorNotes.length&&filtered.every(id=>byId.has(id))){ monitorNotes=filtered.map(id=>byId.get(id)); monitorLastViewedNoteId=state.noteId; monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorHighlightLastViewedNote(); }

        monitorNoteSuppressOpenUntil=Date.now()+350;

      }

      monitorNoteDragState=null;

    };

    document.addEventListener("pointermove",onMove,{passive:false}); document.addEventListener("pointerup",finish); document.addEventListener("pointercancel",finish);

  });

}
//@@FN_END:monitorBindNoteDrag

//@@FN_START:monitorCreateNote
function monitorCreateNote() {

  const note={id:monitorNoteId(),title:"새 메모",body:"",updatedAt:Date.now()};

  monitorNoteListUndo.push({type:"create",note:{...note}});

  if(monitorNoteListUndo.length>50)monitorNoteListUndo.shift();

  monitorNoteListRedo.length=0;

  monitorNotes.unshift(note);

  monitorNoteLocalDirty=true;

  monitorQueueNoteBundleSave();

  monitorShowNoteList();

  requestAnimationFrame(()=>{

    const row=[...monitorNoteList.querySelectorAll(".monitor-note-item")].find(el=>el.dataset.noteId===note.id);

    if(row) row.scrollIntoView({block:"start",inline:"nearest"});

  });

}
//@@FN_END:monitorCreateNote

//@@FN_START:monitorHighlightLastViewedNote
function monitorHighlightLastViewedNote() {

  const id=String(monitorLastViewedNoteId||""); if(!id)return;

  requestAnimationFrame(()=>{

    const row=[...monitorNoteList.querySelectorAll(".monitor-note-item")].find(el=>el.dataset.noteId===id);

    if(!row)return;

    row.scrollIntoView({block:"nearest",inline:"nearest"});

    row.classList.remove("monitor-note-return-highlight");

    void row.offsetWidth;

    row.classList.add("monitor-note-return-highlight");

    setTimeout(()=>row.classList.remove("monitor-note-return-highlight"),1200);

  });

}
//@@FN_END:monitorHighlightLastViewedNote

//@@FN_START:monitorNoteDragScrollTick
function monitorNoteDragScrollTick() {

  const st=monitorNoteDragState; if(!st?.active){monitorNoteDragRaf=0;return;}

  if(st.scrollVelocity){ monitorNoteList.scrollTop+=st.scrollVelocity; monitorUpdateNoteInsertLine(st.lastClientY); }

  monitorNoteDragRaf=requestAnimationFrame(monitorNoteDragScrollTick);

}
//@@FN_END:monitorNoteDragScrollTick

//@@FN_START:monitorNoteHistoryState
function monitorNoteHistoryState(id=monitorActiveNoteId) { if(!id)return null; if(!monitorNoteHistory.has(id)) monitorNoteHistory.set(id,{undo:[],redo:[]}); return monitorNoteHistory.get(id); }
//@@FN_END:monitorNoteHistoryState

//@@FN_START:monitorNoteId
function monitorNoteId() { return `n${Date.now().toString(36)}${Math.random().toString(36).slice(2,7)}`; }
//@@FN_END:monitorNoteId

//@@FN_START:monitorNoteNative
function monitorNoteNative(message) {

  return monitorNative(message);

}
//@@FN_END:monitorNoteNative

//@@FN_START:monitorNoteScrollRatio
function monitorNoteScrollRatio() {

  const maxScroll = Math.max(0, monitorSideNoteText.scrollHeight - monitorSideNoteText.clientHeight);

  return maxScroll > 0 ? Math.max(0, Math.min(1, monitorSideNoteText.scrollTop / maxScroll)) : 0;

}
//@@FN_END:monitorNoteScrollRatio

//@@FN_START:monitorNoteSnapshot
function monitorNoteSnapshot(note=monitorActiveNote()) { return note ? { title:String(note.title||""), body:String(note.body||"") } : null; }
//@@FN_END:monitorNoteSnapshot

//@@FN_START:monitorNoteTitleFromText
function monitorNoteTitleFromText(text) { return String(text||"").split(/\r?\n/).map(v=>v.trim()).find(Boolean)?.slice(0,42) || "새 메모"; }
//@@FN_END:monitorNoteTitleFromText

//@@FN_START:monitorOpenNote
function monitorOpenNote(id, focusEditor=true) { const note=monitorNotes.find(n=>n.id===id); if(!note)return; monitorNoteListMode=false; monitorActiveNoteId=id; monitorLastViewedNoteId=id; monitorNoteHistoryState(id); monitorNoteList.hidden=true; monitorNoteEditor.hidden=false; monitorNoteBack.hidden=false; monitorNoteAi.hidden=false; monitorNoteAdd.hidden=true; monitorNoteHeaderTitle.textContent="메모 편집"; monitorNoteDelete.textContent="🗑"; monitorNoteDelete.hidden=false; monitorSideNoteText.value=note.body||""; monitorSyncHistoryButtons(); if(focusEditor) requestAnimationFrame(()=>monitorSideNoteText.focus()); }
//@@FN_END:monitorOpenNote

//@@FN_START:monitorParseNoteBundle
function monitorParseNoteBundle(raw) {

  const text = String(raw || "");

  if (text.startsWith(MONITOR_NOTE_BUNDLE_PREFIX)) {

    try { const data = JSON.parse(text.slice(MONITOR_NOTE_BUNDLE_PREFIX.length)); return Array.isArray(data?.notes) ? data.notes.filter(n=>n&&n.id).map(n=>{ const body=String(n.body||""); return {id:String(n.id),title:monitorNoteTitleFromText(body),body,updatedAt:Number(n.updatedAt)||0}; }) : []; } catch (_) { return []; }

  }

  return text.trim() ? [{ id:monitorNoteId(), title:monitorNoteTitleFromText(text), body:text, updatedAt:Date.now() }] : [];

}
//@@FN_END:monitorParseNoteBundle

//@@FN_START:monitorQueueNoteBundleSave
function monitorQueueNoteBundleSave() { clearTimeout(monitorNoteSaveTimer); monitorNoteSaveTimer=setTimeout(async()=>{ const text=monitorSerializeNotes(); const result=await monitorNoteNative({type:"setSharedNote",text}).catch(()=>null); if(result?.ok){monitorNoteLastSharedText=text;monitorNoteLocalDirty=false;} },180); }
//@@FN_END:monitorQueueNoteBundleSave

//@@FN_START:monitorRedoNote
function monitorRedoNote() { const note=monitorActiveNote(); const h=monitorNoteHistoryState(); if(!note||!h?.redo?.length)return; h.undo.push(monitorNoteSnapshot(note)); monitorApplyHistorySnapshot(h.redo.pop()); }
//@@FN_END:monitorRedoNote

//@@FN_START:monitorRenderNoteList
function monitorRenderNoteList() {
  if (!MONITOR_FEATURE_MEMO_ENABLED) { monitorNoteList.replaceChildren(); return; }

  monitorNoteList.innerHTML = "";

  const sorted = [...monitorNotes];

  if (!sorted.length) { const empty=document.createElement("div"); empty.className="monitor-note-empty"; empty.textContent="메모가 없습니다. 위 + 버튼을 눌러 시작하세요."; monitorNoteList.appendChild(empty); return; }

  for (const note of sorted) {

    const row=document.createElement("div"); row.className="monitor-note-item"; row.dataset.noteId=note.id; if(note.id===monitorLastViewedNoteId) row.classList.add("is-last-viewed");

    const open=document.createElement("button"); open.type="button"; open.className="monitor-note-item-open";

    const title=document.createElement("strong"); title.textContent=note.title||"새 메모";

    const preview=document.createElement("span"); preview.textContent=String(note.body||"").replace(/\s+/g," ").trim().slice(0,72)||"내용 없음";

    open.append(title,preview); open.addEventListener("click",event=>{ if(Date.now()<monitorNoteSuppressOpenUntil){event.preventDefault();return;} monitorOpenNote(note.id); });

    const del=document.createElement("button"); del.type="button"; del.className="monitor-note-item-delete"; del.title="메모 삭제"; del.setAttribute("aria-label",`${note.title||"새 메모"} 삭제`); del.textContent="🗑";

    del.addEventListener("click",()=>{ trashMonitorNote(note); monitorNotes=monitorNotes.filter(n=>n.id!==note.id); monitorNoteHistory.delete(note.id); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); monitorRenderNoteList(); monitorSyncHistoryButtons(); });

    row.append(open,del); monitorBindNoteDrag(row,note.id); monitorNoteList.appendChild(row);

  }

}
//@@FN_END:monitorRenderNoteList

//@@FN_START:monitorSerializeNotes
function monitorSerializeNotes() { return MONITOR_NOTE_BUNDLE_PREFIX + JSON.stringify({ notes:monitorNotes }); }
//@@FN_END:monitorSerializeNotes

//@@FN_START:monitorShowNoteList
function monitorShowNoteList() { monitorNoteListMode=true; monitorActiveNoteId=""; monitorNoteList.hidden=false; monitorNoteEditor.hidden=true; monitorNoteBack.hidden=true; monitorNoteAi.hidden=false; monitorNoteDelete.hidden=true; monitorNoteAdd.hidden=false; monitorNoteHeaderTitle.textContent="메모"; monitorRenderNoteList(); monitorSyncHistoryButtons(); }
//@@FN_END:monitorShowNoteList

//@@FN_START:monitorSketchApplySnapshot
function monitorSketchApplySnapshot(snapshot) {
  if (!snapshot) return;
  const image = new Image();
  image.onload = () => {
    monitorSketchContext.save();
    monitorSketchContext.globalCompositeOperation = "source-over";
    monitorSketchContext.clearRect(0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
    monitorSketchContext.drawImage(image, 0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
    monitorSketchContext.restore();
    monitorSketchClearOverlay();
    monitorSketchSave();
  };
  image.src = snapshot;
}
//@@FN_END:monitorSketchApplySnapshot

//@@FN_START:monitorSketchBeginText
function monitorSketchBeginText(event, point) {
  monitorSketchCommitText();
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const wrapRect = monitorSketchCanvas.parentElement.getBoundingClientRect();
  const cssPoint = monitorSketchCssPoint(point);
  if (!cssPoint) return;
  monitorSketchTextPoint = point;
  monitorSketchTextInput.value = "";
  monitorSketchTextInput.style.left = `${cssPoint.left}px`;
  monitorSketchTextInput.style.top = `${cssPoint.top}px`;
  monitorSketchTextInput.style.width = `${Math.max(32, Math.min(180, canvasRect.right - (wrapRect.left + cssPoint.left)))}px`;
  monitorSketchTextInput.style.fontSize = `${MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize]}px`;
  monitorSketchTextInput.hidden = false;
  requestAnimationFrame(() => {
    try { monitorSketchTextInput.focus({ preventScroll: true }); } catch (_) { monitorSketchTextInput.focus(); }
  });
}
//@@FN_END:monitorSketchBeginText

//@@FN_START:monitorSketchCancelText
function monitorSketchCancelText() {
  monitorSketchTextInput.hidden = true;
  monitorSketchTextInput.value = "";
  monitorSketchTextPoint = null;
}
//@@FN_END:monitorSketchCancelText

//@@FN_START:monitorSketchClearOverlay
function monitorSketchClearOverlay() {
  monitorSketchOverlayContext.clearRect(0, 0, monitorSketchOverlay.width, monitorSketchOverlay.height);
}
//@@FN_END:monitorSketchClearOverlay

//@@FN_START:monitorSketchCommitShape
function monitorSketchCommitShape(point) {
  monitorSketchPrepareShapeContext(monitorSketchContext, point);
  monitorSketchDrawShape(monitorSketchContext, point);
  monitorSketchClearOverlay();
}
//@@FN_END:monitorSketchCommitShape

//@@FN_START:monitorSketchCommitText
function monitorSketchCommitText() {
  if (monitorSketchTextInput.hidden || !monitorSketchTextPoint) return;
  const text = monitorSketchTextInput.value;
  const point = monitorSketchTextPoint;
  monitorSketchTextInput.hidden = true;
  monitorSketchTextInput.value = "";
  monitorSketchTextPoint = null;
  if (!text) return;
  monitorSketchRemember();
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  const fontSize = Math.max(1, point.scale * cssSize);
  monitorSketchContext.save();
  monitorSketchContext.globalCompositeOperation = "source-over";
  monitorSketchContext.fillStyle = "#000000";
  monitorSketchContext.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
  monitorSketchContext.textBaseline = "alphabetic";
  const metrics = monitorSketchContext.measureText(text);
  const fontAscent = Number(metrics.fontBoundingBoxAscent) || fontSize * 0.8;
  const fontDescent = Number(metrics.fontBoundingBoxDescent) || fontSize * 0.2;
  const lineBoxOffset = (fontSize - (fontAscent + fontDescent)) / 2;
  const leftBearing = Number(metrics.actualBoundingBoxLeft) || 0;
  monitorSketchContext.fillText(text, point.x + leftBearing, point.y + fontAscent + lineBoxOffset);
  monitorSketchContext.restore();
  monitorSketchSave();
}
//@@FN_END:monitorSketchCommitText

//@@FN_START:monitorSketchCssPoint
function monitorSketchCssPoint(point) {
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const wrapRect = monitorSketchCanvas.parentElement.getBoundingClientRect();
  if (!point || !canvasRect.width || !canvasRect.height) return null;
  return {
    left: canvasRect.left - wrapRect.left + point.x * canvasRect.width / monitorSketchCanvas.width,
    top: canvasRect.top - wrapRect.top + point.y * canvasRect.height / monitorSketchCanvas.height
  };
}
//@@FN_END:monitorSketchCssPoint

//@@FN_START:monitorSketchDrawPreview
function monitorSketchDrawPreview(point) {
  monitorSketchClearOverlay();
  monitorSketchPrepareShapeContext(monitorSketchOverlayContext, point);
  monitorSketchDrawShape(monitorSketchOverlayContext, point);
}
//@@FN_END:monitorSketchDrawPreview

//@@FN_START:monitorSketchDrawShape
function monitorSketchDrawShape(context, point) {
  if (!monitorSketchStartPoint) return;
  const start = monitorSketchStartPoint;
  if (monitorSketchTool === "line") {
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(point.x, point.y);
    context.stroke();
    context.closePath();
    return;
  }
  if (monitorSketchTool === "rect") {
    const x = Math.min(start.x, point.x);
    const y = Math.min(start.y, point.y);
    const width = Math.abs(point.x - start.x);
    const height = Math.abs(point.y - start.y);
    context.strokeRect(x, y, width, height);
  }
}
//@@FN_END:monitorSketchDrawShape

//@@FN_START:monitorSketchHideTextSizeMenu
function monitorSketchHideTextSizeMenu() {
  monitorSketchTextSizeMenu.hidden = true;
  monitorSketchText.setAttribute("aria-expanded", "false");
}
//@@FN_END:monitorSketchHideTextSizeMenu

//@@FN_START:monitorSketchPoint
function monitorSketchPoint(event) {
  const rect = monitorSketchCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: (event.clientX - rect.left) * monitorSketchCanvas.width / rect.width,
    y: (event.clientY - rect.top) * monitorSketchCanvas.height / rect.height,
    scale: monitorSketchCanvas.width / rect.width
  };
}
//@@FN_END:monitorSketchPoint

//@@FN_START:monitorSketchPrepareShapeContext
function monitorSketchPrepareShapeContext(context, point) {
  context.globalCompositeOperation = "source-over";
  context.strokeStyle = "#000000";
  context.lineCap = "round";
  context.lineJoin = "round";
  context.lineWidth = Math.max(4, point.scale * 2.5);
}
//@@FN_END:monitorSketchPrepareShapeContext

//@@FN_START:monitorSketchRedoAction
function monitorSketchRedoAction() {
  if (!monitorSketchRedoStack.length) return;
  const current = monitorSketchSnapshot();
  const next = monitorSketchRedoStack.pop();
  if (current) {
    monitorSketchUndoStack.push(current);
    if (monitorSketchUndoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchUndoStack.shift();
  }
  monitorSketchApplySnapshot(next);
  monitorSketchUpdateHistoryButtons();
}
//@@FN_END:monitorSketchRedoAction

//@@FN_START:monitorSketchRemember
function monitorSketchRemember() {
  const snapshot = monitorSketchSnapshot();
  if (!snapshot) return;
  if (monitorSketchUndoStack[monitorSketchUndoStack.length - 1] !== snapshot) {
    monitorSketchUndoStack.push(snapshot);
    if (monitorSketchUndoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchUndoStack.shift();
  }
  monitorSketchRedoStack.length = 0;
  monitorSketchUpdateHistoryButtons();
}
//@@FN_END:monitorSketchRemember

//@@FN_START:monitorSketchRestore
function monitorSketchRestore() {
  let saved = "";
  try { saved = localStorage.getItem(MONITOR_SKETCH_STORAGE_KEY) || ""; } catch (_) {}
  if (!saved) return;
  const image = new Image();
  image.onload = () => monitorSketchContext.drawImage(image, 0, 0, monitorSketchCanvas.width, monitorSketchCanvas.height);
  image.src = saved;
}
//@@FN_END:monitorSketchRestore

//@@FN_START:monitorSketchSave
function monitorSketchSave() {
  try { localStorage.setItem(MONITOR_SKETCH_STORAGE_KEY, monitorSketchCanvas.toDataURL("image/png")); } catch (_) {}
}
//@@FN_END:monitorSketchSave

//@@FN_START:monitorSketchSetTextSize
function monitorSketchSetTextSize(size) {
  monitorSketchTextSize = MONITOR_SKETCH_TEXT_SIZES[size] ? size : "medium";
  monitorSketchTextSmall.classList.toggle("active", monitorSketchTextSize === "small");
  monitorSketchTextMedium.classList.toggle("active", monitorSketchTextSize === "medium");
  monitorSketchTextLarge.classList.toggle("active", monitorSketchTextSize === "large");
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  monitorSketchCursor.style.setProperty("--monitor-sketch-text-caret-height", `${cssSize}px`);
  if (!monitorSketchTextInput.hidden) monitorSketchTextInput.style.fontSize = `${cssSize}px`;
}
//@@FN_END:monitorSketchSetTextSize

//@@FN_START:monitorSketchSetTool
function monitorSketchSetTool(tool) {
  monitorSketchTool = ["pen", "eraser", "line", "rect", "text"].includes(tool) ? tool : "pen";
  monitorSketchPen.classList.toggle("active", monitorSketchTool === "pen");
  monitorSketchEraser.classList.toggle("active", monitorSketchTool === "eraser");
  monitorSketchLine.classList.toggle("active", monitorSketchTool === "line");
  monitorSketchRect.classList.toggle("active", monitorSketchTool === "rect");
  monitorSketchText.classList.toggle("active", monitorSketchTool === "text");
  monitorSketchCursor.classList.toggle("pen", monitorSketchTool === "pen");
  monitorSketchCursor.classList.toggle("eraser", monitorSketchTool === "eraser");
  monitorSketchCursor.classList.toggle("shape", monitorSketchTool === "line" || monitorSketchTool === "rect");
  monitorSketchCursor.classList.toggle("text", monitorSketchTool === "text");
  if (monitorSketchTool !== "text") monitorSketchHideTextSizeMenu();
}
//@@FN_END:monitorSketchSetTool

//@@FN_START:monitorSketchShowTextSizeMenu
function monitorSketchShowTextSizeMenu() {
  monitorSketchSetTool("text");
  monitorSketchTextSizeMenu.hidden = false;
  monitorSketchText.setAttribute("aria-expanded", "true");
}
//@@FN_END:monitorSketchShowTextSizeMenu

//@@FN_START:monitorSketchSnapshot
function monitorSketchSnapshot() {
  try { return monitorSketchCanvas.toDataURL("image/png"); } catch (_) { return ""; }
}
//@@FN_END:monitorSketchSnapshot

//@@FN_START:monitorSketchStartTextLongPress
function monitorSketchStartTextLongPress(event) {
  if (event.button !== 0) return;
  if (monitorSketchTextLongPressTimer) clearTimeout(monitorSketchTextLongPressTimer);
  monitorSketchSuppressTextClick = false;
  monitorSketchTextLongPressTimer = setTimeout(() => {
    monitorSketchTextLongPressTimer = null;
    monitorSketchSuppressTextClick = true;
    monitorSketchShowTextSizeMenu();
  }, MONITOR_SKETCH_TEXT_LONG_PRESS_MS);
}
//@@FN_END:monitorSketchStartTextLongPress

//@@FN_START:monitorSketchStop
function monitorSketchStop(event) {
  if (!monitorSketchDrawing) return;
  const point = event?.type === "pointercancel" ? null : monitorSketchPoint(event);
  if (point && (monitorSketchTool === "line" || monitorSketchTool === "rect")) {
    monitorSketchCommitShape(point);
  } else {
    monitorSketchClearOverlay();
  }
  monitorSketchDrawing = false;
  monitorSketchStartPoint = null;
  try { if (event?.pointerId != null) monitorSketchCanvas.releasePointerCapture(event.pointerId); } catch (_) {}
  monitorSketchContext.closePath();
  monitorSketchContext.globalCompositeOperation = "source-over";
  monitorSketchSave();
}
//@@FN_END:monitorSketchStop

//@@FN_START:monitorSketchStopTextLongPress
function monitorSketchStopTextLongPress() {
  if (!monitorSketchTextLongPressTimer) return;
  clearTimeout(monitorSketchTextLongPressTimer);
  monitorSketchTextLongPressTimer = null;
}
//@@FN_END:monitorSketchStopTextLongPress

//@@FN_START:monitorSketchSyncTextInputBearing
function monitorSketchSyncTextInputBearing() {
  if (monitorSketchTextInput.hidden || !monitorSketchTextPoint) return;
  const cssPoint = monitorSketchCssPoint(monitorSketchTextPoint);
  if (!cssPoint) return;
  const bearing = monitorSketchTextLeftBearing(monitorSketchTextInput.value, monitorSketchTextPoint);
  const bearingCss = bearing / Math.max(monitorSketchTextPoint.scale, 0.001);
  monitorSketchTextInput.style.left = `${cssPoint.left + bearingCss}px`;
}
//@@FN_END:monitorSketchSyncTextInputBearing

//@@FN_START:monitorSketchTextLeftBearing
function monitorSketchTextLeftBearing(text, point) {
  if (!text || !point) return 0;
  const cssSize = MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize];
  const fontSize = Math.max(1, point.scale * cssSize);
  monitorSketchContext.save();
  monitorSketchContext.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
  const metrics = monitorSketchContext.measureText(text);
  monitorSketchContext.restore();
  return Number(metrics.actualBoundingBoxLeft) || 0;
}
//@@FN_END:monitorSketchTextLeftBearing

//@@FN_START:monitorSketchUndoAction
function monitorSketchUndoAction() {
  if (!monitorSketchUndoStack.length) return;
  const current = monitorSketchSnapshot();
  const previous = monitorSketchUndoStack.pop();
  if (current) {
    monitorSketchRedoStack.push(current);
    if (monitorSketchRedoStack.length > MONITOR_SKETCH_HISTORY_LIMIT) monitorSketchRedoStack.shift();
  }
  monitorSketchApplySnapshot(previous);
  monitorSketchUpdateHistoryButtons();
}
//@@FN_END:monitorSketchUndoAction

//@@FN_START:monitorSketchUpdateCursor
function monitorSketchUpdateCursor(event) {
  const canvasRect = monitorSketchCanvas.getBoundingClientRect();
  const point = monitorSketchPoint(event);
  const cssPoint = monitorSketchCssPoint(point);
  if (!cssPoint || !canvasRect.width || !canvasRect.height) return;
  monitorSketchCursor.style.left = `${cssPoint.left}px`;
  monitorSketchCursor.style.top = `${cssPoint.top}px`;
  if (monitorSketchTool === "eraser") {
    const scale = monitorSketchCanvas.width / canvasRect.width;
    const eraseCssPx = Math.max(12, 4 / Math.max(scale, 0.001));
    monitorSketchCursor.style.width = `${eraseCssPx}px`;
    monitorSketchCursor.style.height = `${eraseCssPx}px`;
  } else {
    monitorSketchCursor.style.width = "";
    monitorSketchCursor.style.height = "";
  }
  if (monitorSketchTool === "text") {
    monitorSketchCursor.style.setProperty("--monitor-sketch-text-caret-height", `${MONITOR_SKETCH_TEXT_SIZES[monitorSketchTextSize]}px`);
  }
  monitorSketchCursor.classList.add("visible");
}
//@@FN_END:monitorSketchUpdateCursor

//@@FN_START:monitorSketchUpdateHistoryButtons
function monitorSketchUpdateHistoryButtons() {
  monitorSketchUndo.disabled = monitorSketchUndoStack.length === 0;
  monitorSketchRedo.disabled = monitorSketchRedoStack.length === 0;
}
//@@FN_END:monitorSketchUpdateHistoryButtons

//@@FN_START:monitorUndoNote
function monitorUndoNote() { const note=monitorActiveNote(); const h=monitorNoteHistoryState(); if(!note||!h?.undo?.length)return; h.redo.push(monitorNoteSnapshot(note)); monitorApplyHistorySnapshot(h.undo.pop()); }
//@@FN_END:monitorUndoNote

//@@FN_START:monitorUpdateNoteInsertLine
function monitorUpdateNoteInsertLine(clientY) {

  const st=monitorNoteDragState; if(!st?.active)return;

  const rows=[...monitorNoteList.querySelectorAll(".monitor-note-item")];

  let beforeId=null, lineY=null;

  for(const row of rows){

    const r=row.getBoundingClientRect();

    if(clientY < r.top + r.height/2){ beforeId=row.dataset.noteId; lineY=r.top; break; }

  }

  if(lineY==null){

    const last=rows[rows.length-1];

    lineY=last ? last.getBoundingClientRect().bottom : monitorNoteList.getBoundingClientRect().top+7;

  }

  st.beforeId=beforeId;

  const listRect=monitorNoteList.getBoundingClientRect();

  st.insertLine.style.top=`${lineY-listRect.top+monitorNoteList.scrollTop}px`;

}
//@@FN_END:monitorUpdateNoteInsertLine

//@@FN_START:organizeMonitorNoteWithAi
async function organizeMonitorNoteWithAi() {

  if (monitorNoteAiBusy) return;

  monitorNoteAiBusy = true; monitorNoteAi.disabled = true; monitorNoteAi.textContent = "...";

  try {

    if (monitorNoteListMode) {

      const baseline = monitorSerializeNotes();

      const targets = monitorNotes.filter(note => String(note.body || "").trim());

      if (!targets.length) { setMonitorStatus("AI 정리할 메모가 없음", false); return; }

      const response = await actFetch(ORCHESTRATOR_NOTE_AI_URL, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({notes:targets.map(note=>({id:note.id,text:String(note.body||"").trim()}))}) });

      const data = await response.json().catch(() => null);

      if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);

      const cleanedById = new Map((Array.isArray(data.notes)?data.notes:[]).map(item=>[String(item?.id||""),String(item?.text||"").trim()]));

      if (cleanedById.size !== targets.length || targets.some(note=>!cleanedById.get(note.id))) throw new Error("NOTE_AI_BUNDLE_INCOMPLETE");

      if (!monitorNoteListMode || monitorSerializeNotes() !== baseline) { setMonitorStatus("메모 목록이 바뀌어 AI 결과는 적용하지 않음", false); return; }

      const now = Date.now();

      monitorNotes = monitorNotes.map(note => cleanedById.has(note.id) ? {...note, body:cleanedById.get(note.id), title:monitorNoteTitleFromText(cleanedById.get(note.id)), updatedAt:now} : note);

      monitorNoteLocalDirty = true;

      const bundle = monitorSerializeNotes();

      const saved = await monitorNoteNative({ type:"setSharedNote", text:bundle });

      if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");

      monitorNoteLastSharedText = bundle; monitorNoteLocalDirty = false; monitorRenderNoteList();

      setMonitorStatus(`전체 메모 AI 정리 완료 ${targets.length}개${data.profile_id ? ` - ${String(data.profile_id)}` : ""}`, true);

      return;

    }

    const source = String(monitorSideNoteText.value || "").trim();

    if (!source) { setMonitorStatus("AI 정리할 메모가 없음", false); return; }

    const response = await actFetch(ORCHESTRATOR_NOTE_AI_URL, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({text:source}) });

    const data = await response.json().catch(() => null);

    if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);

    if (String(monitorSideNoteText.value || "").trim() !== source) { setMonitorStatus("메모가 바뀌어 AI 결과는 적용하지 않음", false); return; }

    const cleaned = String(data.text || "").trim(); if (!cleaned) throw new Error("NOTE_AI_EMPTY_RESULT");

    monitorRecordUndoBeforeEdit(); monitorSideNoteText.value = cleaned; monitorUpdateActiveFromEditor(); monitorSyncHistoryButtons(); syncMonitorSideNote();

    const bundle = monitorSerializeNotes();

    const saved = await monitorNoteNative({ type:"setSharedNote", text:bundle });

    if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");

    monitorNoteLastSharedText = bundle; monitorNoteLocalDirty = false;

    setMonitorStatus(`메모 AI 정리 완료 - ${String(data.profile_id||"")}`, true);

  } catch (error) { setMonitorStatus(`메모 AI 실패 - ${monitorRoleAdminErrorText(error?.message || error)}`, false); }

  finally { monitorNoteAiBusy = false; monitorNoteAi.disabled = false; monitorNoteAi.textContent = "AI"; }

}
//@@FN_END:organizeMonitorNoteWithAi

//@@FN_START:persistMonitorTrashedNotes
function persistMonitorTrashedNotes(){

  chrome.storage.local.set({[MONITOR_TRASHED_NOTES_KEY]:[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0)).slice(0,100)});

}
//@@FN_END:persistMonitorTrashedNotes

//@@FN_START:refreshMonitorSharedNote
async function refreshMonitorSharedNote() {

  if (monitorNoteDragState?.active) return;

  const result = await monitorNoteNative({ type: "getSharedNote" }).catch(() => null);

  if (!result?.ok) return;

  const text = String(result.text || "");

  if (monitorNoteReady && text === monitorSerializeNotes()) { monitorNoteLastSharedText = text; monitorNoteLocalDirty = false; return; }

  const editorActive = document.activeElement === monitorSideNoteText;

  if (monitorNoteReady && editorActive && text !== monitorSerializeNotes()) return;

  const safeToReplace = !monitorNoteLocalDirty || monitorSerializeNotes() === monitorNoteLastSharedText;

  if (!monitorNoteReady || safeToReplace) {

    const previousActive = monitorActiveNoteId;

    monitorNotes = monitorParseNoteBundle(text);

    monitorNoteLastSharedText = text;

    monitorNoteLocalDirty = false;

    if (!monitorNoteReady || monitorNoteListMode || !monitorNotes.some(n=>n.id===previousActive)) monitorShowNoteList();

    else { monitorOpenNote(previousActive, false); }

    syncMonitorSideNote();

    if (text && !text.startsWith(MONITOR_NOTE_BUNDLE_PREFIX)) { monitorNoteLocalDirty = true; monitorQueueNoteBundleSave(); }

  }

  monitorNoteReady = true;

}
//@@FN_END:refreshMonitorSharedNote

//@@FN_START:refreshMonitorSharedNoteView
async function refreshMonitorSharedNoteView() {

  if (monitorNoteViewSyncBusy) return;

  if (document.activeElement === monitorSideNoteText) return;

  monitorNoteViewSyncBusy = true;

  try {

    const result = await monitorNoteNative({ type: "getSharedMonitorNoteView" }).catch(() => null);

    const revision = String(result?.revision || "");

    if (!result?.ok || !revision || revision === monitorNoteViewRevision) return;

    monitorNoteViewRevision = revision;

    const ratio = Math.max(0, Math.min(1, Number(result.ratio) || 0));

    const maxScroll = Math.max(0, monitorSideNoteText.scrollHeight - monitorSideNoteText.clientHeight);

    const target = maxScroll * ratio;

    if (Math.abs(monitorSideNoteText.scrollTop - target) > 2) {

      monitorNoteViewRemoteApplying = true;

      monitorSideNoteText.scrollTop = target;

      requestAnimationFrame(() => { monitorNoteViewRemoteApplying = false; });

    }

  } finally { monitorNoteViewSyncBusy = false; }

}
//@@FN_END:refreshMonitorSharedNoteView

//@@FN_START:restoreMonitorTrashedNote
function restoreMonitorTrashedNote(id){

  const note=monitorTrashedNotes.get(String(id)); if(!note)return; monitorTrashedNotes.delete(String(id)); const restored={...note}; delete restored.trashed_at_ms; if(!monitorNotes.some((x)=>x.id===restored.id))monitorNotes.push(restored); monitorNoteLocalDirty=true; monitorQueueNoteBundleSave(); persistMonitorTrashedNotes(); monitorRenderNoteList(); refreshMonitorRecoveryMenu();

}
//@@FN_END:restoreMonitorTrashedNote

//@@FN_START:syncMonitorSideNote
function syncMonitorSideNote() {

  const boardCollapsed = monitorRoot.classList.contains("collapsed");

  monitorNote.hidden = boardCollapsed;
  monitorSketchpad.hidden = boardCollapsed;

  if (boardCollapsed) return;

  const rect = monitorRoot.getBoundingClientRect();

  const width = Math.min(300, Math.max(220, rect.left - 24));

  const effectiveWidth = monitorNoteCollapsed ? 50 : width;

  monitorNote.style.width = `${Math.round(width)}px`;

  monitorNote.style.top = `${Math.round(rect.top)}px`;

  monitorNote.style.left = `${Math.max(8, Math.round(rect.left - effectiveWidth - 8))}px`;

  const noteLeft = Number.parseFloat(monitorNote.style.left) || 8;
  const sketchWidth = Math.min(280, Math.max(180, noteLeft - 16));
  const sketchEffectiveWidth = monitorSketchCollapsed ? 50 : sketchWidth;
  monitorSketchpad.style.width = `${Math.round(sketchWidth)}px`;
  monitorSketchpad.style.top = `${Math.round(rect.top)}px`;
  monitorSketchpad.style.left = `${Math.max(8, Math.round(noteLeft - sketchEffectiveWidth - 8))}px`;
  monitorSketchpad.style.height = monitorSketchCollapsed ? "40px" : `${Math.round(rect.height)}px`;
  monitorSketchpad.style.minWidth = monitorSketchCollapsed ? "50px" : "180px";
  monitorSketchpad.style.minHeight = monitorSketchCollapsed ? "40px" : "180px";
  monitorSketchpad.classList.toggle("collapsed", monitorSketchCollapsed);
  monitorSketchCollapse.classList.toggle("is-collapsed", monitorSketchCollapsed);
  monitorSketchCollapse.title = monitorSketchCollapsed ? "그림판 펼치기" : "그림판 접기";
  monitorSketchCollapse.setAttribute("aria-label", monitorSketchCollapse.title);

  monitorNote.classList.toggle("collapsed", monitorNoteCollapsed);

  monitorNoteCollapse.classList.toggle("is-collapsed", monitorNoteCollapsed);

  monitorNoteCollapse.title = monitorNoteCollapsed ? "메모 펼치기" : "메모 접기";

  monitorNoteCollapse.setAttribute("aria-label", monitorNoteCollapse.title);

  if (monitorNoteCollapsed) {

    monitorNote.style.width = "50px";

    monitorNote.style.minWidth = "50px";

    monitorNote.style.height = "40px";

    monitorNote.style.minHeight = "40px";

    return;

  }

  monitorNote.style.minWidth = "220px";

  monitorNote.style.minHeight = "180px";

  monitorNote.style.height = `${Math.round(rect.height)}px`;

}
//@@FN_END:syncMonitorSideNote

//@@FN_START:trashMonitorNote
function trashMonitorNote(note){

  if(!note?.id)return; monitorTrashedNotes.set(String(note.id),{...note,trashed_at_ms:Date.now()}); persistMonitorTrashedNotes(); refreshMonitorRecoveryMenu();

}
//@@FN_END:trashMonitorNote

