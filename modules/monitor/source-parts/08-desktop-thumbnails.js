function syncDesktopSwitcher() {
  let createdDesktopThumb = false;

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

      monitorDesktopThumbs.append(button); createdDesktopThumb = true;

    }

    button.dataset.index = String(index); button.classList.toggle("selected", index === monitorDesktopState.selectedIndex); button.classList.toggle("current", index === monitorDesktopState.currentIndex);
    monitorAttachDesktopManagementControl(button.querySelector(".monitor-desktop-thumb-label"), desktopId);

    const displayIndex = monitorDeletedDesktopUndo && Date.now() < monitorDeletedDesktopUndoExpiresAt && index >= Number(monitorDeletedDesktopUndo.index) ? index + 1 : index;

    const labelText=button.querySelector(".monitor-desktop-label-text"); if(labelText)labelText.textContent=`데스크톱 ${displayIndex + 1}`; const desktopBadge=button.querySelector(".monitor-desktop-number-badge"); if(desktopBadge)desktopBadge.textContent=`D${displayIndex + 1}`;

    existing.delete(desktopId);

  }

  syncMonitorMinimizedNodeBadges();

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

  // The selected desktop is refreshed by refreshVirtualDesktops(). Background
  // desktop pixels stay lazy until an explicit selection/layout operation.
  // Do not capture every desktop merely because its card was created.
  requestAnimationFrame(syncMonitorDesktopScrollArrows);

}

async function refreshObservedWindows() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  if (!monitorIsActiveDesktopRenderer()) return false;

  const desktopId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || null;

  if (!desktopId) return;

  const frame = await captureDesktopFrame(desktopId, "main");

  if (!frame || monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] !== desktopId) return;

  monitorWindowLayer.dataset.desktopId = desktopId;

  reconcileFrame(monitorWindowLayer, frame, "monitor-window-preview");

  // Keep small desktop cards lightweight even for the selected desktop.

  // The large preview above is the only surface that needs real captured pixels.

  const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (visual?.isConnected) await refreshDesktopThumb(visual, desktopId);
  syncMonitorMinimizedNodeBadges(monitorLastAiState);

}

globalThis.addEventListener("bwm-thumbnail-policy-changed", () => {
  const ids = [...(monitorDesktopState.desktopIds || [])].filter(Boolean);
  if (!ids.length || !monitorIsActiveDesktopRenderer()) return;
  invalidateMonitorDesktopFrames(...ids);
  void refreshSelectedThumb().catch(() => false);
  void refreshBackgroundThumbs(...ids).catch(() => []);
});
async function refreshDesktopThumbBatch() {

  if (monitorCapturePaused()) return;

  if (monitorThumbBatchInflight) return monitorThumbBatchInflight;

  const selectedDesktopId = String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "");
  if (!selectedDesktopId) return;

  const targets = [...monitorDesktopThumbs.children].map((button) => ({

    visual: button.querySelector(".monitor-desktop-thumb-visual"),

    desktopId: button.dataset.desktopId || ""

  })).filter((target) => target.desktopId === selectedDesktopId && target.visual?.isConnected);

  const job = (async () => {

    await refreshBackgroundThumbs(...targets.map((target) => target.desktopId));

  })().finally(() => {

    if (monitorThumbBatchInflight === job) monitorThumbBatchInflight = null;

  });

  monitorThumbBatchInflight = job;

  return job;

}

async function refreshSelectedThumb() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;

  const desktopId = monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "";

  if (!desktopId) return false;

  const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (!visual) return false;
  return await refreshDesktopThumb(visual, desktopId);

}

async function refreshInitialSelectedThumb() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  const ready = await refreshSelectedThumb().catch(() => false);
  monitorInitialThumbBatchDone = ready === true;
  if (monitorInitialThumbBatchDone) scheduleInitialSemanticThumbSync();
  // Background Desktop initialization is independent of the selected Desktop.
  // A transient selected capture failure must not prevent D2/D3/D4 from starting.
  await refreshInitialBackgroundThumbs();
  return monitorInitialThumbBatchDone;
}

async function refreshBackgroundThumbs(...desktopIds) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return [];
  if (!monitorIsActiveDesktopRenderer() || monitorCapturePaused()) return [];
  const selectedDesktopId = String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "");
  const ids = new Set(desktopIds.map((id) => String(id || "")).filter(Boolean));
  if (selectedDesktopId) ids.delete(selectedDesktopId);
  const failed = [];
  for (const desktopId of ids) {
    const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
    if (!visual?.isConnected) continue;
    const refreshed = await refreshDesktopThumb(visual, desktopId).catch(() => false);
    if (!refreshed) failed.push(desktopId);
  }
  return failed;
}

function scheduleInitialSemanticThumbSync(delay = 180) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return;
  if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight) return;
  if (monitorInitialSemanticThumbSyncTimer) clearTimeout(monitorInitialSemanticThumbSyncTimer);
  monitorInitialSemanticThumbSyncTimer = setTimeout(async () => {
    monitorInitialSemanticThumbSyncTimer = 0;
    if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight || !monitorInitialThumbBatchDone) return;
    const state = monitorLastAiState;
    const observer = state?.node_state?.observer;
    const semanticReady = state?.ok === true && (
      (String(observer?.source || "") === "ACT_NATIVE_OBSERVER" && Array.isArray(observer?.windows)) ||
      (Array.isArray(state?.endpoints) && state.endpoints.length > 0) ||
      (Array.isArray(state?.node_state?.nodes) && state.node_state.nodes.length > 0)
    );
    if (!semanticReady) return;
    monitorInitialSemanticThumbSyncInflight = true;
    try {
      syncMonitorAllDesktopThumbnailNodeBadges();
      monitorInitialSemanticThumbSyncDone = true;
    } finally {
      monitorInitialSemanticThumbSyncInflight = false;
    }
  }, Math.max(0, Number(delay) || 0));
}

let monitorThumbnailLayoutSignature = "";

