const grid = document.getElementById("desktopGrid");
const main = document.querySelector("main");
const emptyPanel = document.getElementById("emptyPanel");
const errorPanel = document.getElementById("errorPanel");
const refreshButton = document.getElementById("refreshButton");
const statusLabel = document.getElementById("status");
const selectionBox = document.getElementById("selectionBox");
const toast = document.getElementById("toast");
const textViewer = document.getElementById("textViewer");
const textViewerName = document.getElementById("textViewerName");
const textViewerPath = document.getElementById("textViewerPath");
const textViewerContent = document.getElementById("textViewerContent");
const textViewerClose = document.getElementById("textViewerClose");
const folderNav = document.getElementById("folderNav");
const folderBack = document.getElementById("folderBack");
const folderUp = document.getElementById("folderUp");
const folderPath = document.getElementById("folderPath");
const folderName = document.getElementById("folderName");

const TEXT_EXTENSIONS = new Set([
  ".html", ".htm", ".py", ".txt", ".md", ".json", ".css", ".js", ".mjs", ".cjs",
  ".ts", ".tsx", ".jsx", ".xml", ".yaml", ".yml", ".csv", ".log", ".ini", ".cfg",
  ".conf", ".toml", ".sql", ".ps1", ".bat", ".cmd", ".sh", ".c", ".cpp", ".h",
  ".hpp", ".cs", ".java", ".rb", ".go", ".rs", ".php", ".vue", ".svelte"
]);

let refreshInProgress = false;
let toastTimer = null;
let rightClickState = null;
let renameState = null;
let marqueeState = null;
let selectedPaths = new Set();
let itemsByPath = new Map();
let buttonsByPath = new Map();
let iconCache = new Map();
let createInProgress = false;
let desktopMutationVersion = 0;
const CREATED_TAIL_STORAGE_KEY = "desktopWindowCreatedTailPaths.v1";
let createdTailPaths = loadCreatedTailPaths();
let undoStack = [];
let redoStack = [];
let draggedPaths = [];
let lastMiddleActivation = { path: null, time: 0 };
let currentDirectory = null;
let currentParentDirectory = null;
let folderHistory = [];

async function request(message) {
  return chrome.runtime.sendMessage(message);
}

function updateFolderViewState() {
  const active = typeof currentDirectory === "string" && currentDirectory.length > 0;
  document.body.classList.toggle("folder-view-active", active);
  if (folderNav) folderNav.hidden = !active;
  if (folderPath) {
    folderPath.textContent = active ? currentDirectory : "";
    folderPath.title = active ? currentDirectory : "";
  }
  if (folderName) {
    const normalized = active ? currentDirectory.replace(/\\/g, "/").replace(/\/+$/, "") : "";
    const name = normalized ? normalized.slice(normalized.lastIndexOf("/") + 1) : "";
    folderName.textContent = name || "폴더";
  }
  if (folderBack) folderBack.disabled = folderHistory.length === 0;
  if (folderUp) folderUp.disabled = !active;
  window.dispatchEvent(new CustomEvent("desktop-folder-view-changed", { detail: { active } }));
}

async function navigateToDirectory(path, pushHistory = true) {
  const previous = currentDirectory;
  if (pushHistory) folderHistory.push(previous);
  currentDirectory = path || null;
  currentParentDirectory = null;
  updateFolderViewState();
  const ok = await refreshDesktop({ includeVisuals: true, navigation: true });
  if (ok) return;
  currentDirectory = previous;
  if (pushHistory) folderHistory.pop();
  updateFolderViewState();
  await refreshDesktop({ includeVisuals: true });
}

async function navigateBack() {
  if (folderHistory.length === 0) return;
  const target = folderHistory.pop();
  currentDirectory = target || null;
  currentParentDirectory = null;
  updateFolderViewState();
  await refreshDesktop({ includeVisuals: true, navigation: true });
}

async function navigateUp() {
  if (!currentDirectory) return;
  await navigateToDirectory(currentParentDirectory || null, true);
}

function setError(message) {
  errorPanel.textContent = message;
  errorPanel.hidden = !message;
}

