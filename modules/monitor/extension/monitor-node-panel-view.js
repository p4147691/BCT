// The actual NodePanel DOM owner. All BCT/RCC/desktop/actions are injected ports.
(() => {
  "use strict";
  function create({root,summary,document,interactionState,ports}) {
    if (!root || !document || !interactionState || !ports) throw new TypeError("NODE_PANEL_PORTS_REQUIRED");
function render(nodes) {
  if (!ports.enabled() || !root) return;
  // A background refresh may replace the captured row while the mouse is down.
  // Cancel before detaching it, so no ghost or draggable visual state survives.
  if (ports.pointerDrag()) ports.cancelDrag({ pointerId: ports.pointerDrag().pointerId });
  nodes = ports.uniqueNodes(nodes);
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
  // Keep a real destination for returning a node even when no conversation is
  // currently unassigned. The heading is not a drop target; the list below is.
  if (!groups.has("__unassigned__")) groups.set("__unassigned__", {
    key: "__unassigned__",
    name: "미소속 대화",
    nodes: [],
  });
  const orderedGroups = [...groups.values()].sort((left, right) =>
    Number(left.key === "__unassigned__") - Number(right.key === "__unassigned__") ||
    left.name.localeCompare(right.name, "ko"));
  for (const group of orderedGroups) {
    const physicalOrder = new Map(group.nodes.map((node) => {
      const hwnd = ports.hwndForWindow(
        node.windowId, ports.lastAiState(), node.instanceId, node.sessionId);
      const location = hwnd ? ports.locations().get(hwnd) : null;
      const desktopPosition = location
        ? ports.desktopState().desktopIds.indexOf(String(location.desktopId || ""))
        : -1;
      return [ports.selectionKey(node), [
        desktopPosition >= 0 ? desktopPosition : Number.MAX_SAFE_INTEGER,
        location ? Number(location.top || 0) : Number.MAX_SAFE_INTEGER,
        location ? Number(location.left || 0) : Number.MAX_SAFE_INTEGER,
        location ? Number(location.z || 0) : Number.MAX_SAFE_INTEGER,
        Number(node.windowId || Number.MAX_SAFE_INTEGER),
        node.tabIndex ?? Number.MAX_SAFE_INTEGER,
        Number(node.tabId || Number.MAX_SAFE_INTEGER),
      ]];
    }));
    group.nodes.sort((left, right) => {
      const leftManual = Number(left.displayOrder || 0);
      const rightManual = Number(right.displayOrder || 0);
      if (leftManual > 0 || rightManual > 0) {
        if (leftManual <= 0) return 1;
        if (rightManual <= 0) return -1;
        if (leftManual !== rightManual) return leftManual - rightManual;
      }
      const leftPhysical = physicalOrder.get(ports.selectionKey(left)) || [];
      const rightPhysical = physicalOrder.get(ports.selectionKey(right)) || [];
      for (let index = 0; index < Math.max(leftPhysical.length, rightPhysical.length); index += 1) {
        const difference = Number(leftPhysical[index] || 0) - Number(rightPhysical[index] || 0);
        if (difference) return difference;
      }
      return ports.compareNodeOrder(left, right);
    });
    const groupSection = document.createElement("section");
    groupSection.className = "monitor-bct-scope-group";
    groupSection.dataset.scopeId = group.key;
    const groupHeader = document.createElement("button");
    groupHeader.type = "button";
    groupHeader.className = "monitor-bct-scope-heading";
    groupHeader.dataset.scopeId = group.key;
    groupHeader.setAttribute("aria-expanded", interactionState.isCollapsed(group.key) ? "false" : "true");
    const groupCaret = document.createElement("span");
    groupCaret.className = "monitor-bct-scope-caret";
    groupCaret.setAttribute("aria-hidden", "true");
    const groupText = document.createElement("span");
    groupText.textContent = `${group.name} · ${group.nodes.length}`;
    groupHeader.append(groupCaret, groupText);
    groupHeader.addEventListener("click", (event) => {
      if (ports.pointerDrag()?.active || interactionState.isScopeSuppressed(Date.now())) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      interactionState.toggleCollapsed(group.key);
      render(nodes);
    });
    const groupList = document.createElement("div");
    groupList.className = "monitor-bct-node-list";
    groupList.dataset.scopeId = group.key;
    groupList.dataset.scopeName = group.key === "__unassigned__" ? "" : group.name;
    groupSection.append(groupHeader, groupList);
    fragment.append(groupSection);
    if (interactionState.isCollapsed(group.key)) {
      groupList.hidden = true;
      continue;
    }
    if (!group.nodes.length) {
      const emptyDrop = document.createElement("div");
      emptyDrop.className = "monitor-bct-node-empty monitor-bct-node-drop-empty";
      emptyDrop.textContent = "여기에 놓으면 미소속";
      groupList.append(emptyDrop);
    }
    for (const [index, node] of group.nodes.entries()) {
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
    row.setAttribute("aria-selected", String(node.active === true));
    if (node.displayStale || node.instanceState !== "OPEN") row.classList.add("monitor-bct-node-stale");
    row.tabIndex = 0;
    row.draggable = false;
    const mappedHwnd = ports.hwndForWindow(node.windowId, ports.lastAiState(), node.instanceId, node.sessionId);
    const nativeLocation = mappedHwnd ? ports.locations().get(mappedHwnd) : null;
    const desktopPosition = nativeLocation
      ? ports.desktopState().desktopIds.indexOf(String(nativeLocation.desktopId || ""))
      : -1;
    row.title = node.conversationKey
      ? "클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동하고 정확한 대화 선택 · 우클릭: 정보와 이름 변경 · 600ms 길게 누르기: Manager 안내 태그 지정/해제"
      : "클릭: 연결 창 표시 · 더블클릭: 해당 데스크톱으로 이동";
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
    location.textContent = ports.nodeLocationText(node, desktopPosition);
    location.title = location.textContent;
    body.append(location);
    const presence = document.createElement("span");
    const stale = node.displayStale === true || node.instanceState !== "OPEN";
    presence.className = `monitor-bct-node-presence${!stale && node.generating === true ? " is-busy" : ""}`;
    presence.setAttribute("aria-label", stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음");
    presence.title = stale ? "관측 지연" : node.generating === true ? "응답 생성 중" : "열려 있음";
    ports.renderStatusIcon(presence, { activity: !stale && node.generating === true ? "play" : "pause" });
    row.append(number, body, presence);
    row.classList.toggle("is-manager", Array.isArray(node.roleTags) && node.roleTags.includes("Manager"));
    ports.managerHold(row, node);
    row.addEventListener("dragstart", (event) => event.preventDefault());
    row.addEventListener("pointerdown", (event) => ports.beginNodeDrag(event, row, node));
    row.addEventListener("click", (event) => {
      if (interactionState.consumeSuppressedKey(ports.selectionKey(node))) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      void ports.resolveDisplayHwnd(node).then((hwnd) => {
        ports.setSelected(ports.selectionKey(node));
        ports.selectHwnd(hwnd);
        ports.setStatus(`${node.nodeLabel || "N?"} 연결 웹브라우저 창을 표시했습니다.`, true, 1800);
      }).catch((error) => {
        ports.setStatus(`연결 창 표시 실패 · ${error?.message || error}`, false, 3500);
      });
    });
    row.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("monitor-bct-node-switch-pending");
      void ports.resolveHwnd(node).then((hwnd) => (
        ports.setSelected(ports.selectionKey(node)),
        ports.activateHwnd(hwnd, {
          tabId: node.tabId,
          windowId: node.windowId,
          conversationKey: node.conversationKey,
        })
      )).then((result) => {
        ports.setStatus(`${node.nodeLabel || "N?"} 창이 있는 D${result.index + 1}(으)로 이동해 정확한 ChatGPT 탭을 선택했습니다.`, true, 3200);
      }).catch((error) => {
        ports.setStatus(`노드 창 이동 실패 · ${error?.message || error}`, false, 4500);
      }).finally(() => {
        ports.after(() => row.classList.remove("monitor-bct-node-switch-pending"), 350);
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
        ports.openRename(node, row);
      });
    }
    groupList.append(row);
    }
  }
  root.replaceChildren(fragment);
  ports.syncHighlight();
  if (summary) {
    const stale = nodes.some((node) => node.displayStale === true);
    summary.textContent = stale
      ? `${nodes.length}개 · RCC 일시 지연 · 마지막 검증 목록`
      : `${nodes.length}개 · BCT/RCC 실시간 상태`;
  }
}

    return Object.freeze({render});
  }
  globalThis.MonitorNodePanelView=Object.freeze({create});
})();
