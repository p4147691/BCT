function openMonitorBctRenameEditor(node, row) {
  if (!monitorBctShell?.renameConversation || !node?.conversationKey || !node?.sessionId) {
    setMonitorStatus("이 창의 정확한 RCC 대화 신원을 확인할 수 없어 이름을 바꾸지 않았습니다.", false, 5000);
    return;
  }
  closeMonitorBctRenameEditor();
  const overlay = document.createElement("div");
  overlay.className = "monitor-bct-rename-overlay";
  const dialog = document.createElement("form");
  dialog.className = "monitor-bct-rename-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", "대화 정보와 이름 변경");
  const head = document.createElement("div");
  head.className = "monitor-bct-rename-head";
  const heading = document.createElement("strong");
  heading.textContent = `${node.nodeLabel || "N?"} · 대화 정보`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "monitor-bct-rename-close";
  close.setAttribute("aria-label", "취소");
  close.textContent = "×";
  head.append(heading, close);
  let currentTitle = String(node.title || "").trim();
  const facts = document.createElement("div");
  facts.className = "monitor-bct-node-facts";
  const fact = (label, value) => {
    const line = document.createElement("div");
    const key = document.createElement("b");
    const text = document.createElement("span");
    key.textContent = label;
    text.textContent = value || "-";
    line.append(key, text);
    facts.append(line);
  };
  fact("대화 UUID", String(node.conversationKey || ""));
  fact("현재 위치", row?.querySelector?.(".monitor-bct-node-location")?.textContent || "확인 중");
  fact("연결", `창 ${node.windowId} · 탭 ${node.tabId}`);
  fact("실제 추론 수준", String(node.reasoningLevel || "확인 불가"));

  const makeField = (labelText, value, maximum, placeholder = "") => {
    const label = document.createElement("label");
    label.className = "monitor-bct-info-field";
    const caption = document.createElement("span");
    caption.textContent = labelText;
    const control = document.createElement("input");
    control.className = "monitor-bct-rename-input";
    control.type = "text";
    control.maxLength = maximum;
    control.value = value;
    control.placeholder = placeholder;
    control.autocomplete = "off";
    label.append(caption, control);
    return { label, control };
  };
  const titleField = makeField("ChatGPT 대화창 이름", currentTitle, 100);
  const scopeField = makeField(
    "대화망 / 작업 범위",
    String(node.scopeName || "").trim(),
    120,
    "비우면 미소속",
  );
  const rolesField = makeField(
    "역할 태그",
    Array.isArray(node.roleTags) ? node.roleTags.join(", ") : "",
    400,
    "예: Manager, 구현, CI",
  );
  const roleHint = document.createElement("div");
  roleHint.className = "monitor-bct-info-hint";
  roleHint.textContent = "Manager는 안내용 역할 태그입니다. 0명 또는 여러 명이어도 기능과 권한은 제한되지 않습니다.";
  const error = document.createElement("div");
  error.className = "monitor-bct-rename-error";
  error.setAttribute("aria-live", "polite");
  const actions = document.createElement("div");
  actions.className = "monitor-bct-rename-actions";
  const recovery = document.createElement("button");
  recovery.type = "button";
  recovery.className = "monitor-bct-open-recovery";
  recovery.textContent = "복구 보관함";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "취소";
  const confirm = document.createElement("button");
  confirm.type = "submit";
  confirm.className = "is-primary";
  confirm.textContent = "확인";
  actions.append(recovery, cancel, confirm);
  dialog.append(head, facts, titleField.label, scopeField.label, rolesField.label, roleHint, error, actions);
  overlay.append(dialog);
  document.body.append(overlay);
  monitorBctRenameEditor = {
    overlay, dialog, input: titleField.control, scopeInput: scopeField.control,
    rolesInput: rolesField.control, error, recovery, cancel, close, confirm, busy: false,
  };

  const cancelEditor = () => closeMonitorBctRenameEditor();
  close.addEventListener("click", cancelEditor);
  cancel.addEventListener("click", cancelEditor);
  recovery.addEventListener("click", () => {
    if (monitorBctRenameEditor?.busy) return;
    overlay.remove();
    monitorBctRenameEditor = null;
    openMonitorTrashRecovery();
  });
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) cancelEditor();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelEditor();
    }
  });
  dialog.addEventListener("submit", async (event) => {
    event.preventDefault();
    const editor = monitorBctRenameEditor;
    if (!editor || editor.busy) return;
    const title = editor.input.value.trim();
    const scopeName = editor.scopeInput.value.trim();
    const roleTags = monitorBctRoleTagsFromText(editor.rolesInput.value);
    if (!title) {
      editor.error.textContent = "이름을 입력하세요.";
      editor.input.focus();
      return;
    }
    const titleChanged = title !== currentTitle;
    const metadataChanged = scopeName !== String(node.scopeName || "").trim()
      || JSON.stringify(roleTags) !== JSON.stringify(Array.isArray(node.roleTags) ? node.roleTags : []);
    if (!titleChanged && !metadataChanged) return closeMonitorBctRenameEditor();
    editor.busy = true;
    editor.input.disabled = true;
    editor.scopeInput.disabled = true;
    editor.rolesInput.disabled = true;
    editor.recovery.disabled = true;
    editor.cancel.disabled = true;
    editor.close.disabled = true;
    editor.confirm.disabled = true;
    editor.confirm.textContent = "변경 중…";
    editor.error.textContent = "";
    let titleApplied = false;
    try {
      if (titleChanged) {
        await monitorBctShell.renameConversation(node, title);
        row.querySelector(".monitor-bct-node-title").textContent = title;
        currentTitle = title;
        titleApplied = true;
      }
      await monitorBctShell.updateConversationScope(node, {
        displayName: title,
        scopeName,
        roleTags,
      });
      editor.overlay.remove();
      monitorBctRenameEditor = null;
      setMonitorStatus(`대화 정보${titleChanged ? "와 실제 ChatGPT 이름" : ""}을 저장했습니다.`, true, 3500);
      globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 600);
    } catch (renameError) {
      editor.busy = false;
      editor.input.disabled = false;
      editor.scopeInput.disabled = false;
      editor.rolesInput.disabled = false;
      editor.recovery.disabled = false;
      editor.cancel.disabled = false;
      editor.close.disabled = false;
      editor.confirm.disabled = false;
      editor.confirm.textContent = "확인";
      editor.error.textContent = titleApplied
        ? `ChatGPT 이름은 변경됐지만 대화망 정보 저장에 실패했습니다 · ${renameError?.message || renameError}`
        : monitorBctRenameErrorText(renameError);
      (titleApplied ? editor.scopeInput : editor.input).focus();
    }
  });
  titleField.control.focus();
  titleField.control.select();
}

let monitorBctNodeInteractionService = null;
const monitorBctCollapsedScopes = new Set();
let monitorBctSuppressedClickKey = "";
let monitorBctSuppressScopeClickUntil = 0;