function showToast(message, isError = false) {
  if (toastTimer) clearTimeout(toastTimer);
  toast.textContent = message;
  toast.style.borderColor = isError ? "rgba(255, 116, 116, 0.75)" : "rgba(255, 255, 255, 0.2)";
  toast.hidden = false;
  toastTimer = setTimeout(() => {
    toast.hidden = true;
    toastTimer = null;
  }, isError ? 1800 : 1000);
}

function isPhysicalItem(item) {
  return item && item.kind !== "system" && typeof item.path === "string";
}

function isSupportedTextItem(item) {
  if (!isPhysicalItem(item) || item.kind === "folder") return false;
  const dot = item.name.lastIndexOf(".");
  if (dot < 0) return false;
  return TEXT_EXTENSIONS.has(item.name.slice(dot).toLowerCase());
}

function setItemSelected(path, selected) {
  const button = buttonsByPath.get(path);
  if (!button) return;

  if (selected) {
    selectedPaths.add(path);
    button.classList.add("selected");
    button.setAttribute("aria-selected", "true");
  } else {
    selectedPaths.delete(path);
    button.classList.remove("selected");
    button.setAttribute("aria-selected", "false");
  }
}

function clearSelection() {
  for (const path of [...selectedPaths]) setItemSelected(path, false);
}

function selectOnly(path) {
  clearSelection();
  setItemSelected(path, true);
}

function toggleSelection(path) {
  setItemSelected(path, !selectedPaths.has(path));
}

function getSelectedItems() {
  return [...selectedPaths].map((path) => itemsByPath.get(path)).filter(Boolean);
}

async function copyText(value, message) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    showToast(message);
  } catch (error) {
    showToast("클립보드 복사 실패", true);
  }
}

function normalizePathKey(path) {
  return typeof path === "string"
    ? path.replace(/\\/g, "/").normalize("NFC").toLowerCase()
    : "";
}

function loadCreatedTailPaths() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CREATED_TAIL_STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string") : [];
  } catch (_) {
    return [];
  }
}

function saveCreatedTailPaths() {
  localStorage.setItem(CREATED_TAIL_STORAGE_KEY, JSON.stringify(createdTailPaths));
}

function pinCreatedPath(path) {
  if (!path) return;
  const key = normalizePathKey(path);
  createdTailPaths = createdTailPaths.filter((value) => normalizePathKey(value) !== key);
  createdTailPaths.push(path);
  // Missing entries are intentionally retained across refreshes because Windows can
  // report a newly-created text file a little later than the create response.
  if (createdTailPaths.length > 200) createdTailPaths = createdTailPaths.slice(-200);
  saveCreatedTailPaths();
}