function applyMonitorLiveWindowGeometry(desktopId, snap) {

  const actMeta = monitorActDesktopVisualForDesktop(desktopId);

  if (!actMeta || !snap?.ok) return;

  const vw = Math.max(1, Number(actMeta.previewVirtualWidth) || 1);

  const vh = Math.max(1, Number(actMeta.previewVirtualHeight) || 1);

  const vl = Number(actMeta.previewVirtualLeft || 0), vt = Number(actMeta.previewVirtualTop || 0);

  const rows = new Map((Array.isArray(snap.windows) ? snap.windows : []).map((item) => [String(item?.hwnd || ""), item]));

  const targets = [];

  const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === String(desktopId || ""));

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (visual) targets.push(visual);

  if (String(monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] || "") === String(desktopId || "")) targets.push(monitorWindowLayer);

  for (const container of targets) for (const img of container.querySelectorAll(".monitor-desktop-thumb-window[data-hwnd], .monitor-window-preview[data-hwnd]")) {

    const row = rows.get(String(img.dataset.hwnd || ""));

    if (!row) continue;

    if (Boolean(row.iconic)) { img.style.display = "none"; continue; }

    img.style.display = "";

    // getDesktopWindowHandles reports visibility/iconic state but may not include geometry.

    // Never overwrite a valid captured frame with 0x0 when rect fields are absent.

    const hasGeometry = [row.left,row.top,row.width,row.height].every((value) => Number.isFinite(Number(value)))

      && Number(row.width) > 0 && Number(row.height) > 0;

    if (hasGeometry) {

      img.style.left = `${((Number(row.left) - vl) / vw) * 100}%`;

      img.style.top = `${((Number(row.top) - vt) / vh) * 100}%`;

      img.style.width = `${(Number(row.width) / vw) * 100}%`;

      img.style.height = `${(Number(row.height) / vh) * 100}%`;

    }

    syncMonitorStatusLayer(img, img.dataset.hwnd || "");

    syncMonitorPauseOverlay(img, img.dataset.hwnd || "");

    syncMonitorDesktopNumberBadge(img, img.dataset.hwnd || "");

    syncMonitorNonChatCountdown(img, img.dataset.hwnd || "");

  }

}

async function monitorThumbnailLayoutWatch() {

  const desktopIds = monitorDesktopState.desktopIds.filter(Boolean);

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!desktopIds.length || !/^\d+$/.test(hostHwnd) || hostHwnd === "0") return;

  const parts = [];

  for (const desktopId of desktopIds) {

    const snap = await monitorNative({ type:"getDesktopWindowHandles", desktopId, hostWindowHwnd:hostHwnd, includeMonitorWindows:true }).catch(() => null);

    if (!snap?.ok) continue;

    applyMonitorLiveWindowGeometry(desktopId, snap);

    const rows = (Array.isArray(snap.windows) ? snap.windows : [])

      .filter((item) => String(item?.hwnd || "") !== hostHwnd)

      .map((item) => [String(item?.hwnd||""),Number(item?.left||0),Number(item?.top||0),Number(item?.width||0),Number(item?.height||0),Boolean(item?.iconic)].join(":"))

      .sort();

    parts.push(`${desktopId}=${rows.join(",")}`);

  }

  const signature = parts.join("|");

  if (!signature) return;

  if (!monitorThumbnailLayoutSignature) {

    monitorThumbnailLayoutSignature = signature;

    invalidateMonitorDesktopFrames(...desktopIds);

    void refreshSelectedThumb();
    void refreshBackgroundThumbs(...desktopIds);

    void refreshAiMonitor().catch(() => {});

    return;

  }

  if (signature !== monitorThumbnailLayoutSignature) {

    monitorThumbnailLayoutSignature = signature;

    // Recovery-only reconciliation. Live move/snap/desktop-transfer rendering is driven

    // by Native window events; never pause or schedule delayed redraws from this watcher.

    invalidateMonitorDesktopFrames(...desktopIds);

    void refreshSelectedThumb();
    void refreshBackgroundThumbs(...desktopIds);

    void refreshAiMonitor().catch(() => {});

  }

}

let monitorWindowsStateRefreshBusy = false;

async function refreshWindowsCurrentState() {
  if (monitorWindowsStateRefreshBusy) return;
  monitorWindowsStateRefreshBusy = true;
  try {
    await refreshVirtualDesktops();
  } finally {
    monitorWindowsStateRefreshBusy = false;
  }
}

function renderLightweightDesktopCards() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) { monitorDesktopThumbs.replaceChildren(); return true; }

  const ids = Array.isArray(monitorDesktopState.desktopIds) ? monitorDesktopState.desktopIds.filter(Boolean) : [];

  if (!ids.length) return false;

  monitorDesktopThumbs.replaceChildren();

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

    if (index === monitorDesktopState.selectedIndex) void refreshDesktopThumb(visual, desktopId);

  });

  syncMonitorMinimizedNodeBadges();
  return true;

}

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
    monitorPreviewWallpaper.style.backgroundImage = "";
    monitorPreviewWallpaper.dataset.desktopId = selectedId || "";
    monitorWindowLayer.replaceChildren();
    monitorFrameCache.clear();
    if (hostWindowChanged) void monitorPublishSharedInstance("host-hwnd-changed");
    return;
  }

  try {

    syncDesktopSwitcher();

  } catch (error) {

    console.warn("DesktopWindow Monitor desktop card renderer failed; using lightweight fallback", error);

    renderLightweightDesktopCards();

  }

  if (desktopIds.length && monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb[data-desktop-id]").length < desktopIds.length) {

    renderLightweightDesktopCards();

  }

  if (hostWindowChanged) {

    void monitorPublishSharedInstance("host-hwnd-changed");

    monitorFrameCache.clear();

    for (const visual of monitorDesktopThumbs.querySelectorAll(".monitor-desktop-thumb-visual")) delete visual.dataset.monitorFrameReady;

    setTimeout(() => { refreshObservedWindows(); refreshSelectedThumb(); }, 0);

  }

  if (selectedId) {

    const wallpaperChangedDesktop = monitorPreviewWallpaper.dataset.desktopId !== selectedId;

    applyObservedWallpaper(selectedId, wallpaperChangedDesktop);

  }

  if (selectedId && monitorWindowLayer.dataset.desktopId !== selectedId) {

    refreshObservedWindows();

  }

  if (monitorStructureOpen && document.getElementById("monitorStructureManagers")) renderMonitorStructure();

}

let monitorHostResolveRetryCount = 0;

let monitorHostResolveRetryTimer = 0;