function installMonitorBctManagerLongPress(row, node) {
  let timer = 0;
  let startX = 0;
  let startY = 0;
  const cancel = () => {
    if (timer) clearTimeout(timer);
    timer = 0;
    row.classList.remove("monitor-bct-manager-hold");
  };
  row.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button,input")) return;
    startX = event.clientX;
    startY = event.clientY;
    row.classList.add("monitor-bct-manager-hold");
    timer = setTimeout(() => {
      timer = 0;
      row.classList.remove("monitor-bct-manager-hold");
      const key = monitorBctNodeSelectionKey(node);
      monitorBctSuppressedClickKey = key;
      globalThis.setTimeout(() => {
        if (monitorBctSuppressedClickKey === key) monitorBctSuppressedClickKey = "";
      }, 900);
      if (!node.scopeName) {
        setMonitorStatus("먼저 우클릭 정보창에서 이 대화의 작업 범위를 지정하세요.", false, 3500);
        return;
      }
      const tags = Array.isArray(node.roleTags) ? [...node.roleTags] : [];
      const hadManager = tags.includes("Manager");
      const nextTags = hadManager ? tags.filter((tag) => tag !== "Manager") : [...tags, "Manager"];
      row.classList.toggle("is-manager", !hadManager);
      void monitorBctShell.updateConversationScope(node, {
        displayName: node.title,
        scopeName: node.scopeName,
        roleTags: nextTags,
      }).then(() => {
        setMonitorStatus(
          `${node.nodeLabel || "N?"}의 Manager 안내 태그를 ${hadManager ? "해제했습니다" : "붙였습니다"}.`,
          true,
          2800,
        );
        globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 250);
      }).catch((error) => {
        row.classList.toggle("is-manager", hadManager);
        setMonitorStatus(`Manager 태그 저장 실패 · ${error?.message || error}`, false, 4000);
      });
    }, 600);
  });
  row.addEventListener("pointermove", (event) => {
    if (timer && Math.hypot(event.clientX - startX, event.clientY - startY) > 7) cancel();
  });
  row.addEventListener("pointerup", cancel);
  row.addEventListener("pointercancel", cancel);
  row.addEventListener("dragstart", cancel);
}

function getMonitorBctNodeInteractionService() {
  if (monitorBctNodeInteractionService) return monitorBctNodeInteractionService;
  if (!globalThis.MonitorBctNodeInteraction?.create) throw new Error("BCT 노드 이동 모듈을 불러오지 못함");
  monitorBctNodeInteractionService = globalThis.MonitorBctNodeInteraction.create({
    nativeRequest: monitorNative,
    renderVirtualDesktops,
    selectVirtualDesktopPreview,
    highlight: applyMonitorBctNodeHighlight,
    focusBrowserTab: async (target) => chrome.runtime.sendMessage({
      type: "monitor-focus-exact-chat-tab",
      tabId: target?.tabId,
      windowId: target?.windowId,
      conversationKey: target?.conversationKey,
    }),
  });
  return monitorBctNodeInteractionService;
}

async function resolveMonitorBctNodeHwnd(node) {
  let hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (hwnd) return String(hwnd);
  await refreshMonitorIdentityIndex(monitorLastAiState, true);
  refreshMonitorBctCurrentSessionWindowHwnd();
  hwnd = monitorHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (!hwnd) throw new Error("현재 세션에서 이 노드와 웹브라우저 창을 정확히 대조하지 못함");
  return String(hwnd);
}

async function resolveMonitorBctNodeDisplayHwnd(node) {
  let hwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (hwnd) return String(hwnd);
  await refreshMonitorBctBrowserWindowGeometry();
  await refreshMonitorIdentityIndex(monitorLastAiState, true);
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  hwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
  if (!hwnd) throw new Error("현재 세션에서 이 노드의 표시 위치를 고유하게 대조하지 못함");
  return String(hwnd);
}

function compareMonitorBctNodeDisplayOrder(left, right) {
  const leftOrder = Number(left.displayOrder || 0);
  const rightOrder = Number(right.displayOrder || 0);
  if (leftOrder > 0 || rightOrder > 0) {
    if (leftOrder <= 0) return 1;
    if (rightOrder <= 0) return -1;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  }
  return (left.tabIndex ?? Number.MAX_SAFE_INTEGER) - (right.tabIndex ?? Number.MAX_SAFE_INTEGER)
    || left.tabId - right.tabId;
}