function remapCreatedPath(from, to) {
  if (!from || !to || normalizePathKey(from) === normalizePathKey(to)) {
    if (from && to && from !== to) {
      const index = createdTailPaths.findIndex((value) => normalizePathKey(value) === normalizePathKey(from));
      if (index >= 0) {
        createdTailPaths[index] = to;
        saveCreatedTailPaths();
      }
    }
    return;
  }
  const fromKey = normalizePathKey(from);
  const index = createdTailPaths.findIndex((value) => normalizePathKey(value) === fromKey);
  if (index >= 0) {
    createdTailPaths[index] = to;
    const seen = new Set();
    createdTailPaths = createdTailPaths.filter((value) => {
      const key = normalizePathKey(value);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    saveCreatedTailPaths();
  }
  if (iconCache.has(from)) {
    iconCache.set(to, iconCache.get(from));
    iconCache.delete(from);
  }
}

function orderItemsForDisplay(items) {
  const byKey = new Map(items.map((item) => [normalizePathKey(item.path), item]));
  const tailKeys = new Set(createdTailPaths.map(normalizePathKey));
  const normal = items.filter((item) => !tailKeys.has(normalizePathKey(item.path)));
  const tail = createdTailPaths
    .map((path) => byKey.get(normalizePathKey(path)))
    .filter(Boolean);
  // Do not delete a remembered tail path just because a single directory refresh
  // missed it. That race was causing new .txt files to fall back into normal sort.
  return normal.concat(tail);
}

function applyWallpaperInfo(info) {
  if (!info || typeof info !== "object") return;
  document.body.style.backgroundColor = info.backgroundColor || "#0b1728";

  if (typeof info.dataUri !== "string" || !info.dataUri.startsWith("data:image/jpeg;base64,")) {
    document.body.style.backgroundImage = "none";
    return;
  }

  document.body.style.backgroundImage = `url("${info.dataUri}")`;
  const mode = info.mode || "fill";
  const originalWidth = Number(info.originalWidth) || 0;
  const originalHeight = Number(info.originalHeight) || 0;
  const originalSize = originalWidth > 0 && originalHeight > 0
    ? `${originalWidth}px ${originalHeight}px`
    : "auto";

  if (mode === "tile") {
    document.body.style.backgroundSize = originalSize;
    document.body.style.backgroundPosition = "left top";
    document.body.style.backgroundRepeat = "repeat";
  } else if (mode === "center") {
    document.body.style.backgroundSize = originalSize;
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundRepeat = "no-repeat";
  } else if (mode === "stretch") {
    document.body.style.backgroundSize = "100% 100%";
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundRepeat = "no-repeat";
  } else if (mode === "fit") {
    document.body.style.backgroundSize = "contain";
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundRepeat = "no-repeat";
  } else {
    // Windows Fill and Span are both represented as a crop-to-cover view inside
    // this single Desktop Window. Span across multiple physical monitors cannot
    // be pixel-identical inside one browser window.
    document.body.style.backgroundSize = "cover";
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundRepeat = "no-repeat";
  }
}

async function copySelectedFiles() {
  const paths = getSelectedItems().filter(isPhysicalItem).map((item) => item.path);
  if (paths.length === 0) return;

  const response = await request({ type: "copyFiles", paths });
  if (!response?.ok) {
    showToast(response?.error || "파일을 복사할 수 없습니다.", true);
    return;
  }
  showToast(paths.length === 1 ? "파일 복사됨" : paths.length + "개 파일 복사됨");
}

function flushPendingRightClick() {
  if (!rightClickState) return;
  clearTimeout(rightClickState.timer);
  const pending = rightClickState;
  rightClickState = null;
  copyText(pending.item.name, "이름 복사됨");
}

function handleRightClick(event, item) {
  event.preventDefault();
  if (!selectedPaths.has(item.path)) selectOnly(item.path);

  if (rightClickState && rightClickState.item.path === item.path) {
    clearTimeout(rightClickState.timer);
    rightClickState = null;
    copyText(item.path, "전체 경로 복사됨");
    return;
  }

  if (rightClickState) flushPendingRightClick();

  rightClickState = {
    item,
    timer: setTimeout(() => {
      const pending = rightClickState;
      rightClickState = null;
      if (pending) copyText(pending.item.name, "이름 복사됨");
    }, 310)
  };
}

function createIcon(item) {
  const iconData = typeof item.icon === "string" && item.icon.startsWith("data:image/png;base64,")
    ? item.icon
    : iconCache.get(item.path);

  if (typeof iconData === "string" && iconData.startsWith("data:image/png;base64,")) {
    if (item.icon === iconData) iconCache.set(item.path, iconData);
    const image = document.createElement("img");
    image.src = iconData;
    image.alt = "";
    image.draggable = false;
    return image;
  }

  const fallback = document.createElement("span");
  fallback.className = "fallback-icon";
  fallback.setAttribute("aria-hidden", "true");
  if (item.kind === "folder") fallback.textContent = "📁";
  else if (item.kind === "system" && item.name === "휴지통") fallback.textContent = "♻️";
  else if (item.kind === "system") fallback.textContent = "🖥️";
  else fallback.textContent = "📄";
  return fallback;
}

function updateDesktopRows() {
  const availableHeight = Math.max(126, window.innerHeight - 20);
  const rowCount = Math.max(1, Math.floor(availableHeight / 129));
  grid.style.gridTemplateRows = "repeat(" + rowCount + ", 126px)";
}

async function openItem(item, button, forceExternal = false) {
  if (item?.kind === "folder" && !forceExternal) {
    await navigateToDirectory(item.path, true);
    return;
  }

  button.disabled = true;
  statusLabel.textContent = item.name + " 여는 중…";
  try {
    const response = await request({ type: "open", path: item.path });
    if (!response?.ok) throw new Error(response?.error || "항목을 열 수 없습니다.");
    statusLabel.textContent = item.name + " 열기 완료";
  } catch (error) {
    showToast(error?.message || "항목을 열 수 없습니다.", true);
    statusLabel.textContent = "열기 실패";
  } finally {
    button.disabled = false;
  }
}

async function openTextViewer(item) {
  if (!isSupportedTextItem(item)) return;
  statusLabel.textContent = item.name + " 텍스트 읽는 중…";
  try {
    const response = await request({ type: "readText", path: item.path });
    if (!response?.ok) throw new Error(response?.error || "텍스트로 열 수 없습니다.");
    textViewerName.textContent = response.name || item.name;
    textViewerPath.textContent = response.path || item.path;
    textViewerContent.value = response.content || "";
    textViewer.hidden = false;
    textViewerContent.scrollTop = 0;
    textViewerContent.scrollLeft = 0;
    textViewerContent.focus();
    statusLabel.textContent = item.name + " 텍스트 보기";
  } catch (error) {
    const message = error?.message || String(error);
    showToast(message, true);
    statusLabel.textContent = "텍스트 열기 실패";
  }
}

function closeTextViewer() {
  textViewer.hidden = true;
  textViewerContent.value = "";
  textViewerName.textContent = "";
  textViewerPath.textContent = "";
}

function handleMiddleClick(event, item) {
  if (event.button !== 1) return;
  event.preventDefault();
  event.stopPropagation();

  const now = Date.now();
  if (lastMiddleActivation.path === item.path && now - lastMiddleActivation.time < 450) return;
  lastMiddleActivation = { path: item.path, time: now };
  openTextViewer(item);
}

function recordOperation(operation) {
  if (!operation) return;
  undoStack.push(operation);
  if (undoStack.length > 50) undoStack.shift();
  redoStack = [];
}

async function applyHistory(direction) {
  const source = direction === "undo" ? undoStack : redoStack;
  const destination = direction === "undo" ? redoStack : undoStack;
  if (source.length === 0) return;

  const operation = source.pop();
  const response = await request({ type: direction, operation });
  if (!response?.ok) {
    source.push(operation);
    showToast(direction === "undo" ? "되돌릴 수 없습니다." : "다시 실행할 수 없습니다.", true);
    return;
  }

  destination.push(operation);
  showToast(direction === "undo" ? "되돌림 완료" : "다시 실행 완료");
  await refreshDesktop();
}

function cancelRename() {
  if (!renameState) return;
  const state = renameState;
  renameState = null;
  if (state.input.isConnected) state.input.replaceWith(state.originalLabel);
}

function sizeAndPositionRenameInput(input, button) {
  const style = getComputedStyle(input);
  const canvas = sizeAndPositionRenameInput.canvas || (sizeAndPositionRenameInput.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = style.font;

  const desiredWidth = Math.ceil(context.measureText(input.value || " ").width) + 24;
  const inputWidth = Math.max(88, Math.min(desiredWidth, window.innerWidth - 28));
  const buttonRect = button.getBoundingClientRect();
  const halfWidth = inputWidth / 2;

  input.style.width = inputWidth + "px";
  input.style.left = Math.max(14 + halfWidth, Math.min(window.innerWidth - 14 - halfWidth, buttonRect.left + buttonRect.width / 2)) + "px";
  input.style.top = buttonRect.top + 59 + "px";
}

async function commitRename() {
  if (!renameState || renameState.committing) return;
  const state = renameState;
  state.committing = true;
  const oldPath = state.item.path;
  const wasCreatedTail = createdTailPaths.some((path) => normalizePathKey(path) === normalizePathKey(oldPath));
  const newName = state.input.value;

  const response = await request({ type: "rename", path: oldPath, newName });
  renameState = null;

  if (!response?.ok) {
    showToast("이름을 변경할 수 없습니다.", true);
    if (state.input.isConnected) state.input.replaceWith(state.originalLabel);
    return;
  }

  const firstMove = response.operation?.moves?.[0];
  if (firstMove?.from && firstMove?.to) remapCreatedPath(firstMove.from, firstMove.to);
  if (response.operation) recordOperation(response.operation);

  // Newly-created items are already at the requested visual tail. Update the
  // existing DOM node in place instead of rebuilding the whole grid and risking
  // a Windows directory refresh racing the tail-order bookkeeping.
  if (wasCreatedTail && firstMove?.to) {
    const newPath = firstMove.to;
    const finalName = newPath.split(/[\\/]/).pop() || newName;
    state.item.path = newPath;
    state.item.name = finalName;
    state.button.title = newPath;

    itemsByPath.delete(oldPath);
    itemsByPath.set(newPath, state.item);
    buttonsByPath.delete(oldPath);
    buttonsByPath.set(newPath, state.button);
    if (selectedPaths.delete(oldPath)) selectedPaths.add(newPath);

    const label = document.createElement("span");
    label.className = "item-name";
    label.textContent = finalName;
    if (state.input.isConnected) state.input.replaceWith(label);

    showToast("이름 변경됨");
    statusLabel.textContent = "이름 변경됨";
    return;
  }

  showToast("이름 변경됨");
  await refreshDesktop({ includeVisuals: false });
}

function beginRename() {
  const selected = getSelectedItems();
  if (selected.length !== 1 || !isPhysicalItem(selected[0]) || renameState) return;

  const item = selected[0];
  const button = buttonsByPath.get(item.path);
  const label = button?.querySelector(".item-name");
  if (!button || !label) return;

  const input = document.createElement("input");
  input.className = "rename-input";
  input.value = item.name;
  input.setAttribute("aria-label", "새 이름");
  label.replaceWith(input);
  sizeAndPositionRenameInput(input, button);

  renameState = { item, button, input, originalLabel: label, committing: false };
  input.focus();

  if (item.kind === "folder") {
    input.select();
  } else {
    const dot = item.name.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : item.name.length);
  }

  input.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      commitRename();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
      button.focus();
    }
  });

  input.addEventListener("input", () => sizeAndPositionRenameInput(input, button));

  input.addEventListener("blur", () => {
    if (renameState && !renameState.committing) cancelRename();
  });
}