async function refreshVirtualDesktops() {

  try {

    const currentWindow = await chrome.windows.getCurrent();

    let state = await monitorNative({

      type: "getVirtualDesktops", hostTitle: document.title,

      left: currentWindow?.left, top: currentWindow?.top,

      width: currentWindow?.width, height: currentWindow?.height

    });

    const hostResolved = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0";

    if (state?.ok && !hostResolved) {

      const titleOnlyState = await monitorNative({ type: "getVirtualDesktops", hostTitle: document.title }).catch(() => null);

      const titleResolved = /^\d+$/.test(String(titleOnlyState?.hostWindowHwnd || "")) && String(titleOnlyState?.hostWindowHwnd || "") !== "0";

      if (titleOnlyState?.ok && titleResolved) state = titleOnlyState;

    }

    if (state?.ok) {

      renderVirtualDesktops(state);

      const resolved = /^\d+$/.test(String(state?.hostWindowHwnd || "")) && String(state?.hostWindowHwnd || "") !== "0";

      if (resolved) {

        monitorHostResolveRetryCount = 0;

        if (monitorHostResolveRetryTimer) clearTimeout(monitorHostResolveRetryTimer);

        monitorHostResolveRetryTimer = 0;

        if (!monitorInitialThumbBatchDone) {

          monitorInitialThumbBatchDone = false;

          await refreshInitialSelectedThumb();

        }

      } else if (monitorHostResolveRetryCount < 8 && !monitorHostResolveRetryTimer) {

        monitorHostResolveRetryCount += 1;

        monitorHostResolveRetryTimer = setTimeout(() => {

          monitorHostResolveRetryTimer = 0;

          refreshVirtualDesktops();

        }, Math.min(1200, 250 + monitorHostResolveRetryCount * 150));

      }

    } else if (!monitorHostResolveRetryTimer) {

      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  } catch (_) {

    if (!monitorHostResolveRetryTimer) {

      monitorHostResolveRetryCount += 1;

      monitorHostResolveRetryTimer = setTimeout(() => { monitorHostResolveRetryTimer = 0; refreshVirtualDesktops(); }, Math.min(5000, 500 + monitorHostResolveRetryCount * 250));

    }

  }

}

function flashDesktopTransition() {

  monitorTransitionFlash.classList.remove("active");

  const button=[...monitorDesktopThumbs.children].find((node)=>Number(node.dataset.index)===monitorDesktopState.selectedIndex);

  if(!button)return;

  button.classList.remove("monitor-desktop-card-flash");

  void button.offsetWidth;

  button.classList.add("monitor-desktop-card-flash");

  setTimeout(()=>button.classList.remove("monitor-desktop-card-flash"),420);

}

function primeSelectedDesktopPreview(desktopId) {
  const id = String(desktopId || "");
  if (!id) return;
  const tile = [...monitorDesktopThumbs.children].find((button) => String(button.dataset.desktopId || "") === id);
  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
  monitorWindowLayer.replaceChildren();
  monitorWindowLayer.dataset.desktopId = id;
  if (!visual) return;
  if (visual.style.backgroundImage) {
    monitorPreviewWallpaper.style.backgroundImage = visual.style.backgroundImage;
    monitorPreviewWallpaper.dataset.desktopId = id;
  }
  for (const source of visual.querySelectorAll(".monitor-desktop-thumb-window")) {
    const img = source.cloneNode(false);
    img.className = "monitor-window-preview";
    img.dataset.hwnd = String(source.dataset.hwnd || "");
    monitorWindowLayer.append(img);
  }
}

function selectVirtualDesktopPreview(index) {

  const bounded = Math.min(Math.max(0, index), monitorDesktopState.count - 1);

  const changed = bounded !== monitorDesktopState.selectedIndex;

  if (changed) {

    monitorFrameGeneration += 1;

    monitorThumbBatchGeneration += 1;

    monitorFrameCache.clear();

    monitorFrameInflight.clear();

    monitorThumbBatchInflight = null;

  }

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

  refreshObservedWindows();

}

function expireDesktopUndoSession(now = Date.now()) {

  if (!monitorUndoStack.length || !monitorUndoSessionExpiresAt || now < monitorUndoSessionExpiresAt) return false;

  monitorUndoStack.length = 0;

  monitorUndoSessionExpiresAt = 0;

  return true;

}

function resetDesktopUndoSessionExpiry(now = Date.now()) {

  monitorUndoSessionExpiresAt = monitorUndoStack.length ? now + MONITOR_UNDO_TTL_MS : 0;

}

function pushDesktopUndoSnapshot(snapshot, now = Date.now()) {

  monitorUndoStack.push({ ...snapshot });

  while (monitorUndoStack.length > MONITOR_UNDO_MAX) monitorUndoStack.shift();

  resetDesktopUndoSessionExpiry(now);

}

function peekDesktopUndoSnapshot(now = Date.now()) {

  expireDesktopUndoSession(now);

  return monitorUndoStack[monitorUndoStack.length - 1] || null;

}

function commitDesktopUndoRestore(now = Date.now()) {

  if (monitorUndoStack.length) monitorUndoStack.pop();

  resetDesktopUndoSessionExpiry(now);

}

function updateDesktopUndoUi() {

  const now = Date.now();

  expireDesktopUndoSession(now);

  clearTimeout(monitorUndoTimer);

  const latest = monitorUndoStack[monitorUndoStack.length - 1] || null;

  monitorDesktopUndo.hidden = !latest;

  if (!latest) return;

  const seconds = Math.max(0, Math.ceil((monitorUndoSessionExpiresAt - now) / 1000));

  monitorDesktopUndoCountdown.textContent = `${seconds}s`;

  const label = latest.kind === "window-move" ? "window move" : latest.kind === "window-copy" ? "window copy" : latest.kind === "create-move" ? "new desktop move" : latest.kind === "create-copy" ? "new desktop copy" : `desktop ${Number(latest.index) + 1}`;

  monitorDesktopUndoButton.title = `Undo ${label} - ${seconds}s left`;

  monitorUndoTimer = setTimeout(updateDesktopUndoUi, Math.min(250, Math.max(50, monitorUndoSessionExpiresAt - now)));

}

function showDesktopUndo(snapshot) {

  pushDesktopUndoSnapshot(snapshot);

  updateDesktopUndoUi();

}

function updateDeletedDesktopTrashUi() {

  clearTimeout(monitorDeletedDesktopUndoTimer);

  if (!monitorDeletedDesktopUndo) return;

  const now=Date.now();

  if (now >= monitorDeletedDesktopUndoExpiresAt) { monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; syncDesktopSwitcher(); return; }

  syncDesktopSwitcher();

  monitorDeletedDesktopUndoTimer=setTimeout(updateDeletedDesktopTrashUi,250);

}

function showDeletedDesktopTrashUndo(snapshot) {

  monitorDeletedDesktopUndo={...snapshot}; monitorDeletedDesktopUndoExpiresAt=Date.now()+MONITOR_DESKTOP_TRASH_UNDO_MS; updateDeletedDesktopTrashUi();

}

async function undoDeletedDesktopTrash() {

  const snapshot=monitorDeletedDesktopUndo; if(!snapshot||Date.now()>=monitorDeletedDesktopUndoExpiresAt)return;

  const button=monitorDesktopThumbs.querySelector(".monitor-desktop-trash-placeholder-undo"); if(button)button.disabled=true;

  try {

    const beforeIds=new Set(monitorDesktopState.desktopIds);

    const result=await monitorNative({type:"restoreVirtualDesktop",hwnds:snapshot.hwnds,wallpaperPath:snapshot.wallpaperPath||""});

    if(!result?.ok)throw new Error(result?.error||"데스크톱 복구 실패");

    const resultIds=Array.isArray(result.desktopIds)?result.desktopIds:[];

    const restoredId=resultIds.find((id)=>!beforeIds.has(id))||resultIds[resultIds.length-1]||null;

    if(restoredId&&snapshot.wallpaperDataUri){monitorRememberWallpaperEntry(monitorWallpaperCache, restoredId, snapshot.wallpaperDataUri, MONITOR_WALLPAPER_CACHE_LIMIT);}

    monitorDeletedDesktopUndo=null; monitorDeletedDesktopUndoExpiresAt=0; clearTimeout(monitorDeletedDesktopUndoTimer);

    restoreMonitorDesktopNodeSnapshots(snapshot.nodes);

    if(snapshot.desktopId) deleteMonitorTrashedDesktop(snapshot.desktopId);

    monitorDesktopState.observedDesktopId=restoredId; renderVirtualDesktops(result); if(restoredId)settleNewDesktopWallpaper(restoredId).catch(()=>{});

  } catch(error) { setMonitorStatus(`데스크톱 복구 실패 · ${error?.message||error}`,false); if(button)button.disabled=false; }

}

async function removeVirtualDesktopPreview(index, options={}) {

  if (monitorDesktopState.count <= 1 || index < 0 || index >= monitorDesktopState.count) return;

  const desktopId = monitorDesktopState.desktopIds[index] || null;

  const fallbackIndex = index < monitorDesktopState.count - 1 ? index + 1 : index - 1;

  try {

    const nodeSnapshots = monitorDesktopNodeSnapshots(desktopId,index);

    const snapshot = desktopId ? await monitorNative({ type: "getDesktopWindowHandles", desktopId }) : null;

    const wallpaperInfo = desktopId ? await monitorNative({ type: "getDesktopWallpaperInfo", desktopId }).catch(() => null) : null;

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

    const undoSnapshot={kind:"desktop-delete",desktopId,index,hwnds,nodes:nodeSnapshots,wallpaperPath:wallpaperInfo?.path||"",wallpaperDataUri,thumbnail};

    storeMonitorTrashedDesktop({desktopId,index,desktop_number:index+1,thumbnail,hwnds,nodes:nodeSnapshots,wallpaperPath:wallpaperInfo?.path||""});

    showDeletedDesktopTrashUndo(undoSnapshot);

    flashDesktopTransition();

  } catch (error) { setMonitorStatus(`데스크톱 삭제 실패 · ${error?.message || error}`, false); }

}

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

monitorDesktopUndoButton.addEventListener("click", async () => {

  updateDesktopUndoUi(); const snapshot = peekDesktopUndoSnapshot(); if (!snapshot) return; monitorDesktopUndoButton.disabled = true;

  try {

    if (["window-move", "create-move"].includes(snapshot.kind)) {

      for (const entry of Array.isArray(snapshot.entries) ? snapshot.entries : []) await monitorNative({ type: "moveWindowToDesktop", hwnd: String(entry.hwnd), desktopId: String(entry.desktopId) }).catch(() => null);

      if (snapshot.kind === "create-move") await removeCreatedDesktopIfSafe(snapshot);

      commitDesktopUndoRestore(); updateDesktopUndoUi(); await refreshVirtualDesktops(); refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(...(Array.isArray(snapshot.entries) ? snapshot.entries.map((entry)=>String(entry.desktopId||"")) : []), String(snapshot.targetDesktopId||"")); return;

    }

    if (["window-copy", "create-copy"].includes(snapshot.kind)) {

      for (const hwnd of Array.isArray(snapshot.hwnds) ? snapshot.hwnds : []) await monitorNative({ type: "closeWindow", hwnd: String(hwnd) }).catch(() => null);

      if (snapshot.kind === "create-copy") await removeCreatedDesktopIfSafe(snapshot);

      commitDesktopUndoRestore(); updateDesktopUndoUi(); refreshObservedWindows(); refreshSelectedThumb(); refreshBackgroundThumbs(String(snapshot.targetDesktopId||"")); return;

    }

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const result = await monitorNative({ type: "restoreVirtualDesktop", hwnds: snapshot.hwnds, wallpaperPath: snapshot.wallpaperPath || "" });

    if (!result?.ok) throw new Error(result?.error || "데스크톱 복구 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const restoredId = resultIds.find((id) => !beforeIds.has(id)) || resultIds[resultIds.length - 1] || null;

    if (restoredId && snapshot.wallpaperDataUri) { monitorRememberWallpaperEntry(monitorWallpaperCache, restoredId, snapshot.wallpaperDataUri, MONITOR_WALLPAPER_CACHE_LIMIT);  }

    commitDesktopUndoRestore(); updateDesktopUndoUi();

    monitorDesktopState.observedDesktopId = restoredId;

    renderVirtualDesktops(result); selectVirtualDesktopPreview(monitorDesktopState.selectedIndex); settleNewDesktopWallpaper(restoredId).catch(() => {});

  } catch (error) { setMonitorStatus(`데스크톱 복구 실패 · ${error?.message || error}`, false); }

  finally { monitorDesktopUndoButton.disabled = false; }

});

async function settleNewDesktopWallpaper(createdId, expectedWallpaperPath = "") {

  if (!createdId) return;

  const started = Date.now(); let ready = false;

  while (Date.now() - started < 5000) {

    const info = await monitorNative({ type: "getDesktopWallpaperInfo", desktopId: createdId }).catch(() => null);

    const path = String(info?.path || "").trim().toLowerCase();

    const expected = String(expectedWallpaperPath || "").trim().toLowerCase();

    if (info?.ready && (!expected || path === expected)) { ready = true; break; }

    await new Promise((resolve) => setTimeout(resolve, 160));

  }

  if (!ready) return;

  monitorWallpaperCache.delete(createdId);

  const dataUri = await getObservedWallpaper(createdId, true);

  if (monitorDesktopState.desktopIds[monitorDesktopState.selectedIndex] === createdId && dataUri) monitorPreviewWallpaper.style.backgroundImage = `url("${dataUri}")`;

  const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === createdId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (visual) {
    void globalThis.MonitorDesktopThumbnailV2.refreshWallpaper(
      visual,createdId,id=>monitorNative({type:"getDesktopVisualSnapshot",desktopId:id,
        maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,quality:68}),
      {force:true}).catch(()=>false);
  }

}

monitorCreateDesktop.addEventListener("click", async () => {

  if (Date.now() < monitorCreateDesktopDropConsumedUntil || monitorCreateDesktopDropBusy) return;

  monitorCreateDesktop.disabled = true;

  try {

    const beforeIds = new Set(monitorDesktopState.desktopIds);

    const liveBefore = await monitorNative({ type: "getVirtualDesktops" }).catch(() => null);

    const liveIds = Array.isArray(liveBefore?.desktopIds) ? liveBefore.desktopIds : monitorDesktopState.desktopIds;

    const liveIndexRaw = Number(liveBefore?.currentIndex);

    const liveIndex = Number.isInteger(liveIndexRaw) && liveIndexRaw >= 0 && liveIndexRaw < liveIds.length ? liveIndexRaw : monitorDesktopState.currentIndex;

    const sourceDesktopId = liveIds[liveIndex] || monitorDesktopState.currentDesktopId || null;

    const sourceWallpaper = sourceDesktopId ? await getObservedWallpaper(sourceDesktopId, true) : "";

    const sourceWallpaperInfo = sourceDesktopId ? await monitorNative({ type: "getDesktopWallpaperInfo", desktopId: sourceDesktopId }).catch(() => null) : null;

    const result = await monitorNative({ type: "createVirtualDesktop" });

    if (!result?.ok) throw new Error(result?.error || "새 데스크톱 생성 실패");

    const resultIds = Array.isArray(result.desktopIds) ? result.desktopIds : [];

    const createdId = resultIds.find((id) => !beforeIds.has(id)) || resultIds[resultIds.length - 1] || null;

    if (createdId && sourceWallpaper) {

      monitorRememberWallpaperEntry(monitorWallpaperCache, createdId, sourceWallpaper, MONITOR_WALLPAPER_CACHE_LIMIT);

    }

    monitorDesktopState.observedDesktopId = createdId;

    renderVirtualDesktops(result);

    selectVirtualDesktopPreview(monitorDesktopState.selectedIndex);

    settleNewDesktopWallpaper(createdId, sourceWallpaperInfo?.path || "").catch(() => {});

  } catch (error) {

    monitorCreateDesktop.title = error?.message || String(error);

  } finally { monitorCreateDesktop.disabled = false; }

});

let monitorExpandedGeometry = null;

monitorCollapse.addEventListener("click", () => {

  const wasCollapsed = monitorRoot.classList.contains("collapsed");

  if (!wasCollapsed) {

    const rootRect = monitorRoot.getBoundingClientRect();

    monitorExpandedGeometry = {

      top: rootRect.top,

      right: Math.max(0, window.innerWidth - rootRect.right),

      width: rootRect.width,

      height: rootRect.height

    };

    monitorRoot.style.width = "";

    monitorRoot.style.height = "";

    monitorRoot.classList.add("collapsed");

    monitorRoot.style.left = "auto";

    monitorRoot.style.right = `${Math.round(monitorExpandedGeometry.right)}px`;

    monitorRoot.style.top = `${Math.round(monitorExpandedGeometry.top)}px`;

  } else {

    monitorRoot.classList.remove("collapsed");

    monitorRoot.style.left = "auto";

    monitorRoot.style.right = `${Math.round(monitorExpandedGeometry?.right ?? 12)}px`;

    monitorRoot.style.top = `${Math.round(monitorExpandedGeometry?.top ?? 12)}px`;

    if (monitorExpandedGeometry?.width) monitorRoot.style.width = `${Math.round(monitorExpandedGeometry.width)}px`;

    if (monitorExpandedGeometry?.height) monitorRoot.style.height = `${Math.round(monitorExpandedGeometry.height)}px`;

  }

  const collapsed = monitorRoot.classList.contains("collapsed");

  if (collapsed && monitorStructureOpen) closeMonitorStructure();

  document.body.classList.toggle("desktop-window-monitor-collapsed", collapsed);
  if (!collapsed) requestAnimationFrame(syncMonitorPanelToDesktopSwitcher);

  syncMonitorSideNote();

  monitorCollapse.classList.toggle("is-collapsed", collapsed);

  monitorCollapse.title = collapsed ? "Monitor 펼치기" : "Monitor 접기";

  if (!collapsed) {

    refreshObservedWindows();

    refreshSelectedThumb();

  }

});

let monitorDeploymentCheckBusy = false;

let monitorReloadToken = null;
let monitorDeploymentReloadRequested = false;

async function checkMonitorDeploymentUpdate() {

  if (monitorDeploymentCheckBusy) return;

  monitorDeploymentCheckBusy = true;

  try {

    const info = await monitorNative({ type: "getDeploymentInfo" });

    const running = chrome.runtime.getManifest().version;

    const reloadToken = String(info?.reloadToken || "");

    const publishedVersion = String(info?.version || "");
    const versionMismatch = Boolean(
      publishedVersion && publishedVersion.localeCompare(
        String(running), undefined, { numeric: true, sensitivity: "base" }
      ) !== 0
    );

    if (versionMismatch) {
      setMonitorStatus(`업데이트 ${publishedVersion} 감지 · 설치본 재로드 중`, false);
      if (!monitorDeploymentReloadRequested) {
        monitorDeploymentReloadRequested = true;
        chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {
          monitorDeploymentReloadRequested = false;
        });
      }
      return;
    }

    if (monitorReloadToken === null) {

      monitorReloadToken = reloadToken;

      if (reloadToken) await monitorNative({ type: "ackExtensionReload", token: reloadToken }).catch(() => null);

    } else if (reloadToken && reloadToken !== monitorReloadToken) {

      if (!monitorDeploymentReloadRequested) {
        monitorDeploymentReloadRequested = true;
        setMonitorStatus("새 설치본 감지 · 설치본 재로드 중", false);
        chrome.runtime.sendMessage({ type: "monitor-reload-extension" }).catch(() => {
          monitorDeploymentReloadRequested = false;
        });
      }
      return;

    }

    // A reload can recreate the popup after its HWND-change event has already
    // run. Publish one fresh presence record once the token is known; this is
    // a startup/deployment event, not a timer or a background polling loop.
    if (reloadToken && monitorReloadToken === reloadToken) {
      await monitorPublishSharedInstance("deployment-token-ready");
    }
    monitorDeploymentReloadRequested = false;

  } catch (_) {} finally { monitorDeploymentCheckBusy = false; }

}

// Desktop selection is synchronized through the Native shared selection state so

// NAVER/GOOGLE Chrome profiles observe the same desktop.

monitorSharedSelectionReady = true;

if (MONITOR_ACTIVE_STARTUP_ENABLED) {
  chrome.storage.local.get([MONITOR_POST_WORK_STORAGE_KEY, MONITOR_LLM_CACHE_STORAGE_KEY, MONITOR_AI_STATE_CACHE_KEY], (data) => {
    const saved=data?.[MONITOR_POST_WORK_STORAGE_KEY]||{};
    for(const key of Array.isArray(saved.worked)?saved.worked:[]) monitorWorkedConversationKeys.add(String(key));
    for(const key of Array.isArray(saved.acknowledged)?saved.acknowledged:[]) monitorAcknowledgedPostWork.add(String(key));
    for(const reportId of Array.isArray(saved.acknowledgedReports)?saved.acknowledgedReports:[]) monitorAcknowledgedReportIds.add(String(reportId));
    for(const key of Array.isArray(saved.alerts)?saved.alerts:[]) monitorPostWorkAlerts.add(String(key));
    for(const [key,detail] of Object.entries(saved.details||{})) if(key&&detail&&typeof detail==="object") monitorChatAlertDetails.set(String(key),detail);
    for(const key of monitorPostWorkAlerts) if(!monitorChatAlertDetails.has(key)) monitorChatAlertDetails.set(key,{symbol:"!",tone:"general",label:"채팅 작업 완료"});
    const observed=Number(saved.lastObservedAt||0); if(Number.isFinite(observed)&&observed>0) monitorPostWorkLastObservedAt=observed;
    monitorCachedLlmNodes = Array.isArray(data?.[MONITOR_LLM_CACHE_STORAGE_KEY]) ? data[MONITOR_LLM_CACHE_STORAGE_KEY] : [];
    const cachedAiState=data?.[MONITOR_AI_STATE_CACHE_KEY];
    if(cachedAiState?.state?.ok===true && Date.now()-Number(cachedAiState?.at||0)<=MONITOR_AI_STATE_CACHE_TTL_MS){
      monitorLastAiState=cachedAiState.state;
      renderWorkers(monitorLastAiState);
    }
    monitorPostWorkStorageReady=true;
    if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) {
      void monitorSyncSharedState("startup", true);
      void (async () => {
        try { await refreshMonitorEndpointRegistry(); }
        catch (error) { console.warn("BCT Window Monitor legacy endpoint reconciliation failed", error); }
        await refreshAiMonitor();
      })();
      scheduleMonitorStartupRecovery();
    }
  });
  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();
  void refreshWindowsCurrentState();
  checkMonitorDeploymentUpdate();
}