function renderMonitorBctWindowNodes(nodes) {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorWorkers) return;
  // A background refresh may replace the captured row while the mouse is down.
  // Cancel before detaching it, so no ghost or draggable visual state survives.
  if (monitorBctPointerDrag) cancelMonitorBctNodePointerDrag({ pointerId: monitorBctPointerDrag.pointerId });
  const fragment = document.createDocumentFragment();
  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "monitor-bct-node-empty";
    empty.textContent = "현재 RCC에서 확인된 ChatGPT 창이 없습니다.";
    fragment.append(empty);
  }
  const groups = new Map();
  for (const node of nodes) {
    const key = node.scopeId || "__unassigned__";
    if (!groups.has(key)) groups.set(key, {
      key,
      name: node.scopeName || "미소속 대화",
      nodes: [],
    });
    groups.get(key).nodes.push(node);
  }
  for (const group of groups.values()) {
    group.nodes.sort(compareMonitorBctNodeDisplayOrder);
    const groupSection = document.createElement("section");
    groupSection.className = "monitor-bct-scope-group";
    groupSection.dataset.scopeId = group.key;
    const groupHeader = document.createElement("button");
    groupHeader.type = "button";
    groupHeader.className = "monitor-bct-scope-heading";
    groupHeader.dataset.scopeId = group.key;
    groupHeader.setAttribute("aria-expanded", monitorBctCollapsedScopes.has(group.key) ? "false" : "true");
    const groupCaret = document.createElement("span");
    groupCaret.className = "monitor-bct-scope-caret";
    groupCaret.setAttribute("aria-hidden", "true");
    const groupText = document.createElement("span");
    groupText.textContent = `${group.name} · ${group.nodes.length}`;
    groupHeader.append(groupCaret, groupText);
    groupHeader.addEventListener("click", (event) => {
      if (monitorBctPointerDrag?.active || Date.now() < monitorBctSuppressScopeClickUntil) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (monitorBctCollapsedScopes.has(group.key)) monitorBctCollapsedScopes.delete(group.key);
      else monitorBctCollapsedScopes.add(group.key);
      renderMonitorBctWindowNodes(nodes);
    });
    const groupList = document.createElement("div");
    groupList.className = "monitor-bct-node-list";
    groupList.dataset.scopeId = group.key;
    groupSection.append(groupHeader, groupList);
    fragment.append(groupSection);
    if (monitorBctCollapsedScopes.has(group.key)) {
      groupList.hidden = true;
      continue;
    }
    group.nodes.forEach((node, index) => {
    const row = document.createElement("article");
    row.className = "monitor-bct-node-row";
    row.dataset.tabId = String(node.tabId);
    row.dataset.windowId = String(node.windowId);
    row.dataset.instanceId = String(node.instanceId || "");
    row.dataset.sessionId = String(node.sessionId || "");
    row.dataset.nodeIndex = String(index + 1);
    row.dataset.nodeLabel = node.nodeLabel || "";
    row.dataset.conversationKey = node.conversationKey;
    row.dataset.scopeId = node.scopeId || "";
    row.setAttribute("role", "button");
    row.setAttribute("aria-selected", "false");
    row.tabIndex = 0;
    row.draggable = false;
    const mappedHwnd = monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId);
    const nativeLocation = mappedHwnd ? monitorWindowDesktopLocations.get(mappedHwnd) : null;
    const desktopPosition = nativeLocation
      ? monitorDesktopState.desktopIds.indexOf(String(nativeLocation.desktopId || ""))
      : -1;
    row.title = node.conversationKey
      ? `클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동하고 정확한 탭 선택 · 우클릭: 정보와 이름 변경 · 600ms 길게 누르기: Manager 안내 태그 지정/해제 · 창 ${node.windowId} · 탭 ${node.tabId}`
      : `클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동하고 정확한 탭 선택 · 창 ${node.windowId} · 탭 ${node.tabId}`;

    const number = document.createElement("span");
    number.className = "monitor-bct-node-number";
    number.textContent = node.nodeLabel || "N?";
    number.title = node.nodeLabel
      ? "BCT 대화망에 등록된 표시 전용 번호"
      : "관측됨 · 대화망 등록 전이라 표시 번호가 없습니다";

    const body = document.createElement("span");
    body.className = "monitor-bct-node-body";
    const title = document.createElement("strong");
    title.className = "monitor-bct-node-title";
    title.textContent = node.title;
    body.append(title);
    const location = document.createElement("small");
    location.className = "monitor-bct-node-location";
    location.textContent = monitorBctNodeLocationText(node, desktopPosition);
    location.title = Array.isArray(node.roleTags) && node.roleTags.length
      ? `${desktopPosition >= 0 ? `D${desktopPosition + 1}` : "위치 확인 중"} · ${node.roleTags.join(" · ")}`
      : location.textContent;
    body.append(location);

    const presence = document.createElement("span");
    presence.className = `monitor-bct-node-presence${node.generating ? " is-busy" : ""}`;
    presence.setAttribute("aria-label", node.generating ? "응답 생성 중" : "열려 있음");
    presence.title = node.generating ? "응답 생성 중" : "열려 있음";
    globalThis.MonitorStatusIcon?.render?.(presence, { activity: node.generating ? "play" : "pause" });
    row.append(number, body, presence);
    row.classList.toggle("is-manager", Array.isArray(node.roleTags) && node.roleTags.includes("Manager"));
    installMonitorBctManagerLongPress(row, node);
    row.addEventListener("dragstart", (event) => event.preventDefault());
    row.addEventListener("pointerdown", (event) => beginMonitorBctNodePointerDrag(event, row, node));
    row.addEventListener("click", (event) => {
      if (monitorBctSuppressedClickKey === monitorBctNodeSelectionKey(node)) {
        monitorBctSuppressedClickKey = "";
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      void resolveMonitorBctNodeDisplayHwnd(node).then((hwnd) => {
        monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(node);
        getMonitorBctNodeInteractionService().select(hwnd);
        setMonitorStatus(`${node.nodeLabel || "N?"} 연결 웹브라우저 창을 표시했습니다.`, true, 1800);
      }).catch((error) => {
        setMonitorStatus(`연결 창 표시 실패 · ${error?.message || error}`, false, 3500);
      });
    });
    row.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("monitor-bct-node-switch-pending");
      void resolveMonitorBctNodeHwnd(node).then((hwnd) => (
        monitorBctSelectedNodeKey = monitorBctNodeSelectionKey(node),
        getMonitorBctNodeInteractionService().activate(hwnd, {
          tabId: node.tabId,
          windowId: node.windowId,
          conversationKey: node.conversationKey,
        })
      )).then((result) => {
        setMonitorStatus(`${node.nodeLabel || "N?"} 창이 있는 D${result.index + 1}(으)로 이동해 정확한 ChatGPT 탭을 선택했습니다.`, true, 3200);
      }).catch((error) => {
        setMonitorStatus(`노드 창 이동 실패 · ${error?.message || error}`, false, 4500);
      }).finally(() => {
        globalThis.setTimeout(() => row.classList.remove("monitor-bct-node-switch-pending"), 350);
      });
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      row.click();
    });
    if (node.conversationKey) {
      row.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        openMonitorBctRenameEditor(node, row);
      });
    }
    groupList.append(row);
    });
  }
  monitorWorkers.replaceChildren(fragment);
  syncMonitorBctNodeTargetHighlight();
  if (monitorBctNodeSummary) {
    const stale = nodes.some((node) => node.displayStale === true);
    monitorBctNodeSummary.textContent = stale
      ? `${nodes.length}개 · RCC 일시 지연 · 마지막 검증 목록`
      : `${nodes.length}개 · BCT/RCC 실시간 상태`;
  }
}

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

function monitorBctPointInsideScopeHeading(clientX, clientY) {
  return [...(monitorWorkers?.querySelectorAll?.(".monitor-bct-scope-heading") || [])].some((heading) => {
    const rect = heading.getBoundingClientRect();
    return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
  });
}

function monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey) {
  const rows = [...list.querySelectorAll(".monitor-bct-node-row")]
    .filter((row) => String(row.dataset.conversationKey || "") !== draggedKey && !row.hidden)
    .map((row) => ({ row, rect: row.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width > 0 && rect.height > 0);
  if (!rows.length) return null;
  const direct = hit?.closest?.(".monitor-bct-node-row");
  if (direct && hit?.closest?.(".monitor-bct-node-list") === list &&
      String(direct.dataset.conversationKey || "") !== draggedKey) {
    const rect = direct.getBoundingClientRect();
    return { row: direct, position: clientX < rect.left + rect.width / 2 ? "before" : "after" };
  }

  const line = rows.reduce((best, candidate) => {
    const centerY = candidate.rect.top + candidate.rect.height / 2;
    const distance = Math.abs(clientY - centerY);
    return !best || distance < best.distance ? { distance, centerY } : best;
  }, null);
  const sameLine = rows
    .filter(({ rect }) => Math.abs((rect.top + rect.height / 2) - line.centerY) <= 3)
    .sort((left, right) => left.rect.left - right.rect.left);
  const first = sameLine[0];
  for (const candidate of sameLine) {
    if (clientX < candidate.rect.left + candidate.rect.width / 2) {
      return { row: candidate.row, position: "before" };
    }
  }
  const last = sameLine[sameLine.length - 1] || first;
  return last ? { row: last.row, position: "after" } : null;
}

// Keep the hit-zone and the visual insertion line governed by the SAME resolver.
const MONITOR_BCT_DROP_EDGE_X_PX = 22;
const MONITOR_BCT_DROP_EDGE_Y_PX = 10;
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

function monitorBctNodeDropAt(clientX, clientY, draggedKey) {
  if (monitorBctPointInsideScopeHeading(clientX, clientY)) return null;
  const hit = document.elementFromPoint(clientX, clientY);
  const list = monitorBctNodeDropListAt(clientX, clientY, hit);
  if (!list) return null;
  const scopeId = String(list.dataset.scopeId || "__unassigned__");
  const insertion = monitorBctNodeInsertionAt(list, hit, clientX, clientY, draggedKey);
  if (insertion) {
    const { row, position } = insertion;
    row.classList.add(position === "before" ? "monitor-bct-drop-before" : "monitor-bct-drop-after");
    row.dataset.dropPosition = position;
    list.classList.add("monitor-bct-node-list-target");
    return {
      scopeId,
      targetConversationKey: String(row.dataset.conversationKey || ""),
      position,
    };
  }
  return null;
}

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
  );
}

function cancelMonitorBctNodePointerDrag(event) {
  const drag = monitorBctPointerDrag;
  if (!drag || (event?.pointerId != null && event.pointerId !== drag.pointerId)) return;
  monitorBctStopDragInput(drag);
  if (drag.active) finishMonitorBctNodeDrag();
}

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