async function createDesktopItem(kind) {
  if (createInProgress) return;
  createInProgress = true;
  // Invalidate any directory refresh that started before this creation. A stale
  // response must never rebuild the grid after the new item has claimed the tail.
  desktopMutationVersion += 1;
  const isFolder = kind === "folder";
  const type = isFolder ? "createFolder" : "createFile";
  const progressText = isFolder ? "새 폴더 생성 중…" : "새 문서 생성 중…";
  statusLabel.textContent = progressText;
  showToast(progressText);

  try {
    // F3 and F4 deliberately share the exact same lifecycle. Do not insert an
    // F3-only placeholder: it caused a second visual slot followed by a full grid
    // rebuild, which made a new text file appear slower and jump to an ambiguous
    // location compared with the stable F4 folder path.
    const response = await request({ type, directory: currentDirectory });
    if (!response?.ok) {
      showToast(response?.error || (isFolder ? "새 폴더를 만들 수 없습니다." : "새 문서를 만들 수 없습니다."), true);
      return;
    }

    const item = {
      name: response.name || (isFolder ? "새 폴더" : "새 문서.txt"),
      path: response.path,
      kind: response.kind || (isFolder ? "folder" : "file"),
      icon: response.icon || null
    };
    if (typeof item.icon === "string" && item.icon.startsWith("data:image/png;base64,")) {
      iconCache.set(item.path, item.icon);
    }
    pinCreatedPath(item.path);

    const items = [...itemsByPath.values()].filter((existing) => existing.path !== item.path);
    items.push(item);
    // Keep the existing desktop DOM intact. Rebuilding every icon here made F3 feel
    // slow and gave an older refresh response a chance to move the new item again.
    const existingButton = buttonsByPath.get(item.path);
    if (existingButton?.isConnected) existingButton.remove();
    itemsByPath.delete(item.path);
    buttonsByPath.delete(item.path);
    selectedPaths.delete(item.path);
    appendRenderedItem(item);
    selectOnly(item.path);
    beginRename();
    statusLabel.textContent = isFolder ? "새 폴더 생성됨" : "새 문서 생성됨";
    showToast(isFolder ? "새 폴더 생성됨" : "새 문서 생성됨");
  } finally {
    createInProgress = false;
  }
}