// Lightweight endpoint/node-state refresh keeps same-tab conversation changes responsive
// without running the heavier full refresh/sync pipeline for every state change.
let monitorConversationStateRefreshBusy = false;
let monitorConversationStateForceBadgeSyncPending = false;
let monitorConversationStateSignatureCache = "";

function monitorConversationStateSignature(state) {
  const endpoints=(Array.isArray(state?.endpoints)?state.endpoints:[])
    .filter((endpoint)=>String(endpoint?.presence_state||"").toUpperCase()==="OPEN")
    .map((endpoint)=>[
      String(endpoint?.profile_id||"").toUpperCase(),
      String(endpoint?.transport_instance_id||""),
      String(endpoint?.tab_id??""),
      String(endpoint?.conversation_key||""),
      String(endpoint?.window_id??""),
      String(endpoint?.metadata?.tab_active===true),
      String(endpoint?.metadata?.window_bounds?.state||"").toLowerCase()
    ].join(":"))
    .sort()
    .join("|");
  const nodes=(Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[])
    .map((node)=>[
      String(node?.node_label||"").toUpperCase(),
      String(node?.browser_node_id||""),
      String(node?.hwnd||""),
      String(node?.desktop_id||""),
      String(node?.location_authority||"")
    ].join(":"))
    .sort()
    .join("|");
  const windows=(Array.isArray(state?.node_state?.observer?.windows)?state.node_state.observer.windows:[])
    .map((row)=>[
      String(row?.hwnd||""),
      String(row?.desktop_id||""),
      String(row?.conversation_key||"")
    ].join(":"))
    .sort()
    .join("|");
  return `e:${endpoints}||n:${nodes}||w:${windows}`;
}