async function commitMonitorBctNodeDrop(destinationGroupKey, targetConversationKey, position) {
  if (monitorBctNodeReorderPending) {
    finishMonitorBctNodeDrag();
    return;
  }
  const draggedKey = monitorBctDraggedNodeKey;
  const snapshot = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache.slice() : [];
  const dragged = snapshot.find((node) => node.conversationKey === draggedKey);
  const destinationScopeId = destinationGroupKey === "__unassigned__" ? "" : destinationGroupKey;
  const destinationSample = snapshot.find((node) => (node.scopeId || "") === destinationScopeId);
  if (!dragged || !monitorBctShell?.reorderConversations) {
    finishMonitorBctNodeDrag();
    return;
  }
  const destination = snapshot
    .filter((node) => node.conversationKey !== draggedKey && (node.scopeId || "") === destinationScopeId)
    .sort(compareMonitorBctNodeDisplayOrder);
  let insertion = destination.length;
  if (targetConversationKey) {
    const targetIndex = destination.findIndex((node) => node.conversationKey === targetConversationKey);
    if (targetIndex >= 0) insertion = targetIndex + (position === "after" ? 1 : 0);
  }
  destination.splice(insertion, 0, dragged);
  const movedAcrossScopes = (dragged.scopeId || "") !== destinationScopeId;
  const nextOrders = new Map(destination.map((node, index) => [node.conversationKey, index + 1]));
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
      movedConversationKey: movedAcrossScopes ? draggedKey : "",
    });
    setMonitorStatus(
      movedAcrossScopes ? "노드를 대화망으로 이동하고 순서를 저장했습니다." : "노드 표시 순서를 저장했습니다.",
      true,
      2200,
    );
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

async function refreshMonitorBctWindowNodes() {
  if (!MONITOR_BCT_NODE_SUMMARY_ENABLED || !monitorBctShell || monitorBctWindowNodeRefreshBusy) return;
  monitorBctWindowNodeRefreshBusy = true;
  if (monitorBctNodesRefresh) monitorBctNodesRefresh.disabled = true;
  if (monitorBctNodeSummary) monitorBctNodeSummary.textContent = "확인 중…";
  try {
    const state = await monitorBctShell.monitorState();
    monitorBctWindowNodesCache = monitorBctShell.displayWindowNodes
      ? monitorBctShell.displayWindowNodes(state, monitorBctWindowNodesCache || [])
      : monitorBctShell.windowNodes(state);
    resetMonitorBctProjectionConvergence();
    await refreshMonitorBctBrowserWindowGeometry();
    await refreshMonitorIdentityIndex(monitorLastAiState, true);
    refreshMonitorBctCurrentSessionWindowHwnd();
    refreshMonitorBctDisplayWindowHwnd();
    renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleMonitorBctProjectionConvergence("bct-state");
  } catch (error) {
    if (monitorBctNodeSummary) monitorBctNodeSummary.textContent = "상태 확인 실패";
    const message = document.createElement("div");
    message.className = "monitor-bct-node-empty is-error";
    message.textContent = `BCT 창 현황을 불러오지 못했습니다 · ${error?.message || error}`;
    monitorWorkers?.replaceChildren(message);
  } finally {
    monitorBctWindowNodeRefreshBusy = false;
    if (monitorBctNodesRefresh) monitorBctNodesRefresh.disabled = false;
  }
}

async function refreshMonitorBctStatus() {
  if (!monitorVersion || !monitorBctShell) return;
  monitorVersion.classList.remove("healthy", "unhealthy");
  monitorVersion.setAttribute("aria-label", "BCT 연결 확인 중");
  try {
    const state = await monitorBctShell.health();
    monitorVersion.title = `${monitorVersion.textContent} · BCT 연결 정상`;
    monitorVersion.setAttribute("aria-label", `${monitorVersion.textContent} · BCT 연결 정상`);
    monitorVersion.classList.add("healthy");
  } catch (error) {
    monitorVersion.title = `${monitorVersion.textContent} · BCT 연결 안 됨 · ${error?.message || error}`;
    monitorVersion.setAttribute("aria-label", `${monitorVersion.textContent} · BCT 연결 안 됨`);
    monitorVersion.classList.add("unhealthy");
  }
}


monitorBctNodesRefresh?.addEventListener("click", () => {
  void refreshMonitorBctWindowNodes();
});

void refreshMonitorBctStatus();
void refreshMonitorBctWindowNodes();

async function refreshMonitorEndpointRegistry() {
  const refreshUrl = new URL("/browser/endpoints/refresh", ORCHESTRATOR_ROLE_ADMIN_URL).toString();
  const response = await actFetch(refreshUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.ok) throw new Error(result?.error || ("HTTP " + response.status));
  return result;
}

if (monitorActRestart) monitorActRestart.addEventListener("click", async () => {
  if (monitorActRestart.disabled) return;
  monitorActRestart.disabled = true;
  setMonitorStatus("ACT 작업 상태 확인 후 재시작 요청 중…", true, 4000);
  try {
    const response = await actFetch("act:/admin/restart", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent: "RESTART_ACT" }),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || !result?.ok) {
      const counts = Number.isInteger(result?.active_tasks) || Number.isInteger(result?.pending_tasks)
        ? ` · 활성 ${result?.active_tasks || 0}, 대기 ${result?.pending_tasks || 0}` : "";
      throw new Error(String(result?.error || `HTTP ${response.status}`) + counts);
    }
    setMonitorStatus("ACT 재시작 요청 완료 · 잠시 후 상태를 다시 확인합니다", true, 5000);
  } catch (error) {
    setMonitorStatus("ACT 재시작 보류 · " + (error?.message || String(error)), false);
    monitorActRestart.disabled = false;
  }
});
if (monitorExtensionReload) monitorExtensionReload.addEventListener("click", () => {
  if (monitorExtensionReload.disabled) return;
  monitorExtensionReload.disabled = true;
  setMonitorStatus("확장을 다시 로드하고 Monitor 창을 복구합니다…", true, 2500);
  try {
    chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {});
  } catch (error) {
    monitorExtensionReload.disabled = false;
    setMonitorStatus("확장 리로드 실패 · " + (error?.message || String(error)), false);
  }
});

function monitorExactSelectedChatNode() {
  const nodes = Array.isArray(monitorBctWindowNodesCache) ? monitorBctWindowNodesCache : [];
  const selected = nodes.find((node) =>
    monitorBctSelectedNodeKey && monitorBctNodeSelectionKey(node) === monitorBctSelectedNodeKey
  );
  if (selected) return selected;
  const active = nodes.filter((node) => node.active === true && node.conversationKey && !node.displayStale);
  return active.length === 1 ? active[0] : null;
}

async function runMonitorUtilityAction(button, pendingText, action) {
  if (!button || button.disabled) return;
  button.disabled = true;
  setMonitorStatus(pendingText, true, 5000);
  try {
    const result = await action();
    if (result?.ok === false) throw new Error(result.error || "복구 결과를 확인하지 못함");
    return result;
  } finally {
    button.disabled = false;
  }
}