async function deleteSelection() {
  const items = getSelectedItems().filter(isPhysicalItem);
  if (items.length === 0) return;

  const confirmed = window.confirm("선택한 " + items.length + "개 항목을 Windows 휴지통으로 이동할까요?");
  if (!confirmed) return;

  const response = await request({ type: "deleteItems", paths: items.map((item) => item.path) });
  if (!response?.ok) {
    showToast("휴지통으로 이동할 수 없습니다.", true);
    return;
  }

  undoStack = [];
  redoStack = [];
  showToast("휴지통으로 이동됨");
  await refreshDesktop();
}

async function moveSelectionToFolder(targetItem, requestedPaths = null) {
  if (targetItem.kind !== "folder") return;
  const paths = (requestedPaths || getSelectedItems()
    .filter(isPhysicalItem)
    .map((item) => item.path))
    .filter((path) => path !== targetItem.path);
  if (paths.length === 0) return;

  const response = await request({
    type: "moveItems",
    paths,
    targetDirectory: targetItem.path
  });

  if (!response?.ok) {
    showToast(response?.error || "파일을 이동할 수 없습니다.", true);
    return;
  }

  if (response.operation) recordOperation(response.operation);
  showToast("이동 완료");
  await refreshDesktop();
}

function configureDrag(button, item) {
  if (!isPhysicalItem(item)) return;
  button.draggable = true;

  button.addEventListener("dragstart", (event) => {
    if (!selectedPaths.has(item.path)) selectOnly(item.path);
    const paths = getSelectedItems().filter(isPhysicalItem).map((selected) => selected.path);
    draggedPaths = paths;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-desktop-window-paths", JSON.stringify(paths));
  });

  button.addEventListener("dragend", () => {
    draggedPaths = [];
    for (const target of grid.querySelectorAll(".drag-over")) target.classList.remove("drag-over");
  });

  if (item.kind === "folder") {
    button.addEventListener("dragover", (event) => {
      if (selectedPaths.has(item.path)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      button.classList.add("drag-over");
    });

    button.addEventListener("dragleave", () => button.classList.remove("drag-over"));
    button.addEventListener("drop", (event) => {
      event.preventDefault();
      button.classList.remove("drag-over");
      let paths = draggedPaths;
      try {
        const encoded = event.dataTransfer.getData("application/x-desktop-window-paths");
        const parsed = encoded ? JSON.parse(encoded) : null;
        if (Array.isArray(parsed)) paths = parsed;
      } catch (_) {
        // 현재 드래그 상태의 검증된 선택 경로를 사용합니다.
      }
      moveSelectionToFolder(item, paths);
      draggedPaths = [];
    });
  }
}

function appendRenderedItem(item) {
  itemsByPath.set(item.path, item);
  if (typeof item.icon === "string" && item.icon.startsWith("data:image/png;base64,")) {
    iconCache.set(item.path, item.icon);
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "desktop-item";
  button.title = item.path;
  button.setAttribute("aria-selected", "false");
  button.append(createIcon(item));

  const name = document.createElement("span");
  name.className = "item-name";
  name.textContent = item.name;
  button.append(name);
  buttonsByPath.set(item.path, button);

  button.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey) toggleSelection(item.path);
    else selectOnly(item.path);
  });

  button.addEventListener("dblclick", (event) => {
    event.preventDefault();
    if (isSupportedTextItem(item)) openTextViewer(item);
    else openItem(item, button);
  });
  button.addEventListener("mousedown", (event) => {
    if (event.button === 1) event.preventDefault();
  });
  button.addEventListener("mouseup", (event) => handleMiddleClick(event, item));
  button.addEventListener("auxclick", (event) => handleMiddleClick(event, item));
  button.addEventListener("contextmenu", (event) => handleRightClick(event, item));
  button.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !renameState) openItem(item, button, event.ctrlKey || event.metaKey);
  });

  configureDrag(button, item);
  grid.append(button);
  emptyPanel.hidden = true;
  return button;
}
function renderItems(items, previousSelection = new Set()) {
  const displayItems = orderItemsForDisplay(items);
  updateDesktopRows();
  grid.replaceChildren();
  itemsByPath = new Map();
  buttonsByPath = new Map();
  selectedPaths = new Set();
  emptyPanel.hidden = displayItems.length !== 0;

  for (const item of displayItems) {
    itemsByPath.set(item.path, item);
    if (typeof item.icon === "string" && item.icon.startsWith("data:image/png;base64,")) {
      iconCache.set(item.path, item.icon);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "desktop-item";
    button.title = item.path;
    button.setAttribute("aria-selected", "false");
    button.append(createIcon(item));

    const name = document.createElement("span");
    name.className = "item-name";
    name.textContent = item.name;
    button.append(name);
    buttonsByPath.set(item.path, button);

    button.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey) toggleSelection(item.path);
      else selectOnly(item.path);
    });

    button.addEventListener("dblclick", (event) => {
      event.preventDefault();
      if (isSupportedTextItem(item)) openTextViewer(item);
      else openItem(item, button);
    });
    button.addEventListener("mousedown", (event) => {
      if (event.button === 1) event.preventDefault();
    });
    button.addEventListener("mouseup", (event) => handleMiddleClick(event, item));
    button.addEventListener("auxclick", (event) => handleMiddleClick(event, item));
    button.addEventListener("contextmenu", (event) => handleRightClick(event, item));
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !renameState) openItem(item, button, event.ctrlKey || event.metaKey);
    });

    configureDrag(button, item);
    grid.append(button);

    if (previousSelection.has(item.path)) setItemSelected(item.path, true);
  }

  const currentPaths = new Set(displayItems.map((item) => item.path));
  for (const path of [...iconCache.keys()]) {
    if (!currentPaths.has(path)) iconCache.delete(path);
  }
}