async function refreshMonitorConversationStateFast(forceBadgeSync = false) {
  if (forceBadgeSync) monitorConversationStateForceBadgeSyncPending = true;
  if (monitorConversationStateRefreshBusy || monitorRefreshBusy) return;
  monitorConversationStateRefreshBusy = true;
  try {
    const response = await actFetch(ORCHESTRATOR_MONITOR_STATE_URL, { cache: "no-store" }).catch(() => null);
    if (!response?.ok) return;
    const state = await response.json().catch(() => null);
    if (!state?.ok) return;
    const signature = monitorConversationStateSignature(state);
    const previous = monitorConversationStateSignatureCache || monitorConversationStateSignature(monitorLastAiState);
    const forceSync=monitorConversationStateForceBadgeSyncPending;
    monitorConversationStateForceBadgeSyncPending=false;
    monitorConversationStateSignatureCache = signature;
    const changed=signature!==previous;
    if (!changed && !forceSync) return;
    state.llm_nodes = Array.isArray(monitorLastAiState?.llm_nodes) ? monitorLastAiState.llm_nodes : monitorCachedLlmNodes;
    monitorLastAiState = state;
    pruneMonitorEphemeralGenerationState(state);
    chrome.storage.local.set({ [MONITOR_AI_STATE_CACHE_KEY]: { at: Date.now(), state } }).catch(() => {});
    if(changed) renderWorkers(state);
    syncMonitorAllDesktopThumbnailNodeBadges();
    scheduleInitialSemanticThumbSync();
  } finally {
    monitorConversationStateRefreshBusy = false;
    if (monitorConversationStateForceBadgeSyncPending && !monitorRefreshBusy) setTimeout(()=>{ void refreshMonitorConversationStateFast(); },0);
  }
}