monitorRccReload?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorRccReload, "RCC의 정확한 현재 인스턴스를 확인 중…", async () => {
    if (!Array.isArray(monitorBctWindowNodesCache)) await refreshMonitorBctWindowNodes();
    const instances = [...new Set((monitorBctWindowNodesCache || [])
      .filter((node) => !node.displayStale && node.instanceState === "OPEN")
      .map((node) => String(node.instanceId || "").trim()).filter(Boolean))];
    if (instances.length !== 1) throw new Error(`RCC_RELOAD_EXACT_INSTANCE_REQUIRED:${instances.length}`);
    await monitorBctShell.reloadRcc(instances[0]);
    setMonitorStatus("RCC 리로드 영수증을 확인했습니다. 연결 복구를 기다립니다.", true, 5000);
    globalThis.setTimeout(() => void refreshMonitorBctWindowNodes(), 1400);
    return { ok:true };
  }).catch((error) => setMonitorStatus(`RCC 리로드 실패 · ${error?.message || error}`, false, 6000));
});

monitorBctRecover?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorBctRecover, "BCT Core Supervisor 복구 상태를 확인 중…", async () => {
    const result = await monitorNative({ type:"recoverBctCore" });
    if (!result?.ok || result?.verified !== true) throw new Error(result?.error || "BCT_CORE_RECOVERY_UNVERIFIED");
    await refreshMonitorBctStatus();
    setMonitorStatus(result.alreadyReady ? "BCT Core가 이미 정상입니다." : "BCT Core 시작·복구와 READY를 확인했습니다.", true, 4500);
    return result;
  }).catch((error) => setMonitorStatus(`BCT 시작·복구 실패 · ${error?.message || error}`, false, 6500));
});

monitorMcpTunnelRecover?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorMcpTunnelRecover, "MCP 터널 Supervisor 복구 상태를 확인 중…", async () => {
    const result = await monitorNative({ type:"recoverMcpTunnel" });
    if (!result?.ok || result?.verified !== true) throw new Error(result?.error || "BCT_TUNNEL_RECOVERY_UNVERIFIED");
    setMonitorStatus(result.alreadyReady ? "MCP 터널이 이미 정상입니다." : "MCP 터널 복구와 health/ready를 확인했습니다.", true, 4500);
    return result;
  }).catch((error) => setMonitorStatus(`MCP 터널 복구 실패 · ${error?.message || error}`, false, 6500));
});

monitorBctControlRefresh?.addEventListener("click", () => {
  void runMonitorUtilityAction(monitorBctControlRefresh, "선택한 ChatGPT 탭의 BC 도구 연결을 새로 읽는 중…", async () => {
    const node = monitorExactSelectedChatNode();
    if (!node?.conversationKey) throw new Error("BC_REFRESH_SELECT_EXACT_CHAT_NODE_FIRST");
    if (node.generating === true) throw new Error("BC_REFRESH_CHAT_IS_GENERATING");
    const result = await chrome.runtime.sendMessage({
      type:"monitor-refresh-exact-chatgpt-tab",
      tabId:node.tabId,
      windowId:node.windowId,
      conversationKey:node.conversationKey,
    });
    if (!result?.ok || result?.reloaded !== true) throw new Error(result?.error || "BC_REFRESH_UNVERIFIED");
    setMonitorStatus(`${node.nodeLabel || "선택 노드"} ChatGPT 탭을 다시 불러왔습니다. BC 도구가 다시 연결됩니다.`, true, 5000);
    return result;
  }).catch((error) => setMonitorStatus(`BC 도구 새로고침 실패 · ${error?.message || error}`, false, 6500));
});
if (monitorNodeSync) monitorNodeSync.addEventListener("click", async () => {
  if (monitorNodeSync.disabled) return;
  monitorNodeSync.disabled = true;
  setMonitorStatus("노드 동기화 중…", true, 3000);
  try {
    await refreshMonitorEndpointRegistry();

    await refreshAiMonitor();
    await refreshMonitorRoleAdmin();

    const openEndpoints = (Array.isArray(monitorLastAiState?.endpoints) ? monitorLastAiState.endpoints : [])
      .filter((endpoint) => String(endpoint?.presence_state || "").toUpperCase() === "OPEN");
    const conversationCounts = new Map();
    for (const endpoint of openEndpoints) {
      const key = String(endpoint?.conversation_key || "").trim();
      const tabId = String(endpoint?.tab_id ?? "").trim();
      if (!key || !tabId) continue;
      conversationCounts.set(key, (conversationCounts.get(key) || 0) + 1);
    }
    const matched = [...conversationCounts.values()].filter((count) => count === 1).length;
    const ambiguous = [...conversationCounts.values()].filter((count) => count > 1).length;
    setMonitorStatus(
      ambiguous
        ? ("노드 동기화 완료 · " + matched + "개 일치 · " + ambiguous + "개 중복 확인 필요")
        : ("노드 동기화 완료 · " + matched + "개 일치"),
      ambiguous === 0,
      3000
    );
  } catch (error) {
    setMonitorStatus("노드 동기화 실패 · " + (error?.message || String(error)), false, 3500);
  } finally {
    monitorNodeSync.disabled = false;
  }
});

chrome.storage.onChanged.addListener((changes,areaName)=>{
  if(areaName!=="local")return;
  let shouldRender=false;
  if(changes[MONITOR_NODE_BINDINGS_KEY]){
    const nextValues=Array.isArray(changes[MONITOR_NODE_BINDINGS_KEY]?.newValue)?changes[MONITOR_NODE_BINDINGS_KEY].newValue:[];
    const nextSignature=monitorNodeBindingsSignature(nextValues);
    const bindingsActuallyChanged=nextSignature!==monitorPersistedNodeBindingsSignature;
    monitorPersistedNodeBindingsSignature=nextSignature;
    monitorNodeBindings.clear();
    for(const item of nextValues){
      if(!item?.conversation_key)continue;
      const transport=String(item?.transport_instance_id||"").trim(),tabId=String(item?.tab_id??"").trim(),hwnd=String(item?.hwnd||"").trim(),windowId=String(item?.window_id??"").trim();
      if(transport&&tabId)monitorNodeBindings.set(`tab:${transport}:${tabId}`,item);
      if(transport&&windowId)monitorNodeBindings.set(`lineage:${transport}:${windowId}`,item);
      if(/^\d+$/.test(hwnd)&&hwnd!=="0")monitorNodeBindings.set(`hwnd:${hwnd}`,item);
    }
    monitorNodeBindingsReady=true;
    shouldRender=bindingsActuallyChanged;
  }
  if(changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]){
    monitorApprovedChatTransitions.clear();
    for(const item of Array.isArray(changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]?.newValue)?changes[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY].newValue:[])if(String(item||"").trim())monitorApprovedChatTransitions.add(String(item));
    monitorApprovedChatTransitionsReady=true;
    shouldRender=true;
  }
  if(shouldRender&&monitorLastAiState)renderWorkers(monitorLastAiState);
});