function updateMarquee(event) {
  if (!marqueeState) return;
  const left = Math.min(marqueeState.startX, event.clientX);
  const top = Math.min(marqueeState.startY, event.clientY);
  const right = Math.max(marqueeState.startX, event.clientX);
  const bottom = Math.max(marqueeState.startY, event.clientY);
  const moved = right - left > 4 || bottom - top > 4;

  selectionBox.hidden = !moved;
  if (!moved) return;

  selectionBox.style.left = left + "px";
  selectionBox.style.top = top + "px";
  selectionBox.style.width = right - left + "px";
  selectionBox.style.height = bottom - top + "px";

  for (const [path, button] of buttonsByPath) {
    const rect = button.getBoundingClientRect();
    const intersects = rect.right >= left && rect.left <= right && rect.bottom >= top && rect.top <= bottom;
    setItemSelected(path, intersects || marqueeState.initialSelection.has(path));
  }
}

function endMarquee() {
  if (!marqueeState) return;
  marqueeState = null;
  selectionBox.hidden = true;
  document.removeEventListener("pointermove", updateMarquee);
  document.removeEventListener("pointerup", endMarquee);
}

main.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || renameState) return;
  if (event.target.closest(".desktop-item") || event.target.closest(".desktop-actions")) return;

  if (!event.ctrlKey && !event.metaKey) clearSelection();
  marqueeState = {
    startX: event.clientX,
    startY: event.clientY,
    initialSelection: (event.ctrlKey || event.metaKey) ? new Set(selectedPaths) : new Set()
  };
  selectionBox.hidden = true;
  document.addEventListener("pointermove", updateMarquee);
  document.addEventListener("pointerup", endMarquee);
  event.preventDefault();
});

