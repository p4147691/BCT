"use strict";
(function installMonitorNotesFeature(root) {
  const BUNDLE_PREFIX = "DWM_NOTES_V1:";
  const LIST_HISTORY_LIMIT = 50;
  const EDIT_HISTORY_LIMIT = 100;

  function titleFromText(text) {
    return String(text || "").split(/\r?\n/).map((value) => value.trim()).find(Boolean)?.slice(0, 42) || "새 메모";
  }

  function create({
    document: doc,
    enabled = true,
    sharedNotePort,
    aiPort,
    onTrash,
    onStatus,
    errorText,
    onLayoutChange,
    requestFrame,
    cancelFrame,
    setTimer,
    clearTimer,
  } = {}) {
    if (!doc?.createElement) throw new Error("MONITOR_NOTES_DOCUMENT_REQUIRED");
    for (const name of ["getContent", "setContent", "getView", "setView"]) {
      if (typeof sharedNotePort?.[name] !== "function") throw new Error(`MONITOR_NOTES_PORT_REQUIRED:${name}`);
    }
    if (typeof aiPort?.organize !== "function") throw new Error("MONITOR_NOTES_AI_PORT_REQUIRED");
    const frame = typeof requestFrame === "function" ? requestFrame : (callback) => callback();
    const cancel = typeof cancelFrame === "function" ? cancelFrame : () => {};
    const later = typeof setTimer === "function" ? setTimer : root.setTimeout.bind(root);
    const cancelLater = typeof clearTimer === "function" ? clearTimer : root.clearTimeout.bind(root);
    const trash = typeof onTrash === "function" ? onTrash : () => {};
    const status = typeof onStatus === "function" ? onStatus : () => {};
    const describeError = typeof errorText === "function" ? errorText : (value) => String(value || "");
    const requestLayout = typeof onLayoutChange === "function" ? onLayoutChange : () => {};

    const element = doc.createElement("aside");
    element.className = "monitor-side-note";
    element.setAttribute("aria-label", "할 일 메모");
    element.innerHTML = `<div class="monitor-side-note-title"><span class="monitor-note-title-left"><button id="monitorNoteBack" type="button" title="메모 목록" aria-label="메모 목록" hidden>‹</button><span id="monitorNoteHeaderTitle">메모</span><button id="monitorNoteAdd" type="button" title="새 메모" aria-label="새 메모">＋</button></span><span class="monitor-note-actions"><button id="monitorNoteUndo" type="button" title="실행 취소 (Ctrl+Z)" aria-label="실행 취소" hidden>↶</button><button id="monitorNoteRedo" type="button" title="다시 실행 (Ctrl+Y / Ctrl+Shift+Z)" aria-label="다시 실행" hidden>↷</button><button id="monitorNoteAi" type="button" title="작업하지 않는 유휴 워커로 메모 정리" aria-label="AI로 메모 정리" hidden>AI</button><button id="monitorNoteDelete" type="button" title="현재 메모 삭제" aria-label="현재 메모 삭제" hidden>×</button><button id="monitorNoteCollapse" type="button" title="메모 접기" aria-label="메모 접기">−</button></span></div><div id="monitorNoteList" class="monitor-note-list"></div><div id="monitorNoteEditor" class="monitor-note-editor" hidden><textarea id="monitorSideNoteText" spellcheck="false" placeholder="첫 줄이 목록 제목으로 표시됩니다.\n해야 할 일..."></textarea></div>`;
    if (!enabled) element.style.setProperty("display", "none", "important");

    const query = (selector) => {
      const node = element.querySelector(selector);
      if (!node) throw new Error(`MONITOR_NOTES_MOUNT_MISSING:${selector}`);
      return node;
    };
    const editorText = query("#monitorSideNoteText");
    const aiButton = query("#monitorNoteAi");
    const collapseButton = query("#monitorNoteCollapse");
    const backButton = query("#monitorNoteBack");
    const addButton = query("#monitorNoteAdd");
    const deleteButton = query("#monitorNoteDelete");
    const undoButton = query("#monitorNoteUndo");
    const redoButton = query("#monitorNoteRedo");
    const list = query("#monitorNoteList");
    const editor = query("#monitorNoteEditor");
    const headerTitle = query("#monitorNoteHeaderTitle");
    collapseButton.classList.add("monitor-collapse-chevron");
    collapseButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg>';

    let notes = [];
    let activeNoteId = "";
    let lastViewedNoteId = "";
    let listMode = true;
    let suppressOpenUntil = 0;
    let dragState = null;
    let dragFrame = 0;
    let collapsed = false;
    let saveTimer = 0;
    let aiBusy = false;
    let lastSharedText = "";
    let localDirty = false;
    let ready = false;
    let viewRevision = "";
    let viewRemoteApplying = false;
    let viewSaveTimer = 0;
    let viewSyncBusy = false;
    let destroyed = false;
    const history = new Map();
    const listUndo = [];
    const listRedo = [];

    const noteId = () => `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
    const activeNote = () => notes.find((note) => note.id === activeNoteId) || null;
    const noteSnapshot = (note = activeNote()) => note ? { title: String(note.title || ""), body: String(note.body || "") } : null;
    const historyState = (id = activeNoteId) => {
      if (!id) return null;
      if (!history.has(id)) history.set(id, { undo: [], redo: [] });
      return history.get(id);
    };
    const serialize = () => BUNDLE_PREFIX + JSON.stringify({ notes });
    const parse = (raw) => {
      const text = String(raw || "");
      if (text.startsWith(BUNDLE_PREFIX)) {
        try {
          const data = JSON.parse(text.slice(BUNDLE_PREFIX.length));
          return Array.isArray(data?.notes) ? data.notes.filter((note) => note && note.id).map((note) => {
            const body = String(note.body || "");
            return { id: String(note.id), title: titleFromText(body), body, updatedAt: Number(note.updatedAt) || 0 };
          }) : [];
        } catch (_) { return []; }
      }
      return text.trim() ? [{ id: noteId(), title: titleFromText(text), body: text, updatedAt: Date.now() }] : [];
    };

    function syncHistoryButtons() {
      if (listMode) {
        undoButton.hidden = false;
        undoButton.disabled = !listUndo.length;
        undoButton.title = "목록 변경 되돌리기 (Ctrl+Z)";
        undoButton.setAttribute("aria-label", "목록 변경 되돌리기");
        redoButton.hidden = false;
        redoButton.disabled = !listRedo.length;
        redoButton.title = "목록 변경 다시 실행 (Ctrl+Y / Ctrl+Shift+Z)";
        redoButton.setAttribute("aria-label", "목록 변경 다시 실행");
        return;
      }
      const state = historyState();
      const editing = Boolean(activeNoteId);
      undoButton.hidden = !editing;
      redoButton.hidden = !editing;
      undoButton.disabled = !state?.undo?.length;
      redoButton.disabled = !state?.redo?.length;
      undoButton.title = "실행 취소 (Ctrl+Z)";
      undoButton.setAttribute("aria-label", "실행 취소");
    }

    function updateActiveFromEditor() {
      const note = activeNote();
      if (!note) return;
      note.body = String(editorText.value || "");
      note.title = titleFromText(note.body);
      note.updatedAt = Date.now();
      localDirty = true;
    }

    function recordUndoBeforeEdit() {
      const note = activeNote();
      const state = historyState();
      if (!note || !state) return;
      const previous = noteSnapshot(note);
      const next = { title: titleFromText(editorText.value), body: String(editorText.value || "") };
      if (previous.body === next.body) return;
      const last = state.undo[state.undo.length - 1];
      if (!last || last.body !== previous.body) state.undo.push(previous);
      if (state.undo.length > EDIT_HISTORY_LIMIT) state.undo.shift();
      state.redo.length = 0;
    }

    function queueSave() {
      cancelLater(saveTimer);
      saveTimer = later(async () => {
        const text = serialize();
        const result = await sharedNotePort.setContent(text).catch(() => null);
        if (result?.ok) { lastSharedText = text; localDirty = false; }
      }, 180);
    }

    function applyHistorySnapshot(snapshot) {
      const note = activeNote();
      if (!note || !snapshot) return;
      note.body = String(snapshot.body || "");
      note.title = titleFromText(note.body);
      note.updatedAt = Date.now();
      editorText.value = note.body;
      localDirty = true;
      queueSave();
      syncHistoryButtons();
    }

    function undoEdit() {
      const note = activeNote();
      const state = historyState();
      if (!note || !state?.undo?.length) return;
      state.redo.push(noteSnapshot(note));
      applyHistorySnapshot(state.undo.pop());
    }

    function redoEdit() {
      const note = activeNote();
      const state = historyState();
      if (!note || !state?.redo?.length) return;
      state.undo.push(noteSnapshot(note));
      applyHistorySnapshot(state.redo.pop());
    }

    function undoListChange() {
      const action = listUndo.pop();
      if (!action) return;
      let note = action.note || action;
      if (action.type === "create") {
        const current = notes.find((item) => item.id === note.id);
        if (current) note = { ...current };
        notes = notes.filter((item) => item.id !== note.id);
        history.delete(note.id);
      } else if (!notes.some((item) => item.id === note.id)) notes.push(note);
      listRedo.push({ type: action.type || "delete", note: { ...note } });
      if (listRedo.length > LIST_HISTORY_LIMIT) listRedo.shift();
      localDirty = true;
      queueSave();
      renderList();
      syncHistoryButtons();
    }

    function redoListChange() {
      const action = listRedo.pop();
      if (!action) return;
      const note = action.note || action;
      if ((action.type || "delete") === "create") {
        if (!notes.some((item) => item.id === note.id)) notes.push(note);
      } else {
        notes = notes.filter((item) => item.id !== note.id);
        history.delete(note.id);
      }
      listUndo.push({ type: action.type || "delete", note: { ...note } });
      if (listUndo.length > LIST_HISTORY_LIMIT) listUndo.shift();
      localDirty = true;
      queueSave();
      renderList();
      syncHistoryButtons();
    }

    function updateInsertLine(clientY) {
      const state = dragState;
      if (!state?.active) return;
      const rows = [...list.querySelectorAll(".monitor-note-item")];
      let beforeId = null;
      let lineY = null;
      for (const row of rows) {
        const bounds = row.getBoundingClientRect();
        if (clientY < bounds.top + bounds.height / 2) { beforeId = row.dataset.noteId; lineY = bounds.top; break; }
      }
      if (lineY == null) {
        const last = rows[rows.length - 1];
        lineY = last ? last.getBoundingClientRect().bottom : list.getBoundingClientRect().top + 7;
      }
      state.beforeId = beforeId;
      const bounds = list.getBoundingClientRect();
      state.insertLine.style.top = `${lineY - bounds.top + list.scrollTop}px`;
    }

    function dragScrollTick() {
      const state = dragState;
      if (!state?.active) { dragFrame = 0; return; }
      if (state.scrollVelocity) { list.scrollTop += state.scrollVelocity; updateInsertLine(state.lastClientY); }
      dragFrame = frame(dragScrollTick);
    }

    function bindDrag(row, id) {
      row.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || event.target.closest(".monitor-note-item-delete") || dragState) return;
        const startX = event.clientX;
        const startY = event.clientY;
        const state = { row, noteId: id, pointerId: event.pointerId, startX, startY, lastClientY: startY, active: false, scrollVelocity: 0, offsetY: 0, height: 0, ghost: null, insertLine: null, beforeId: id };
        dragState = state;
        const onMove = (moveEvent) => {
          if (moveEvent.pointerId !== state.pointerId) return;
          state.lastClientY = moveEvent.clientY;
          if (!state.active && Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 6) return;
          if (!state.active) {
            state.active = true;
            suppressOpenUntil = Date.now() + 500;
            const bounds = row.getBoundingClientRect();
            state.offsetY = startY - bounds.top;
            state.height = bounds.height;
            const ghost = row.cloneNode(true);
            ghost.classList.add("monitor-note-drag-ghost");
            ghost.removeAttribute("data-note-id");
            Object.assign(ghost.style, { position: "fixed", left: `${bounds.left}px`, top: `${bounds.top}px`, width: `${bounds.width}px`, height: `${bounds.height}px`, margin: "0", zIndex: "2147483646", pointerEvents: "none" });
            state.ghost = ghost;
            doc.body.appendChild(ghost);
            row.classList.add("monitor-note-drag-source");
            const line = doc.createElement("div");
            line.className = "monitor-note-insert-line";
            state.insertLine = line;
            list.appendChild(line);
            list.classList.add("monitor-note-reordering");
            updateInsertLine(startY);
            if (!dragFrame) dragFrame = frame(dragScrollTick);
          }
          moveEvent.preventDefault();
          const listRect = list.getBoundingClientRect();
          const top = Math.max(listRect.top, Math.min(moveEvent.clientY - state.offsetY, listRect.bottom - state.height));
          state.ghost.style.top = `${top}px`;
          const edge = Math.min(48, Math.max(30, listRect.height * .16));
          if (moveEvent.clientY < listRect.top + edge) state.scrollVelocity = -Math.min(14, Math.max(2, (listRect.top + edge - moveEvent.clientY) * .34));
          else if (moveEvent.clientY > listRect.bottom - edge) state.scrollVelocity = Math.min(14, Math.max(2, (moveEvent.clientY - (listRect.bottom - edge)) * .34));
          else state.scrollVelocity = 0;
          updateInsertLine(moveEvent.clientY);
        };
        const finish = (finishEvent) => {
          if (finishEvent.pointerId !== state.pointerId) return;
          doc.removeEventListener("pointermove", onMove);
          doc.removeEventListener("pointerup", finish);
          doc.removeEventListener("pointercancel", finish);
          if (state.active) {
            state.scrollVelocity = 0;
            if (dragFrame) { cancel(dragFrame); dragFrame = 0; }
            state.ghost?.remove();
            state.insertLine?.remove();
            row.classList.remove("monitor-note-drag-source");
            list.classList.remove("monitor-note-reordering");
            const currentIds = notes.map((note) => note.id);
            const filtered = currentIds.filter((noteIdValue) => noteIdValue !== state.noteId);
            let insertAt = state.beforeId ? filtered.indexOf(state.beforeId) : filtered.length;
            if (insertAt < 0) insertAt = filtered.length;
            filtered.splice(insertAt, 0, state.noteId);
            const byId = new Map(notes.map((note) => [note.id, note]));
            if (filtered.length === notes.length && filtered.every((noteIdValue) => byId.has(noteIdValue))) {
              notes = filtered.map((noteIdValue) => byId.get(noteIdValue));
              lastViewedNoteId = state.noteId;
              localDirty = true;
              queueSave();
              renderList();
              highlightLastViewed();
            }
            suppressOpenUntil = Date.now() + 350;
          }
          dragState = null;
        };
        doc.addEventListener("pointermove", onMove, { passive: false });
        doc.addEventListener("pointerup", finish);
        doc.addEventListener("pointercancel", finish);
      });
    }

    function openNote(id, focusEditor = true) {
      const note = notes.find((item) => item.id === id);
      if (!note) return;
      listMode = false;
      activeNoteId = id;
      lastViewedNoteId = id;
      historyState(id);
      list.hidden = true;
      editor.hidden = false;
      backButton.hidden = false;
      aiButton.hidden = false;
      addButton.hidden = true;
      headerTitle.textContent = "메모 편집";
      deleteButton.textContent = "🗑";
      deleteButton.hidden = false;
      editorText.value = note.body || "";
      syncHistoryButtons();
      if (focusEditor) frame(() => editorText.focus());
    }

    function highlightLastViewed() {
      const id = String(lastViewedNoteId || "");
      if (!id) return;
      frame(() => {
        const row = [...list.querySelectorAll(".monitor-note-item")].find((item) => item.dataset.noteId === id);
        if (!row) return;
        row.scrollIntoView({ block: "nearest", inline: "nearest" });
        row.classList.remove("monitor-note-return-highlight");
        void row.offsetWidth;
        row.classList.add("monitor-note-return-highlight");
        later(() => row.classList.remove("monitor-note-return-highlight"), 1200);
      });
    }

    function renderList() {
      if (!enabled) { list.replaceChildren(); return; }
      list.innerHTML = "";
      if (!notes.length) {
        const empty = doc.createElement("div");
        empty.className = "monitor-note-empty";
        empty.textContent = "메모가 없습니다. 위 + 버튼을 눌러 시작하세요.";
        list.appendChild(empty);
        return;
      }
      for (const note of notes) {
        const row = doc.createElement("div");
        row.className = "monitor-note-item";
        row.dataset.noteId = note.id;
        if (note.id === lastViewedNoteId) row.classList.add("is-last-viewed");
        const open = doc.createElement("button");
        open.type = "button";
        open.className = "monitor-note-item-open";
        const title = doc.createElement("strong");
        title.textContent = note.title || "새 메모";
        const preview = doc.createElement("span");
        preview.textContent = String(note.body || "").replace(/\s+/g, " ").trim().slice(0, 72) || "내용 없음";
        open.append(title, preview);
        open.addEventListener("click", (event) => {
          if (Date.now() < suppressOpenUntil) { event.preventDefault(); return; }
          openNote(note.id);
        });
        const del = doc.createElement("button");
        del.type = "button";
        del.className = "monitor-note-item-delete";
        del.title = "메모 삭제";
        del.setAttribute("aria-label", `${note.title || "새 메모"} 삭제`);
        del.textContent = "🗑";
        del.addEventListener("click", () => {
          trash({ ...note });
          notes = notes.filter((item) => item.id !== note.id);
          history.delete(note.id);
          localDirty = true;
          queueSave();
          renderList();
          syncHistoryButtons();
        });
        row.append(open, del);
        bindDrag(row, note.id);
        list.appendChild(row);
      }
    }

    function showList() {
      listMode = true;
      activeNoteId = "";
      list.hidden = false;
      editor.hidden = true;
      backButton.hidden = true;
      aiButton.hidden = false;
      deleteButton.hidden = true;
      addButton.hidden = false;
      headerTitle.textContent = "메모";
      renderList();
      syncHistoryButtons();
    }

    function createNote() {
      const note = { id: noteId(), title: "새 메모", body: "", updatedAt: Date.now() };
      listUndo.push({ type: "create", note: { ...note } });
      if (listUndo.length > LIST_HISTORY_LIMIT) listUndo.shift();
      listRedo.length = 0;
      notes.unshift(note);
      localDirty = true;
      queueSave();
      showList();
      frame(() => {
        const row = [...list.querySelectorAll(".monitor-note-item")].find((item) => item.dataset.noteId === note.id);
        row?.scrollIntoView({ block: "start", inline: "nearest" });
      });
    }

    async function organizeWithAi() {
      if (aiBusy) return;
      aiBusy = true;
      aiButton.disabled = true;
      aiButton.textContent = "...";
      try {
        if (listMode) {
          const baseline = serialize();
          const targets = notes.filter((note) => String(note.body || "").trim());
          if (!targets.length) { status("AI 정리할 메모가 없음", false); return; }
          const data = await aiPort.organize({ notes: targets.map((note) => ({ id: note.id, text: String(note.body || "").trim() })) });
          const cleanedById = new Map((Array.isArray(data?.notes) ? data.notes : []).map((item) => [String(item?.id || ""), String(item?.text || "").trim()]));
          if (cleanedById.size !== targets.length || targets.some((note) => !cleanedById.get(note.id))) throw new Error("NOTE_AI_BUNDLE_INCOMPLETE");
          if (!listMode || serialize() !== baseline) { status("메모 목록이 바뀌어 AI 결과는 적용하지 않음", false); return; }
          const now = Date.now();
          notes = notes.map((note) => cleanedById.has(note.id) ? { ...note, body: cleanedById.get(note.id), title: titleFromText(cleanedById.get(note.id)), updatedAt: now } : note);
          localDirty = true;
          const bundle = serialize();
          const saved = await sharedNotePort.setContent(bundle);
          if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");
          lastSharedText = bundle;
          localDirty = false;
          renderList();
          status(`전체 메모 AI 정리 완료 ${targets.length}개${data.profile_id ? ` - ${String(data.profile_id)}` : ""}`, true);
          return;
        }
        const source = String(editorText.value || "").trim();
        if (!source) { status("AI 정리할 메모가 없음", false); return; }
        const data = await aiPort.organize({ text: source });
        if (String(editorText.value || "").trim() !== source) { status("메모가 바뀌어 AI 결과는 적용하지 않음", false); return; }
        const cleaned = String(data?.text || "").trim();
        if (!cleaned) throw new Error("NOTE_AI_EMPTY_RESULT");
        recordUndoBeforeEdit();
        editorText.value = cleaned;
        updateActiveFromEditor();
        syncHistoryButtons();
        requestLayout();
        const bundle = serialize();
        const saved = await sharedNotePort.setContent(bundle);
        if (!saved?.ok) throw new Error(saved?.error || "NOTE_SAVE_FAILED");
        lastSharedText = bundle;
        localDirty = false;
        status(`메모 AI 정리 완료 - ${String(data?.profile_id || "")}`, true);
      } catch (error) {
        status(`메모 AI 실패 - ${describeError(error?.message || error)}`, false);
      } finally {
        aiBusy = false;
        aiButton.disabled = false;
        aiButton.textContent = "AI";
      }
    }

    async function refreshContent() {
      if (dragState?.active) return;
      const result = await sharedNotePort.getContent().catch(() => null);
      if (!result?.ok) return;
      const text = String(result.text || "");
      if (ready && text === serialize()) { lastSharedText = text; localDirty = false; return; }
      const editorActive = doc.activeElement === editorText;
      if (ready && editorActive && text !== serialize()) return;
      const safeToReplace = !localDirty || serialize() === lastSharedText;
      if (!ready || safeToReplace) {
        const previousActive = activeNoteId;
        notes = parse(text);
        lastSharedText = text;
        localDirty = false;
        if (!ready || listMode || !notes.some((note) => note.id === previousActive)) showList();
        else openNote(previousActive, false);
        requestLayout();
        if (text && !text.startsWith(BUNDLE_PREFIX)) { localDirty = true; queueSave(); }
      }
      ready = true;
    }

    const scrollRatio = () => {
      const maxScroll = Math.max(0, editorText.scrollHeight - editorText.clientHeight);
      return maxScroll > 0 ? Math.max(0, Math.min(1, editorText.scrollTop / maxScroll)) : 0;
    };

    async function refreshView() {
      if (viewSyncBusy || doc.activeElement === editorText) return;
      viewSyncBusy = true;
      try {
        const result = await sharedNotePort.getView().catch(() => null);
        const revision = String(result?.revision || "");
        if (!result?.ok || !revision || revision === viewRevision) return;
        viewRevision = revision;
        const ratio = Math.max(0, Math.min(1, Number(result.ratio) || 0));
        const maxScroll = Math.max(0, editorText.scrollHeight - editorText.clientHeight);
        const target = maxScroll * ratio;
        if (Math.abs(editorText.scrollTop - target) > 2) {
          viewRemoteApplying = true;
          editorText.scrollTop = target;
          frame(() => { viewRemoteApplying = false; });
        }
      } finally { viewSyncBusy = false; }
    }

    function layout({ boardCollapsed = false, rootRect } = {}) {
      element.hidden = Boolean(boardCollapsed);
      if (boardCollapsed || !rootRect) return Object.freeze({ left: 8, collapsed });
      const width = Math.min(300, Math.max(220, rootRect.left - 24));
      const effectiveWidth = collapsed ? 50 : width;
      const left = Math.max(8, Math.round(rootRect.left - effectiveWidth - 8));
      element.style.width = `${Math.round(width)}px`;
      element.style.top = `${Math.round(rootRect.top)}px`;
      element.style.left = `${left}px`;
      element.classList.toggle("collapsed", collapsed);
      collapseButton.classList.toggle("is-collapsed", collapsed);
      collapseButton.title = collapsed ? "메모 펼치기" : "메모 접기";
      collapseButton.setAttribute("aria-label", collapseButton.title);
      if (collapsed) {
        element.style.width = "50px";
        element.style.minWidth = "50px";
        element.style.height = "40px";
        element.style.minHeight = "40px";
      } else {
        element.style.minWidth = "220px";
        element.style.minHeight = "180px";
        element.style.height = `${Math.round(rootRect.height)}px`;
      }
      return Object.freeze({ left, collapsed });
    }

    function restoreNote(note) {
      if (!note?.id || notes.some((item) => item.id === String(note.id))) return false;
      const restored = { ...note, id: String(note.id) };
      delete restored.trashed_at_ms;
      notes.push(restored);
      localDirty = true;
      queueSave();
      renderList();
      return true;
    }

    collapseButton.addEventListener("click", () => { collapsed = !collapsed; requestLayout(); });
    addButton.addEventListener("click", createNote);
    backButton.addEventListener("click", () => { updateActiveFromEditor(); queueSave(); showList(); highlightLastViewed(); });
    deleteButton.addEventListener("click", () => {
      const id = activeNoteId;
      if (!id) return;
      const note = notes.find((item) => item.id === id);
      if (note) trash({ ...note });
      notes = notes.filter((item) => item.id !== id);
      history.delete(id);
      localDirty = true;
      queueSave();
      showList();
    });
    undoButton.addEventListener("click", () => { if (listMode) undoListChange(); else undoEdit(); });
    redoButton.addEventListener("click", () => { if (listMode) redoListChange(); else redoEdit(); });
    editor.addEventListener("keydown", (event) => {
      if (!event.ctrlKey || event.altKey || event.metaKey) return;
      const key = String(event.key || "").toLowerCase();
      if (key === "z") { event.preventDefault(); if (event.shiftKey) redoEdit(); else undoEdit(); }
      else if (key === "y") { event.preventDefault(); redoEdit(); }
    });
    element.addEventListener("keydown", (event) => {
      if (!listMode || !event.ctrlKey || event.altKey || event.metaKey) return;
      const key = String(event.key || "").toLowerCase();
      if (key === "z") { event.preventDefault(); if (event.shiftKey) redoListChange(); else undoListChange(); }
      else if (key === "y") { event.preventDefault(); redoListChange(); }
    });
    aiButton.addEventListener("click", organizeWithAi);
    editorText.addEventListener("scroll", (event) => {
      if (viewRemoteApplying || !event.isTrusted) return;
      cancelLater(viewSaveTimer);
      viewSaveTimer = later(async () => {
        const result = await sharedNotePort.setView(String(scrollRatio())).catch(() => null);
        if (result?.ok && result.revision) viewRevision = String(result.revision);
      }, 80);
    });
    editorText.addEventListener("input", (event) => {
      requestLayout();
      if (!event.isTrusted || !ready || listMode) return;
      recordUndoBeforeEdit();
      updateActiveFromEditor();
      queueSave();
      syncHistoryButtons();
    });

    showList();

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      cancelLater(saveTimer);
      cancelLater(viewSaveTimer);
      if (dragFrame) cancel(dragFrame);
      element.remove();
    }

    return Object.freeze({
      element,
      layout,
      refreshContent,
      refreshView,
      restoreNote,
      titleFromText,
      destroy,
      snapshot: () => Object.freeze({ noteCount: notes.length, activeNoteId, listMode, collapsed, ready, localDirty }),
    });
  }

  root.MonitorNotesFeature = Object.freeze({ create, titleFromText });
})(globalThis);