chrome.storage.local.get([MONITOR_NODE_BINDINGS_KEY,MONITOR_APPROVED_CHAT_TRANSITIONS_KEY],(data)=>{

  const storedNodeBindings=Array.isArray(data?.[MONITOR_NODE_BINDINGS_KEY])?data[MONITOR_NODE_BINDINGS_KEY]:[];
  monitorPersistedNodeBindingsSignature=monitorNodeBindingsSignature(storedNodeBindings);
  for(const item of storedNodeBindings){

    if(!item?.conversation_key)continue;

    const transport=String(item?.transport_instance_id||"").trim(),tabId=String(item?.tab_id??"").trim(),hwnd=String(item?.hwnd||"").trim(),windowId=String(item?.window_id??"").trim();

    if(transport&&tabId)monitorNodeBindings.set(`tab:${transport}:${tabId}`,item);

    if(transport&&windowId)monitorNodeBindings.set(`lineage:${transport}:${windowId}`,item);

    if(/^\d+$/.test(hwnd)&&hwnd!=="0")monitorNodeBindings.set(`hwnd:${hwnd}`,item);

  }

  for(const item of Array.isArray(data?.[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY])?data[MONITOR_APPROVED_CHAT_TRANSITIONS_KEY]:[])if(String(item||"").trim())monitorApprovedChatTransitions.add(String(item));

  monitorNodeBindingsReady=true;

  monitorApprovedChatTransitionsReady=true;

  if(monitorLastAiState)renderWorkers(monitorLastAiState);

});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_GHOST_CACHE_KEY,MONITOR_GHOST_HIDDEN_KEY],(data)=>{for(const item of Array.isArray(data?.[MONITOR_GHOST_CACHE_KEY])?data[MONITOR_GHOST_CACHE_KEY]:[])if(item?.conversation_key)monitorGhostCache.set(String(item.conversation_key),item);for(const key of Array.isArray(data?.[MONITOR_GHOST_HIDDEN_KEY])?data[MONITOR_GHOST_HIDDEN_KEY]:[])monitorHiddenGhosts.add(String(key));monitorGhostStorageReady=true;});

chrome.storage.local.get([MONITOR_CONTEXT_TITLE_STORAGE_KEY],(data)=>{const raw=data?.[MONITOR_CONTEXT_TITLE_STORAGE_KEY]||{};for(const [key,value] of Object.entries(raw))if(key&&value&&typeof value==="object")monitorContextTitles.set(String(key),value);monitorContextTitlesReady=true;for(const [key,value] of monitorContextTitles){monitorPublishedContextTitleSignatures.set(key,JSON.stringify(value||{}));monitorPublishSharedContextTitle(key,value);}void monitorSyncSharedRuntime();if(monitorLastAiState)renderWorkers(monitorLastAiState);});

if (MONITOR_FEATURE_RECOVERY_ENABLED) chrome.storage.local.get([MONITOR_REBOOT_SNAPSHOT_KEY],(data)=>{const raw=data?.[MONITOR_REBOOT_SNAPSHOT_KEY];if(raw&&typeof raw==="object"&&Array.isArray(raw.items))monitorRebootSnapshot=raw;monitorRebootSnapshotReady=true;});

let monitorStateFailureCount = 0;

let monitorStateFailureStartedAt = 0;

const MONITOR_FAILURE_GRACE_MS = 3000;

let monitorActHealthWasDown = false;

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

async function refreshActHealth() {

  try {

    const response = await actFetch(ORCHESTRATOR_HEALTH_URL, { cache: "no-store" });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const health = await response.json();

    if (!health?.ok || health?.service !== "Agent Orchestrator") throw new Error("ACT health unavailable");

    const recovered = monitorActHealthWasDown;

    monitorActHealthWasDown = false;

    setMonitorStatus("ACT 실행 중", true);

    if (recovered) await refreshAiMonitor();

  } catch (_) {

    monitorActHealthWasDown = true;

    setMonitorStatus("ACT 연결 끊김", false);

  }

}

async function refreshAiMonitor() {
  const refreshStartedAt = performance.now();
  const refreshStages = {};
  const markRefreshStage = (name) => { refreshStages[name] = Math.max(0, performance.now() - refreshStartedAt); };

  if (monitorRefreshBusy) { monitorRefreshQueued = true; return; }

  monitorRefreshBusy = true;

  let actStateConfirmed = false;

  try {

    const optionalFetch = (url, timeoutMs = 900) => Promise.race([

      actFetch(url, { cache: "no-store" }).catch(() => null),

      new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs)),

    ]);

    const stateResponse = await actFetch(ORCHESTRATOR_MONITOR_STATE_URL, { cache: "no-store" });

    const [reportsResponse, llmNodesResponse] = await Promise.all([

      optionalFetch(ORCHESTRATOR_PENDING_REPORTS_URL),

      optionalFetch(ORCHESTRATOR_LLM_NODES_URL, 5000),

    ]);

    markRefreshStage("ACT 수신");

    if (!stateResponse.ok) throw new Error(`STATE HTTP ${stateResponse.status}`);

    const state = await stateResponse.json();

    if (!state?.ok) throw new Error("Orchestrator state unavailable");

    monitorStartupStateConfirmed = true;

    const startupOpenEndpoints=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((endpoint)=>String(endpoint?.presence_state||"").toUpperCase()==="OPEN");

    monitorStartupEndpointFreshConfirmed=startupOpenEndpoints.every((endpoint)=>monitorEndpointFreshnessState(endpoint)!=="unresponsive");

    const llmNodeState = llmNodesResponse?.ok ? await llmNodesResponse.json().catch(() => null) : null;

    const previousLlmNodes = Array.isArray(monitorLastAiState?.llm_nodes) && monitorLastAiState.llm_nodes.length

      ? monitorLastAiState.llm_nodes

      : monitorCachedLlmNodes;

    const freshLlmNodes = llmNodeState?.ok && Array.isArray(llmNodeState?.llm_nodes) ? llmNodeState.llm_nodes : null;

    const transientEmptyLlmNodes = Array.isArray(freshLlmNodes) && freshLlmNodes.length === 0 && previousLlmNodes.length > 0 && monitorConsecutiveEmptyLlmResponses < 1;

    if (Array.isArray(freshLlmNodes)) {

      if (freshLlmNodes.length === 0) monitorConsecutiveEmptyLlmResponses += 1;

      else monitorConsecutiveEmptyLlmResponses = 0;

    }

    const effectiveFreshLlmNodes = transientEmptyLlmNodes ? null : freshLlmNodes;

    if (transientEmptyLlmNodes) monitorRefreshQueued = true;

    state.llm_nodes = effectiveFreshLlmNodes || previousLlmNodes;

    if (effectiveFreshLlmNodes) {

      monitorCachedLlmNodes = effectiveFreshLlmNodes;

      chrome.storage.local.set({ [MONITOR_LLM_CACHE_STORAGE_KEY]: effectiveFreshLlmNodes }).catch(() => {});

    }

    markRefreshStage("상태 정리");

    // From here on ACT state transport is confirmed healthy. Any later failure is

    // Monitor-side synchronization work and must not be reported as ACT disconnected.

    actStateConfirmed = true;

    let reportState = null;

    if (reportsResponse?.ok) reportState = await reportsResponse.json().catch(() => null);

    if (reportState?.ok) {

      monitorPendingDurableReports = Array.isArray(reportState?.reports) ? reportState.reports : [];

    } else if (reportsResponse?.status === 409) {

      monitorPendingDurableReports = [];

      const reportError = String(reportState?.error || "").trim();

      if (reportError === "CURRENT_ORCHESTRATOR_MISSING") {

        setMonitorStatus("ORCHESTRATOR 없음", false);

      } else {

        setMonitorStatus("보고 준비 중", false);

      }

    }

    monitorLastAiState = state;
    pruneMonitorEphemeralGenerationState(state);

    chrome.storage.local.set({ [MONITOR_AI_STATE_CACHE_KEY]: { at: Date.now(), state } }).catch(() => {});

    monitorReconcilePendingTitles(state);

    // Render ACT-authoritative nodes immediately. Physical identity/workplace sync below is enrichment only

    // and must not be able to leave the node list blank when ACT transport is already healthy.

    renderWorkers(state);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleInitialSemanticThumbSync();

    markRefreshStage("노드 렌더");

    // Physical desktop/window state is authoritative from Windows Native Host; ACT adds node/work meaning only.

    await Promise.race([refreshMonitorIdentityIndex(state), new Promise((resolve)=>setTimeout(resolve, 3000))]);

    markRefreshStage("창 식별");
    await syncMonitorPhysicalWorkplaces(state);
    markRefreshStage("데스크 동기화");

    const completionTransitionChanged = monitorSyncChatCompletionTransitions(state);

    const authoritativeAlertChanged = monitorSyncAuthoritativeCompletionAlerts(state);

    if (completionTransitionChanged || authoritativeAlertChanged) renderWorkers(state);

    monitorPostWorkLastObservedAt = Date.now();

    monitorPostWorkPersist();

    markRefreshStage("후처리");
    monitorStateFailureCount = 0;

    monitorStateFailureStartedAt = 0;

    setMonitorStatus("ACT 실행 중", true);

  } catch (error) {

    if (actStateConfirmed) {

      monitorStateFailureCount = 0;

      monitorStateFailureStartedAt = 0;

      setMonitorStatus("ACT 실행 중", true);

      console.warn("DesktopWindow Monitor post-ACT sync delayed", error);

    } else {

      scheduleMonitorStartupRecovery();

      monitorStateFailureCount += 1;

      if (!monitorStateFailureStartedAt) monitorStateFailureStartedAt = Date.now();

      if (Date.now() - monitorStateFailureStartedAt >= MONITOR_FAILURE_GRACE_MS) {

        setMonitorStatus("ACT \uC5F0\uACB0 \uB04A\uAE40", false);

        console.warn("DesktopWindow Monitor ACT state transport failed", error);

      }

    }

  } finally {

    monitorRecordRefreshTiming(refreshStartedAt, refreshStages);
    monitorRefreshBusy = false;
    // A restore can queue an authoritative badge resync while the full refresh owns the gate.
    // Consume it immediately when that gate opens instead of waiting for another window event.
    if (monitorConversationStateForceBadgeSyncPending && !monitorConversationStateRefreshBusy) {
      setTimeout(()=>{ void refreshMonitorConversationStateFast(); },0);
    }

    if (monitorRefreshQueued) {

      monitorRefreshQueued = false;

      setTimeout(() => { void refreshAiMonitor(); }, 0);

    }

  }

}