if (MONITOR_ACTIVE_STARTUP_ENABLED && MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) void refreshMonitorConversationStateFast();
if (MONITOR_ACT_STARTUP_TEST_ENABLED) {
  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();
  void (async () => {
    try { await refreshMonitorEndpointRegistry(); }
    catch (error) { console.warn("DesktopWindow Monitor ACT-only endpoint reconciliation failed", error); }
    await refreshAiMonitor();
  })();
  void refreshMonitorConversationStateFast();
}

// ACT health is checked only on startup/focus/actions; no periodic liveness polling.

// Shared runtime sync is event-driven: startup/focus/state changes.

// Windows desktop structure + window layout now share one adaptive Native Host polling loop.

// Non-chat countdown updates are event-driven; no global 1s countdown loop.

// monitorThumbnailLayoutWatch is driven by refreshWindowsCurrentState().

// Shared desktop selection is read on startup/focus; local changes publish immediately.

// Post-work acknowledgement shares the single foreground click sampler below; do not consume click state in a second poll.

// Thumbnail pixels refresh only when window layout changes or an explicit UI event requests it.

// Deployment/reload checks are event-driven: startup/focus.

let monitorFocusRefreshQueued = false;

window.addEventListener("focus", () => {
  if (!MONITOR_ACTIVE_STARTUP_ENABLED) return;
  if (monitorFocusRefreshQueued) return;
  monitorFocusRefreshQueued = true;
  queueMicrotask(() => {
  monitorFocusRefreshQueued = false;

  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshActHealth();

  if (MONITOR_LEGACY_ACT_COMPATIBILITY_ENABLED) refreshAiMonitor();

  void refreshMonitorBctStatus();
  void refreshMonitorBctWindowNodes();

  void refreshWindowsCurrentState();

  void monitorSyncSharedState("focus", true);

  void refreshMonitorSharedNote();

  void refreshMonitorSharedNoteView();

  void checkMonitorDeploymentUpdate();

  });

});