async function refreshDesktop(options = {}) {
  if (refreshInProgress && options.navigation) {
    for (let i = 0; i < 40 && refreshInProgress; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  if (refreshInProgress || renameState || createInProgress) return false;
  const includeVisuals = options.includeVisuals !== false;
  const mutationVersionAtStart = desktopMutationVersion;
  refreshInProgress = true;
  refreshButton.disabled = true;
  statusLabel.textContent = "새로고침 중…";
  setError("");
  const previousSelection = new Set(selectedPaths);

  try {
    const message = currentDirectory
      ? { type: "listDirectory", path: currentDirectory, includeVisuals }
      : { type: "list", includeVisuals };
    let response = await request(message);
    // Immediately after an extension reload the Native helper can still be
    // reconnecting. Retry this read-only list request once before showing an
    // error; do not retry mutations from this screen.
    if (!response?.ok) {
      await new Promise((resolve) => setTimeout(resolve, 280));
      response = await request(message);
    }
    if (!response?.ok) throw new Error(response?.error || "Windows helper에 연결할 수 없습니다.");

    // A create/rename UI may have started while this directory request was in flight.
    // Discard that old snapshot instead of letting it erase or relocate the new tail item.
    if (mutationVersionAtStart !== desktopMutationVersion || renameState || createInProgress) return false;

    if (currentDirectory && response.directoryPath) currentDirectory = response.directoryPath;
    currentParentDirectory = currentDirectory ? (response.parentPath || null) : null;
    updateFolderViewState();
    const items = Array.isArray(response.items) ? response.items : [];
    renderItems(items, previousSelection);
    if (response.wallpaperInfo) applyWallpaperInfo(response.wallpaperInfo);
    const overflow = grid.scrollWidth > grid.clientWidth + 2 || grid.scrollHeight > grid.clientHeight + 2;
    statusLabel.textContent = items.length + "개" + (overflow ? " · 스크롤" : "") + " · " + new Date().toLocaleTimeString("ko-KR");
    return true;
  } catch (error) {
    grid.replaceChildren();
    emptyPanel.hidden = true;
    setError("바탕화면을 불러오지 못했습니다. Windows helper 연결을 다시 확인한 뒤 새로고침하세요.");
    statusLabel.textContent = "연결 실패";
    return false;
  } finally {
    refreshButton.disabled = false;
    refreshInProgress = false;
  }
}

refreshButton.addEventListener("click", () => refreshDesktop({ includeVisuals: false }));
folderBack?.addEventListener("click", navigateBack);
folderUp?.addEventListener("click", navigateUp);
textViewerClose.addEventListener("click", closeTextViewer);
textViewer.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    closeTextViewer();
  }
});
document.addEventListener("contextmenu", (event) => {
  if (event.target.closest(".desktop-item")) event.preventDefault();
});
document.addEventListener("keydown", (event) => {
  if (renameState || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;

  if (event.key === "F2") {
    event.preventDefault();
    beginRename();
    return;
  }

  if (event.key === "F3") {
    event.preventDefault();
    createDesktopItem("file");
    return;
  }

  if (event.key === "F4") {
    event.preventDefault();
    createDesktopItem("folder");
    return;
  }

  if (event.key === "Delete") {
    event.preventDefault();
    deleteSelection();
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    for (const path of itemsByPath.keys()) setItemSelected(path, true);
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
    const selected = getSelectedItems().filter(isPhysicalItem);
    if (selected.length > 0) {
      event.preventDefault();
      copySelectedFiles();
    }
    return;
  }

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    applyHistory(event.shiftKey ? "redo" : "undo");
    return;
  }

  if (event.key === "Escape") {
    clearSelection();
    flushPendingRightClick();
  }
});

window.addEventListener("focus", () => refreshDesktop({ includeVisuals: true }));
window.addEventListener("resize", () => {
  updateDesktopRows();
  if (renameState) sizeAndPositionRenameInput(renameState.input, renameState.button);
});
window.addEventListener("blur", flushPendingRightClick);
// External filesystem changes refresh on focus or explicit refresh; no periodic polling.
refreshDesktop({ includeVisuals: true });