let monitorNativePort = null;

const monitorNativePending = [];

function monitorCaptureDataUriToObjectUrl(dataUri) {
  const source = String(dataUri || "");
  const match = /^data:([^;,]+);base64,(.+)$/.exec(source);
  if (!match) return source;
  const binary = atob(match[2]);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const objectUrl = URL.createObjectURL(new Blob([bytes], { type:match[1] || "image/jpeg" }));
  monitorRenderDiagnostics.blobCreates += 1;
  return objectUrl;
}

function ensureMonitorNativePort() {

  if (monitorNativePort) return monitorNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

  monitorNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.event === true && response?.type === "windowMoveSizeEnd") { scheduleMonitorWindowLifecycleEvent(response); return; }
    if (response?.event === true && response?.type === "windowForegroundChanged") { handleMonitorForegroundChangedEvent(response); return; }
    if (response?.event === true && response?.type === "desktopWallpaperChanged") {
      const explicitId=String(response.desktopId||"").toLowerCase();
      const visuals=[...(monitorDesktopThumbs?.querySelectorAll?.(".monitor-desktop-thumb-visual")||[])];
      const targets=explicitId ? visuals.filter(v=>String(v.dataset.desktopId||"").toLowerCase()===explicitId) : visuals;
      monitorDesktopThumbs.dataset.wallpaperEventAt=String(Date.now());
      // Each visual keeps its own generation fence; no cross-desktop cache.
      void Promise.allSettled(targets.map(visual =>
        globalThis.MonitorDesktopThumbnailV2.refreshWallpaper(
          visual,visual.dataset.desktopId,id=>monitorNative({
            type:"getDesktopVisualSnapshot",desktopId:id,
            maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,quality:68
          }),{force:true})));
      return;
    }
    if (response?.event === true && response?.type === "monitorDragPreviewReleased") {
      const drag = monitorBctPointerDrag;
      if (drag?.active && response?.token === monitorBctNativePreviewToken) {
        cancelMonitorBctNodePointerDrag({ pointerId:drag.pointerId });
      }
      return;
    }

    if (response?.event === true) return; // Never shift a request reply for unsolicited Native events.
    const pending = monitorNativePending.shift();

    if (pending) {
      pending.resolve(response);
    }

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료";

    monitorNativePort = null;

    while (monitorNativePending.length) monitorNativePending.shift().reject(new Error(error));

  });

  return port;

}

function handleMonitorForegroundChangedEvent(event) {
  const hwnd=String(event?.hwnd||"").trim();
  const desktopId=String(event?.desktopId||"").trim();
  if(!/^\d+$/.test(hwnd)||hwnd==="0"||!desktopId)return;
  const visibleNode=document.querySelector(`.monitor-desktop-thumb-window[data-hwnd="${hwnd}"], .monitor-window-preview[data-hwnd="${hwnd}"]`);
  if(!visibleNode)return;
  monitorAcknowledgePostWorkForHwnd(hwnd);
  applyMonitorWindowHighlight(hwnd);
  void syncMonitorNativeZOrder(desktopId);
}