/* MONITOR_BOTTOM_DIAGNOSTICS_V1 */

const monitorAutoProcessQuick=document.createElement("button");

monitorAutoProcessQuick.id="monitorAutoProcessQuick";

monitorAutoProcessQuick.type="button";

monitorAutoProcessQuick.textContent="자동 처리 OFF";

monitorAutoProcessQuick.className="monitor-diagnostics-status-item monitor-diagnostics-status-toggle is-unknown";

const monitorStructureQuick=document.createElement("button");

monitorStructureQuick.id="monitorStructureQuick"; monitorStructureQuick.type="button"; monitorStructureQuick.textContent="조직도";

document.getElementById("monitorNodeSync")?.after(monitorStructureQuick);

const monitorStructurePanel=document.createElement("aside"); monitorStructurePanel.id="monitorStructurePanel"; monitorStructurePanel.hidden=true;

monitorStructurePanel.style.cssText="position:fixed;z-index:2147483646;right:22px;top:72px;width:min(520px,calc(100vw - 44px));max-height:calc(100vh - 120px);overflow:auto;padding:12px;border:1px solid rgba(255,255,255,.20);border-radius:12px;background:rgba(10,14,20,.97);box-shadow:0 14px 44px rgba(0,0,0,.55);color:#eef3f8;font:12px/1.4 'Segoe UI','Malgun Gothic',sans-serif";

monitorStructurePanel.innerHTML=`<div class="monitor-org-head"><strong>조직도</strong><button id="monitorStructureClose" type="button">×</button></div><div class="monitor-org-pyramid"><svg id="monitorStructureLinks" class="monitor-org-links" aria-hidden="true"></svg><div id="monitorStructureManagers" class="monitor-org-managers"></div><div class="monitor-org-codex-manager"><strong>CODEX MANAGER</strong><div id="monitorStructureCodexManagerState" class="monitor-org-codex-manager-state">UNASSIGNED ? CODEX workspace</div><small>Dedicated code-management slot; real ChatGPT Manager identity is assigned separately.</small></div><div class="monitor-org-resource-pool-title">Shared AI Resource Pool <small>ACT state view ? execution owned by ACT/Hybrid</small></div><div class="monitor-org-resource-pools"><section><strong>LOCAL</strong><div id="monitorStructureLocalPool" class="monitor-org-resource-pool"></div></section><section><strong>EXTERNAL</strong><div id="monitorStructureExternalPool" class="monitor-org-resource-pool"></div></section><section class="monitor-org-codex-pool"><strong>CODEX</strong><div id="monitorStructureCodexPool" class="monitor-org-resource-pool"></div></section></div></div><div id="monitorStructureStatus" class="monitor-org-status">노드 드래그: 빈 역할 노드 또는 +에 놓아 Desk 이동 · 노드에 놓아 연결 · 선=실제 관리 연결 · 실행 후 ACT 확정</div><div class="monitor-org-actions"><button id="monitorStructureUndo" type="button" class="monitor-org-history" title="조직도 변경 되돌리기" aria-label="조직도 변경 되돌리기" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7 4 12l5 5M5 12h8a6 6 0 0 1 6 6"/></svg></button><button id="monitorStructureRedo" type="button" class="monitor-org-history" title="조직도 변경 다시하기" aria-label="조직도 변경 다시하기" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 7 5 5-5 5m4-5h-8a6 6 0 0 0-6 6"/></svg></button><button id="monitorStructureClear" type="button" class="monitor-org-clear" title="마지막 안정 조직도 상태로 되돌리기">초기화</button><button id="monitorStructureAutoLayout" type="button" title="현재 실제 노드 위치 기준으로 다시 배치">자동배치</button><button id="monitorStructurePlacementSave" type="button" title="역할·관리선은 확정하지 않고 실제 Desk 위치만 적용">위치 변경 확정</button><button id="monitorStructureSave" type="button" class="monitor-org-save">실행</button></div>`;

document.body.append(monitorStructurePanel);

// Organization-chart presentation is canonical in monitor.css (MONITOR_ORG_UI_CANONICAL_V1).

let monitorStructureHtmlDragGhost=null;

function monitorStructureFinishHtmlDragGhost(){
  destroyMonitorNodeDragGhost(monitorStructureHtmlDragGhost);
  monitorStructureHtmlDragGhost=null;
}

function monitorStructureTrackHtmlDragGhost(event){
  if(!monitorStructureHtmlDragGhost)return;
  moveMonitorNodeDragGhost(monitorStructureHtmlDragGhost,event.clientX,event.clientY);
}

function monitorStructureUseNodeDragGhost(event){
  const source=event?.target?.closest?.(".monitor-org-node-card,.monitor-org-bundle,.monitor-worker-row")||event?.currentTarget;
  if(!source)return;
  monitorStructureFinishHtmlDragGhost();
  const ghost=createMonitorNodeDragGhost(source,event);
  if(!ghost)return;
  ghost.classList.add("monitor-org-drag-ghost");
  ghost.style.transform="translate3d(-10000px,-10000px,0)";
  monitorStructureHtmlDragGhost=ghost;
  try{const nativeDragImage=document.createElement("canvas");nativeDragImage.width=1;nativeDragImage.height=1;event?.dataTransfer?.setDragImage(nativeDragImage,0,0);}catch(_){}
  requestAnimationFrame(()=>{if(monitorStructureHtmlDragGhost===ghost)moveMonitorNodeDragGhost(ghost,event.clientX,event.clientY);});
}

