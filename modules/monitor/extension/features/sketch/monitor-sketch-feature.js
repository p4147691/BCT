"use strict";
(function installMonitorSketchFeature(root) {
  const STORAGE_KEY = "desktopWindowMonitorSketchV1";
  const TEXT_SIZES = Object.freeze({ small: 14, medium: 20, large: 28 });
  const TEXT_LONG_PRESS_MS = 450;
  const HISTORY_LIMIT = 24;

  function create({
    document: doc,
    storage,
    ImageCtor,
    requestFrame,
    setTimer,
    clearTimer,
    onLayoutChange,
  } = {}) {
    if (!doc?.createElement) throw new Error("MONITOR_SKETCH_DOCUMENT_REQUIRED");
    if (!storage || typeof storage.get !== "function" || typeof storage.set !== "function" ||
        typeof storage.remove !== "function") throw new Error("MONITOR_SKETCH_STORAGE_PORT_REQUIRED");
    if (typeof ImageCtor !== "function") throw new Error("MONITOR_SKETCH_IMAGE_PORT_REQUIRED");
    const scheduleFrame = typeof requestFrame === "function" ? requestFrame : (callback) => callback();
    const scheduleTimer = typeof setTimer === "function" ? setTimer : root.setTimeout.bind(root);
    const cancelTimer = typeof clearTimer === "function" ? clearTimer : root.clearTimeout.bind(root);
    const requestLayout = typeof onLayoutChange === "function" ? onLayoutChange : () => {};

    const element = doc.createElement("aside");
    element.className = "monitor-sketchpad";
    element.setAttribute("aria-label", "간단 그림판");
    element.innerHTML = `<div class="monitor-sketch-title"><span>그림</span><button id="monitorSketchCollapse" type="button" class="monitor-sketch-icon-btn monitor-sketch-collapse" title="그림판 접기" aria-label="그림판 접기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 14l6-6 6 6"/></svg></button></div><div class="monitor-sketch-tools" role="toolbar" aria-label="그림판 도구"><div class="monitor-sketch-tool-row"><button id="monitorSketchPen" type="button" class="monitor-sketch-icon-btn active" title="펜" aria-label="펜"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l4.5-1 10-10-3.5-3.5-10 10L4 20zM13.8 6.7l3.5 3.5"/></svg></button><button id="monitorSketchEraser" type="button" class="monitor-sketch-icon-btn" title="지우개" aria-label="지우개"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17l-3-3 8.5-8.5a2 2 0 012.8 0l3.2 3.2a2 2 0 010 2.8L12 18H8l-1-1zM10 18h10"/></svg></button><button id="monitorSketchLine" type="button" class="monitor-sketch-icon-btn" title="직선" aria-label="직선"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 19L19 5"/></svg></button><button id="monitorSketchRect" type="button" class="monitor-sketch-icon-btn" title="사각형" aria-label="사각형"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="6" width="14" height="12" rx="1"/></svg></button></div><div class="monitor-sketch-tool-row monitor-sketch-history-row"><button id="monitorSketchText" type="button" class="monitor-sketch-icon-btn" title="글자 · 길게 눌러 크기 선택" aria-label="글자" aria-haspopup="menu" aria-expanded="false"><span class="monitor-sketch-text-tool-label">가</span></button><button id="monitorSketchUndo" type="button" class="monitor-sketch-icon-btn" title="되돌리기" aria-label="되돌리기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7L4 12l5 5M5 12h8a6 6 0 016 6"/></svg></button><button id="monitorSketchRedo" type="button" class="monitor-sketch-icon-btn" title="다시하기" aria-label="다시하기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 7l5 5-5 5M19 12h-8a6 6 0 00-6 6"/></svg></button><button id="monitorSketchClear" type="button" class="monitor-sketch-icon-btn monitor-sketch-danger" title="전체 지우기" aria-label="전체 지우기"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 10v8M12 10v8M16 10v8M7 7l1 13h8l1-13"/></svg></button></div><div id="monitorSketchTextSizeMenu" class="monitor-sketch-text-size-menu" role="menu" aria-label="글자 크기" hidden><button id="monitorSketchTextSmall" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn" role="menuitem" title="작은 글자" aria-label="작은 글자"><span class="monitor-sketch-text-size-label small">가</span></button><button id="monitorSketchTextMedium" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn active" role="menuitem" title="보통 글자" aria-label="보통 글자"><span class="monitor-sketch-text-size-label medium">가</span></button><button id="monitorSketchTextLarge" type="button" class="monitor-sketch-icon-btn monitor-sketch-text-size-btn" role="menuitem" title="큰 글자" aria-label="큰 글자"><span class="monitor-sketch-text-size-label large">가</span></button></div></div><div class="monitor-sketch-canvas-wrap"><canvas id="monitorSketchCanvas" width="900" height="1200" aria-label="자유 낙서 영역"></canvas><canvas id="monitorSketchOverlay" width="900" height="1200" aria-hidden="true"></canvas><div id="monitorSketchCursor" class="monitor-sketch-cursor pen" aria-hidden="true"></div><input id="monitorSketchTextInput" class="monitor-sketch-text-input" type="text" maxlength="120" autocomplete="off" spellcheck="false" aria-label="그림판 글자 입력" hidden></div>`;

    const query = (selector) => {
      const node = element.querySelector(selector);
      if (!node) throw new Error(`MONITOR_SKETCH_MOUNT_MISSING:${selector}`);
      return node;
    };
    const canvas = query("#monitorSketchCanvas");
    const overlay = query("#monitorSketchOverlay");
    const context = canvas.getContext("2d");
    const overlayContext = overlay.getContext("2d");
    if (!context || !overlayContext) throw new Error("MONITOR_SKETCH_CANVAS_CONTEXT_MISSING");
    const pen = query("#monitorSketchPen");
    const eraser = query("#monitorSketchEraser");
    const line = query("#monitorSketchLine");
    const rect = query("#monitorSketchRect");
    const textTool = query("#monitorSketchText");
    const textSmall = query("#monitorSketchTextSmall");
    const textMedium = query("#monitorSketchTextMedium");
    const textLarge = query("#monitorSketchTextLarge");
    const textSizeMenu = query("#monitorSketchTextSizeMenu");
    const undo = query("#monitorSketchUndo");
    const redo = query("#monitorSketchRedo");
    const clear = query("#monitorSketchClear");
    const collapse = query("#monitorSketchCollapse");
    const textInput = query("#monitorSketchTextInput");
    const cursor = query("#monitorSketchCursor");

    let tool = "pen";
    let drawing = false;
    let collapsed = false;
    let startPoint = null;
    let textSize = "medium";
    let textPoint = null;
    let textLongPressTimer = null;
    let suppressTextClick = false;
    let destroyed = false;
    const undoStack = [];
    const redoStack = [];

    function hideTextSizeMenu() {
      textSizeMenu.hidden = true;
      textTool.setAttribute("aria-expanded", "false");
    }

    function setTool(nextTool) {
      tool = ["pen", "eraser", "line", "rect", "text"].includes(nextTool) ? nextTool : "pen";
      pen.classList.toggle("active", tool === "pen");
      eraser.classList.toggle("active", tool === "eraser");
      line.classList.toggle("active", tool === "line");
      rect.classList.toggle("active", tool === "rect");
      textTool.classList.toggle("active", tool === "text");
      cursor.classList.toggle("pen", tool === "pen");
      cursor.classList.toggle("eraser", tool === "eraser");
      cursor.classList.toggle("shape", tool === "line" || tool === "rect");
      cursor.classList.toggle("text", tool === "text");
      if (tool !== "text") hideTextSizeMenu();
    }

    function setTextSize(size) {
      textSize = TEXT_SIZES[size] ? size : "medium";
      textSmall.classList.toggle("active", textSize === "small");
      textMedium.classList.toggle("active", textSize === "medium");
      textLarge.classList.toggle("active", textSize === "large");
      const cssSize = TEXT_SIZES[textSize];
      cursor.style.setProperty("--monitor-sketch-text-caret-height", `${cssSize}px`);
      if (!textInput.hidden) textInput.style.fontSize = `${cssSize}px`;
    }

    function showTextSizeMenu() {
      setTool("text");
      textSizeMenu.hidden = false;
      textTool.setAttribute("aria-expanded", "true");
    }

    function startTextLongPress(event) {
      if (event.button !== 0) return;
      if (textLongPressTimer) cancelTimer(textLongPressTimer);
      suppressTextClick = false;
      textLongPressTimer = scheduleTimer(() => {
        textLongPressTimer = null;
        suppressTextClick = true;
        showTextSizeMenu();
      }, TEXT_LONG_PRESS_MS);
    }

    function stopTextLongPress() {
      if (!textLongPressTimer) return;
      cancelTimer(textLongPressTimer);
      textLongPressTimer = null;
    }

    function point(event) {
      const bounds = canvas.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return null;
      return {
        x: (event.clientX - bounds.left) * canvas.width / bounds.width,
        y: (event.clientY - bounds.top) * canvas.height / bounds.height,
        scale: canvas.width / bounds.width,
      };
    }

    function cssPoint(value) {
      const canvasRect = canvas.getBoundingClientRect();
      const wrapRect = canvas.parentElement.getBoundingClientRect();
      if (!value || !canvasRect.width || !canvasRect.height) return null;
      return {
        left: canvasRect.left - wrapRect.left + value.x * canvasRect.width / canvas.width,
        top: canvasRect.top - wrapRect.top + value.y * canvasRect.height / canvas.height,
      };
    }

    function updateCursor(event) {
      const canvasRect = canvas.getBoundingClientRect();
      const value = point(event);
      const position = cssPoint(value);
      if (!position || !canvasRect.width || !canvasRect.height) return;
      cursor.style.left = `${position.left}px`;
      cursor.style.top = `${position.top}px`;
      if (tool === "eraser") {
        const scale = canvas.width / canvasRect.width;
        const eraseCssPx = Math.max(12, 4 / Math.max(scale, 0.001));
        cursor.style.width = `${eraseCssPx}px`;
        cursor.style.height = `${eraseCssPx}px`;
      } else {
        cursor.style.width = "";
        cursor.style.height = "";
      }
      if (tool === "text") cursor.style.setProperty("--monitor-sketch-text-caret-height", `${TEXT_SIZES[textSize]}px`);
      cursor.classList.add("visible");
    }

    function clearOverlay() {
      overlayContext.clearRect(0, 0, overlay.width, overlay.height);
    }

    function prepareShapeContext(target, value) {
      target.globalCompositeOperation = "source-over";
      target.strokeStyle = "#000000";
      target.lineCap = "round";
      target.lineJoin = "round";
      target.lineWidth = Math.max(4, value.scale * 2.5);
    }

    function drawShape(target, value) {
      if (!startPoint) return;
      if (tool === "line") {
        target.beginPath();
        target.moveTo(startPoint.x, startPoint.y);
        target.lineTo(value.x, value.y);
        target.stroke();
        target.closePath();
        return;
      }
      if (tool === "rect") {
        const x = Math.min(startPoint.x, value.x);
        const y = Math.min(startPoint.y, value.y);
        target.strokeRect(x, y, Math.abs(value.x - startPoint.x), Math.abs(value.y - startPoint.y));
      }
    }

    function drawPreview(value) {
      clearOverlay();
      prepareShapeContext(overlayContext, value);
      drawShape(overlayContext, value);
    }

    function commitShape(value) {
      prepareShapeContext(context, value);
      drawShape(context, value);
      clearOverlay();
    }

    function canvasSnapshot() {
      try { return canvas.toDataURL("image/png"); } catch (_) { return ""; }
    }

    function updateHistoryButtons() {
      undo.disabled = undoStack.length === 0;
      redo.disabled = redoStack.length === 0;
    }

    function remember() {
      const saved = canvasSnapshot();
      if (!saved) return;
      if (undoStack[undoStack.length - 1] !== saved) {
        undoStack.push(saved);
        if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
      }
      redoStack.length = 0;
      updateHistoryButtons();
    }

    function save() {
      const saved = canvasSnapshot();
      if (saved) storage.set(STORAGE_KEY, saved);
    }

    function applySnapshot(saved) {
      if (!saved) return;
      const image = new ImageCtor();
      image.onload = () => {
        context.save();
        context.globalCompositeOperation = "source-over";
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        context.restore();
        clearOverlay();
        save();
      };
      image.src = saved;
    }

    function undoAction() {
      if (!undoStack.length) return;
      const current = canvasSnapshot();
      const previous = undoStack.pop();
      if (current) {
        redoStack.push(current);
        if (redoStack.length > HISTORY_LIMIT) redoStack.shift();
      }
      applySnapshot(previous);
      updateHistoryButtons();
    }

    function redoAction() {
      if (!redoStack.length) return;
      const current = canvasSnapshot();
      const next = redoStack.pop();
      if (current) {
        undoStack.push(current);
        if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
      }
      applySnapshot(next);
      updateHistoryButtons();
    }

    function restore() {
      const saved = storage.get(STORAGE_KEY) || "";
      if (!saved) return;
      const image = new ImageCtor();
      image.onload = () => context.drawImage(image, 0, 0, canvas.width, canvas.height);
      image.src = saved;
    }

    function cancelText() {
      textInput.hidden = true;
      textInput.value = "";
      textPoint = null;
    }

    function textLeftBearing(value, at) {
      if (!value || !at) return 0;
      const fontSize = Math.max(1, at.scale * TEXT_SIZES[textSize]);
      context.save();
      context.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
      const metrics = context.measureText(value);
      context.restore();
      return Number(metrics.actualBoundingBoxLeft) || 0;
    }

    function syncTextInputBearing() {
      if (textInput.hidden || !textPoint) return;
      const position = cssPoint(textPoint);
      if (!position) return;
      const bearingCss = textLeftBearing(textInput.value, textPoint) / Math.max(textPoint.scale, 0.001);
      textInput.style.left = `${position.left + bearingCss}px`;
    }

    function commitText() {
      if (textInput.hidden || !textPoint) return;
      const value = textInput.value;
      const at = textPoint;
      textInput.hidden = true;
      textInput.value = "";
      textPoint = null;
      if (!value) return;
      remember();
      const fontSize = Math.max(1, at.scale * TEXT_SIZES[textSize]);
      context.save();
      context.globalCompositeOperation = "source-over";
      context.fillStyle = "#000000";
      context.font = `${fontSize}px "Malgun Gothic","Segoe UI",sans-serif`;
      context.textBaseline = "alphabetic";
      const metrics = context.measureText(value);
      const fontAscent = Number(metrics.fontBoundingBoxAscent) || fontSize * 0.8;
      const fontDescent = Number(metrics.fontBoundingBoxDescent) || fontSize * 0.2;
      const lineBoxOffset = (fontSize - (fontAscent + fontDescent)) / 2;
      const leftBearing = Number(metrics.actualBoundingBoxLeft) || 0;
      context.fillText(value, at.x + leftBearing, at.y + fontAscent + lineBoxOffset);
      context.restore();
      save();
    }

    function beginText(value) {
      commitText();
      const canvasRect = canvas.getBoundingClientRect();
      const wrapRect = canvas.parentElement.getBoundingClientRect();
      const position = cssPoint(value);
      if (!position) return;
      textPoint = value;
      textInput.value = "";
      textInput.style.left = `${position.left}px`;
      textInput.style.top = `${position.top}px`;
      textInput.style.width = `${Math.max(32, Math.min(180, canvasRect.right - (wrapRect.left + position.left)))}px`;
      textInput.style.fontSize = `${TEXT_SIZES[textSize]}px`;
      textInput.hidden = false;
      scheduleFrame(() => {
        try { textInput.focus({ preventScroll: true }); } catch (_) { textInput.focus(); }
      });
    }

    function stop(event) {
      if (!drawing) return;
      const value = event?.type === "pointercancel" ? null : point(event);
      if (value && (tool === "line" || tool === "rect")) commitShape(value);
      else clearOverlay();
      drawing = false;
      startPoint = null;
      try { if (event?.pointerId != null) canvas.releasePointerCapture(event.pointerId); } catch (_) {}
      context.closePath();
      context.globalCompositeOperation = "source-over";
      save();
    }

    function applyCollapsedState() {
      element.classList.toggle("collapsed", collapsed);
      collapse.classList.toggle("is-collapsed", collapsed);
      collapse.title = collapsed ? "그림판 펼치기" : "그림판 접기";
      collapse.setAttribute("aria-label", collapse.title);
    }

    function layout({ boardCollapsed = false, rootRect, noteLeft } = {}) {
      element.hidden = Boolean(boardCollapsed);
      if (boardCollapsed || !rootRect) return;
      const resolvedNoteLeft = Number.isFinite(Number(noteLeft)) ? Number(noteLeft) : 8;
      const width = Math.min(280, Math.max(180, resolvedNoteLeft - 16));
      const effectiveWidth = collapsed ? 50 : width;
      element.style.width = `${Math.round(width)}px`;
      element.style.top = `${Math.round(rootRect.top)}px`;
      element.style.left = `${Math.max(8, Math.round(resolvedNoteLeft - effectiveWidth - 8))}px`;
      element.style.height = collapsed ? "40px" : `${Math.round(rootRect.height)}px`;
      element.style.minWidth = collapsed ? "50px" : "180px";
      element.style.minHeight = collapsed ? "40px" : "180px";
      applyCollapsedState();
    }

    canvas.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const value = point(event);
      if (!value) return;
      event.preventDefault();
      if (tool === "text") {
        hideTextSizeMenu();
        beginText(value);
        return;
      }
      remember();
      drawing = true;
      startPoint = value;
      canvas.setPointerCapture(event.pointerId);
      if (tool === "line" || tool === "rect") {
        clearOverlay();
        return;
      }
      context.beginPath();
      context.moveTo(value.x, value.y);
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = Math.max(4, value.scale * (tool === "eraser" ? 12 : 2.5));
      context.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
      context.strokeStyle = "#000000";
    });
    canvas.addEventListener("pointermove", (event) => {
      updateCursor(event);
      if (!drawing) return;
      const value = point(event);
      if (!value) return;
      event.preventDefault();
      if (tool === "line" || tool === "rect") {
        drawPreview(value);
        return;
      }
      context.lineTo(value.x, value.y);
      context.stroke();
    });
    canvas.addEventListener("pointerenter", updateCursor);
    canvas.addEventListener("pointerleave", () => cursor.classList.remove("visible"));
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);
    pen.addEventListener("click", () => setTool("pen"));
    eraser.addEventListener("click", () => setTool("eraser"));
    line.addEventListener("click", () => setTool("line"));
    rect.addEventListener("click", () => setTool("rect"));
    textTool.addEventListener("pointerdown", startTextLongPress);
    textTool.addEventListener("pointerup", stopTextLongPress);
    textTool.addEventListener("pointercancel", stopTextLongPress);
    textTool.addEventListener("pointerleave", stopTextLongPress);
    textTool.addEventListener("click", (event) => {
      if (suppressTextClick) {
        suppressTextClick = false;
        event.preventDefault();
        return;
      }
      hideTextSizeMenu();
      setTool("text");
    });
    [[textSmall, "small"], [textMedium, "medium"], [textLarge, "large"]].forEach(([button, size]) => {
      button.addEventListener("pointerdown", (event) => event.preventDefault());
      button.addEventListener("click", () => {
        setTextSize(size);
        setTool("text");
        hideTextSizeMenu();
      });
    });
    const onDocumentPointerDown = (event) => {
      if (textSizeMenu.hidden) return;
      if (textSizeMenu.contains(event.target) || textTool.contains(event.target)) return;
      hideTextSizeMenu();
    };
    doc.addEventListener("pointerdown", onDocumentPointerDown, true);
    textInput.addEventListener("input", syncTextInputBearing);
    textInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        commitText();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancelText();
      }
    });
    textInput.addEventListener("blur", commitText);
    undo.addEventListener("click", undoAction);
    redo.addEventListener("click", redoAction);
    clear.addEventListener("click", () => {
      remember();
      context.clearRect(0, 0, canvas.width, canvas.height);
      clearOverlay();
      storage.remove(STORAGE_KEY);
    });
    collapse.addEventListener("click", () => {
      collapsed = !collapsed;
      applyCollapsedState();
      requestLayout();
    });

    restore();
    setTextSize("medium");
    setTool("pen");
    updateHistoryButtons();
    applyCollapsedState();

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      stopTextLongPress();
      doc.removeEventListener("pointerdown", onDocumentPointerDown, true);
      element.remove();
    }

    return Object.freeze({
      element,
      layout,
      destroy,
      snapshot: () => Object.freeze({ tool, textSize, collapsed, undoDepth: undoStack.length, redoDepth: redoStack.length }),
    });
  }

  root.MonitorSketchFeature = Object.freeze({ create });
})(globalThis);