// V2 owns all bottom desktop-thumbnail pixels and HWND DOM. Legacy lifecycle
// events may request refresh/removal; they must never create/modify tile images.
function removeMonitorV2Window(hwnd, exceptDesktopId = "") {
  const key=String(hwnd||"");
  if (!/^\d+$/.test(key)) return;
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  for (const tile of monitorDesktopThumbs.children) {
    const id=String(tile.dataset.desktopId||"");
    if (id===String(exceptDesktopId||"")) continue;
    const visual=tile.querySelector(".monitor-desktop-thumb-visual");
    if (!visual) continue;
    renderer?.removeWindow(visual,id,key);
    // These are independent semantic overlays, not pixel-rendering surfaces.
    for (const selector of [
      `.monitor-window-status-layer[data-hwnd="${key}"]`,
      `.monitor-window-pause-overlay[data-hwnd="${key}"]`,
      `.monitor-window-desktop-badge[data-hwnd="${key}"]`,
      `.monitor-window-non-chat-countdown[data-hwnd="${key}"]`
    ]) visual.querySelector(selector)?.remove();
  }
}
function scheduleMonitorV2WindowRefresh(event) {
  const id=String(event?.desktopId||"");
  const tile=[...monitorDesktopThumbs.children].find(t=>String(t.dataset.desktopId||"")===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  if (!visual?.isConnected || !globalThis.MonitorDesktopThumbnailV2) return false;
  // Source of pixels remains getDesktopVisualSnapshot/captureDesktopFrame only.
  // Never accept the old event's thumbnail-service snapshot, SVG or cache.
  void refreshDesktopThumb(visual,id).catch(()=>false);
  return true;
}

function scheduleMonitorWindowLifecycleEvent(event) {
  const hwnd = String(event?.hwnd || "").trim();
  if (!/^\d+$/.test(hwnd) || hwnd === "0") return;
  monitorWindowLifecyclePendingEvents.set(hwnd, event);
  if (!monitorWindowLifecycleDrainBusy) void drainMonitorWindowLifecycleEvents();
}

async function drainMonitorWindowLifecycleEvents() {
  if (monitorWindowLifecycleDrainBusy) return;
  monitorWindowLifecycleDrainBusy = true;
  try {
    while (monitorWindowLifecyclePendingEvents.size) {
      const next = monitorWindowLifecyclePendingEvents.entries().next().value;
      if (!next) break;
      const [hwnd, event] = next;
      monitorWindowLifecyclePendingEvents.delete(hwnd);
      await handleMonitorWindowLifecycleEvent(event);
    }
  } finally {
    monitorWindowLifecycleDrainBusy = false;
    if (monitorWindowLifecyclePendingEvents.size) void drainMonitorWindowLifecycleEvents();
  }
}

async function handleMonitorWindowLifecycleEvent(event) {

  const hwnd=String(event?.hwnd||"").trim(), desktopId=String(event?.desktopId||"").trim();

  if (!/^\d+$/.test(hwnd)||hwnd==="0"||!desktopId) return;
  if (hwnd === String(monitorDesktopState.hostWindowHwnd || "")) {
    await chrome.runtime.sendMessage({ type:"monitor-save-popup-window-bounds" }).catch(() => null);
    return;
  }

  const prior=monitorWindowDesktopLocations.get(hwnd)||{};

  const previousDesktopId=String(prior.desktopId||"").trim();

  const vw=Math.max(1,Number(event.previewVirtualWidth)||1), vh=Math.max(1,Number(event.previewVirtualHeight)||1);

  const vl=Number(event.previewVirtualLeft)||0, vt=Number(event.previewVirtualTop)||0;
  const lifecycleReason=String(event?.reason||"").toLowerCase();
  // Native notifications are allowed to use either `iconic: true` or the
  // lifecycle reason. The picture-hiding and node-badge paths must agree.
  const minimized=monitorMinimizedNodeBadgeContract?.minimizedEvent?.(event) || lifecycleReason==="minimized" || Boolean(event.iconic);
  const restoring=Boolean(prior.iconic)&&!minimized&&event.visible!==false;

  const apply=(img)=>{ img.style.display=(minimized||event.visible===false)?"none":""; img.style.left=`${((Number(event.left)-vl)/vw)*100}%`; img.style.top=`${((Number(event.top)-vt)/vh)*100}%`; img.style.width=`${(Number(event.width)/vw)*100}%`; img.style.height=`${(Number(event.height)/vh)*100}%`; syncMonitorStatusLayer(img,hwnd); syncMonitorPauseOverlay(img,hwnd); if(!restoring)syncMonitorDesktopNumberBadge(img,hwnd); syncMonitorNonChatCountdown(img,hwnd); };

  if (!previousDesktopId || previousDesktopId===desktopId) for (const img of document.querySelectorAll(`.monitor-window-preview[data-hwnd="${hwnd}"]`)) apply(img);

  monitorWindowDesktopLocations.set(hwnd,{...prior,hwnd,desktopId,desktop:monitorDesktopState.desktopIds.indexOf(desktopId)+1,title:String(event.title||prior.title||""),className:String(event.className||prior.className||""),left:Number(event.left),top:Number(event.top),width:Number(event.width),height:Number(event.height),iconic:minimized,visible:event.visible!==false,at:Date.now()});
  syncMonitorMinimizedNodeBadges(monitorLastAiState);
  if (minimized) scheduleMonitorMinimizedBadgeConvergence(hwnd);
  const badgeTile=[...monitorDesktopThumbs.children].find((item)=>String(item.dataset.desktopId||"")===desktopId);
  const badgeVisual=badgeTile?.querySelector(".monitor-desktop-thumb-visual");
  if (restoring) {
    badgeVisual?.querySelectorAll(`.monitor-thumbnail-tab-badge[data-hwnd="${hwnd}"], .monitor-window-desktop-badge[data-hwnd="${hwnd}"]`).forEach((node)=>node.remove());
    for (const img of document.querySelectorAll(`.monitor-window-preview[data-hwnd="${hwnd}"], .monitor-desktop-thumb-window[data-hwnd="${hwnd}"]`)) syncMonitorDesktopNumberBadge(img,hwnd);
    if (badgeVisual?.isConnected) syncMonitorThumbnailTabBadges(badgeVisual,"monitor-desktop-thumb-window");
    void refreshMonitorConversationStateFast(true).catch(()=>{});
  } else if (badgeVisual?.isConnected) syncMonitorThumbnailTabBadges(badgeVisual,"monitor-desktop-thumb-window");

  const reason=String(event?.reason||"").toLowerCase();

  const lifecycleHidden=reason==="hidden"||minimized||event.visible===false;
  if (lifecycleHidden) {
    monitorThumbnailService.invalidate(hwnd);
    removeMonitorV2Window(hwnd);
  }

  if (lifecycleHidden) {

    invalidateMonitorDesktopFrames(desktopId);

    return;

  }

  const cloakEvent=reason==="cloaked"||reason==="uncloaked";
  if (cloakEvent) {
    monitorThumbnailService.invalidate(hwnd);
    scheduleMonitorV2WindowRefresh(event);
    return;
  }

  monitorThumbnailService.invalidate(hwnd);

  if (previousDesktopId && previousDesktopId!==desktopId) {
    void actFetch("act:/monitor/node-state/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(()=>refreshAiMonitor()).catch(()=>{});
    await actFetch("act:/monitor/node-state/refresh",{method:"POST"}).catch(()=>null);
    await refreshAiMonitor().catch(()=>{});

    removeMonitorV2Window(hwnd,desktopId);

    scheduleMonitorV2WindowRefresh(event);

    return;

  }

  invalidateMonitorDesktopFrames(desktopId);

  const selectedDesktopId=String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex]||"");
  const selectedDesktop=desktopId===selectedDesktopId;
  if (selectedDesktop) {
    await refreshSelectedThumb().catch(() => false);
    return;
  }

  scheduleMonitorV2WindowRefresh(event);

}

function monitorNative(message) {
  return MonitorNativeTrace.request("control", message, () => monitorControlNativeRequest(message));
}

function monitorControlNativeRequest(message) {
  // Pixel capture belongs exclusively to the WGC Core host. The Control host
  // still contains the legacy synchronous capture implementation.
  if (message?.type === "captureWindow") {
    return Promise.reject(new Error("CAPTURE_REQUIRES_WGC_CORE_ADAPTER"));
  }

  return new Promise((resolve, reject) => {

    const port = ensureMonitorNativePort();

    monitorNativePending.push({ resolve, reject, message });

    try { port.postMessage(message); }

    catch (error) { monitorNativePending.pop(); reject(error); }

  });

}

function monitorNativeLaunchIsolated(message) {

  return new Promise((resolve, reject) => {

    const port = chrome.runtime.connectNative(MONITOR_CONTROL_HOST);

    let settled = false;

    const finish = (fn, value) => {

      if (settled) return;

      settled = true;

      try { port.disconnect(); } catch (_) {}

      fn(value);

    };

    port.onMessage.addListener((response) => {

      if (response?.event === true) return;

      finish(resolve, response);

    });

    port.onDisconnect.addListener(() => {

      if (settled) return;

      finish(reject, new Error(chrome.runtime.lastError?.message || "Monitor Native Host 연결 종료"));

    });

    try { port.postMessage(message); }

    catch (error) { finish(reject, error); }

  });

}