document.addEventListener("dragover",monitorStructureTrackHtmlDragGhost,true);
document.addEventListener("dragend",monitorStructureFinishHtmlDragGhost,true);
document.addEventListener("drop",monitorStructureFinishHtmlDragGhost,true);

const monitorDiagnostics=document.createElement("details");

monitorDiagnostics.className="monitor-bottom-diagnostics";
monitorDiagnostics.hidden=true;

monitorDiagnostics.innerHTML=`<summary class="monitor-diagnostics-summary"><span class="monitor-diagnostics-label">진단</span><span id="monitorServiceDiag" class="monitor-diagnostics-message">ACT 확인 중…</span><button id="monitorDiagToggle" class="monitor-diagnostics-toggle" type="button" title="진단 상세 화면 펼치기/접기" aria-label="진단 상세 화면 펼치기">펼치기</button></summary><div class="monitor-diagnostics-body"><div class="monitor-diagnostics-topline"><div id="monitorDiagStatusBar" class="monitor-diagnostics-status-bar"><span id="monitorDiagAct" class="monitor-diagnostics-status-item is-unknown">ACT: ?</span></div><div class="monitor-diagnostics-toolbar"><span id="monitorDiagLogCopyState" class="monitor-diagnostics-copy-state"></span><button id="monitorDiagLogCopy" class="monitor-diagnostics-icon-button" type="button" title="현재 관제 내용 복사" data-tip="현재 관제 내용 복사" aria-label="현재 관제 내용 복사"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7h11v13H8z"></path><path d="M5 17H3V4h11v2"></path></svg></button><button id="monitorDiagRefresh" class="monitor-diagnostics-icon-button" type="button" title="현재 선택한 관제 정보 다시 확인" data-tip="현재 선택한 관제 정보 다시 확인" aria-label="현재 선택한 관제 정보 다시 확인"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66"></path><path d="M20 4v7h-7"></path></svg></button></div></div><pre id="monitorDiagLog" class="monitor-diagnostics-log">종합 관제 · 아래 항목을 선택하면 이 영역에 세부 정보가 표시됩니다.</pre><div id="monitorDiagFooter" class="monitor-diagnostics-footer"><div class="monitor-diagnostics-tabs"><button class="monitor-diagnostics-tab is-active" type="button" data-monitor-diag-view="overview">종합</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="act">ACT</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="github">GitHub</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="monitor">Monitor</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="console">Console</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="windows">Windows</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="runner">Runner</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="rcc">RCC</button><button class="monitor-diagnostics-tab" type="button" data-monitor-diag-view="rally">Rally</button></div></div></div>`;

monitorRoot.append(monitorDiagnostics);

const monitorServiceDiagInitial=document.getElementById('monitorServiceDiag');


if(monitorServiceDiagInitial && monitorService){


  monitorServiceDiagInitial.textContent=monitorService.textContent;


  const healthy=monitorService.classList.contains('healthy');


  monitorServiceDiagInitial.classList.toggle('healthy',healthy);


  monitorServiceDiagInitial.style.color=healthy?"rgba(154,236,181,.96)":"rgba(255,211,145,.90)";


  monitorServiceDiagInitial.title=monitorService.textContent;


}

const monitorDiagAct=document.getElementById('monitorDiagAct');

const monitorDiagLog=document.getElementById('monitorDiagLog');

const monitorDiagLogCopyState=document.getElementById('monitorDiagLogCopyState');

const monitorDiagToggle=document.getElementById('monitorDiagToggle');
const monitorDiagStatusBar=document.getElementById('monitorDiagStatusBar');
monitorAutoProcessQuick.textContent='AUTO: ?';
monitorAutoProcessQuick.title='자동 처리 상태 · 클릭하여 ON/OFF';
monitorDiagStatusBar?.append(monitorAutoProcessQuick);

let monitorAutoProcessEnabled=false;

function monitorStructureNodeFromWorker(worker,state){

  const key=String(worker?.conversation_key||"").trim(); if(!key)return null;

  const endpoints=monitorOpenEndpointsForConversation(state,key); if(endpoints.length!==1)return null;

  const ep=endpoints[0]; const location=monitorCanonicalPhysicalLocation(worker,state);

  const hwnd=String(location?.hwnd||""); const remembered=monitorWindowDesktopLocations.get(hwnd);

  const desktopId=String(location?.location?.desktopId||location?.desktopId||remembered?.desktopId||"");

  const stableKey=monitorStableBrowserNodeKey(worker);

  const stable=(stableKey&&monitorStableNodeSlotRecord(worker,stableKey))||monitorStableNodeSlot(worker,state);

  const stableLabel=stable&&Number(stable.desktop)>0&&Number(stable.slot)>0?`D${stable.desktop}-${stable.slot}`:"";

  const orderMatch=stableLabel.match(/-(\d+)\b/);

  return {conversation_key:key,profile_id:String(ep?.profile_id||"").toUpperCase(),role:String(worker?.role||"").toUpperCase(),exemption:worker?.exemption||null,transport_instance_id:String(ep?.transport_instance_id||""),session_id:String(ep?.session_id||""),tab_id:ep?.tab_id??null,hwnd,desktop_id:desktopId,node_order:orderMatch?Number(orderMatch[1]):999,label:stableLabel||String(location?.label||"")||key.slice(0,8),title:monitorWorkerMeaningfulTitle(worker,state,ep)||""};

}

function monitorStructureNodeIdentityTokens(node){
  const label=String(node?.label||"").trim().toUpperCase();
  if(/^D\d+[-_]\d+$/.test(label))return [`act:${label}`];
  const tabId=String(node?.tab_id??"").trim();
  const conversationKey=String(node?.conversation_key||"").trim();
  if(tabId&&conversationKey)return [`tab:${tabId}:conversation:${conversationKey}`];
  return [`conversation:${conversationKey}`];
}

function monitorStructureAvailableNodes(){

  const state=monitorLastAiState||{}; const seen=new Set(), seenPhysicalNodes=new Set(), out=[];

  for(const worker of monitorWorkersForState(state)){
    const profile=String(worker?.profile_id||"").toUpperCase();
    if(!["GOOGLE","NAVER"].includes(profile))continue;
    const node=monitorStructureNodeFromWorker(worker,state);
    if(!node)continue;
    const identityTokens=monitorStructureNodeIdentityTokens(node);
    if(seen.has(node.conversation_key)||identityTokens.some(token=>seenPhysicalNodes.has(token)))continue;
    seen.add(node.conversation_key);
    identityTokens.forEach(token=>seenPhysicalNodes.add(token));
    out.push(node);
  }
  return out;

}

