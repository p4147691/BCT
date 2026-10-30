//@@FN_START:applyObservedWallpaper
async function applyObservedWallpaper(desktopId, force = false) {
  const token = ++monitorWallpaperToken;
  const id=String(desktopId||"").toLowerCase();
  monitorPreviewBackground.begin(id);
  const tile=[...monitorDesktopThumbs.children].find(button=>String(button.dataset.desktopId||"").toLowerCase()===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  if(!visual?.isConnected||!renderer?.refreshBackground){
    if(token===monitorWallpaperToken)monitorPreviewBackground.failed(id);
    return false;
  }
  await renderer.refreshBackground(visual,id,{forceWallpaper:force===true}).catch(()=>null);
  if (token !== monitorWallpaperToken) return;
  return syncMonitorPreviewBackground(visual,id);
}
//@@FN_END:applyObservedWallpaper

//@@FN_START:monitorAcceptedDesktopBackground
async function monitorAcceptedDesktopBackground(desktopId, force = false) {
  const id=String(desktopId||"").toLowerCase();
  const tile=[...monitorDesktopThumbs.children].find(button=>String(button.dataset.desktopId||"").toLowerCase()===id);
  const visual=tile?.querySelector(".monitor-desktop-thumb-visual");
  const renderer=globalThis.MonitorDesktopThumbnailV2;
  if(!visual?.isConnected||!renderer?.refreshBackground)return null;
  await renderer.refreshBackground(visual,id,{forceWallpaper:force===true}).catch(()=>null);
  return renderer.acceptedBackground?.(visual,id)||null;
}
//@@FN_END:monitorAcceptedDesktopBackground

//@@FN_START:syncMonitorPreviewBackground
function syncMonitorPreviewBackground(visual,desktopId) {
  const id=String(desktopId||"").toLowerCase();
  const selected=String(monitorDesktopIdentityState.snapshot().desktopIds[monitorDesktopIdentityState.snapshot().selectedIndex]||"").toLowerCase();
  if(!id||id!==selected)return false;
  const snapshot=globalThis.MonitorDesktopThumbnailV2?.acceptedBackground?.(visual,id)||null;
  return snapshot ? monitorPreviewBackground.apply(id,snapshot) : monitorPreviewBackground.failed(id);
}
//@@FN_END:syncMonitorPreviewBackground

//@@FN_START:captureDesktopFrame
async function captureDesktopFrame(desktopId, profile = "main") {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return null;

  if (!desktopId) return null;

  const hostHwnd = String(monitorDesktopIdentityState.snapshot().hostWindowHwnd || "").trim();

  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") return null;

  const hasHostHwnd = true;

  const generation = monitorDesktopFrameGeneration(desktopId);

  const cacheKey = `${generation}:${desktopId}:${profile}:${hasHostHwnd ? hostHwnd : "ambiguous-host"}`;

  const cached = monitorFrameCache.get(cacheKey);
  if(cached&&Date.now()-Number(cached.at||0)<=MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS)return cached;
  if(cached)monitorFrameCache.delete(cacheKey);

  if (monitorFrameInflight.has(cacheKey)) return monitorFrameInflight.get(cacheKey);

  const job = (async () => {

    if (profile === "thumb" && String(desktopId) === String(monitorDesktopIdentityState.snapshot().hostDesktopId || "")) {
      await ensureMonitorOwnFrozenSnapshot().catch(() => false);
    }

    const actMeta = monitorActDesktopVisualForDesktop(desktopId);

    // Window geometry/minimize state must come from the live Windows observer.

    // ACT metadata is still useful for identity, but stale ACT rects must never

    // override the actual desktop position shown in the preview/thumbs.

    const nativeMeta = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindows", desktopId, hostWindowHwnd: hostHwnd }

      : { type: "getDesktopWindows", desktopId }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    const meta = nativeMeta?.ok ? nativeMeta : actMeta;

    if (!meta?.ok) return null;

    const actByHwnd = new Map((Array.isArray(actMeta?.windows) ? actMeta.windows : []).map((item) => [String(item?.hwnd || ""), item]));

    const popupRuntime = await chrome.runtime.sendMessage({ type:"monitor-list-popup-runtime" }).catch(() => null);
    // Native intentionally excludes the Monitor host HWND while it captures a
    // desktop.  Keep that exclusion: including a live self-capture would make
    // Monitor recursively render itself.  The exact host is instead allowed
    // back in only through its bounded, frozen frame from the popup runtime.
    const monitorPopupWindows = (Array.isArray(popupRuntime?.windows) ? popupRuntime.windows : [])
      .filter((item) => String(item?.desktopId || "") === String(desktopId))
      .filter((item) => String(item?.hwnd || "") === hostHwnd && Boolean(item?.frozenDataUri));
    const windowRows = [...(Array.isArray(meta.windows) ? meta.windows : []), ...monitorPopupWindows];
    const windows = [...new Map(windowRows.map((item) => [String(item?.hwnd || ""), item])).values()]

      .map((item) => ({ ...item, conversationKey: String(item?.conversationKey || actByHwnd.get(String(item?.hwnd || ""))?.conversationKey || "") }));

    const handleSnapshot = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true }

      : { type: "getDesktopWindowHandles", desktopId, includeMonitorWindows: true }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    // Only a successful native snapshot can add/remove physical windows.
    const handlesConfirmed = handleSnapshot?.ok === true && Array.isArray(handleSnapshot.windows);
    const handleByHwnd = new Map((handlesConfirmed ? handleSnapshot.windows : []).map((item) => [String(item?.hwnd || ""), item]));
    const previousByHwnd = new Map(windows.map((item) => [String(item?.hwnd || ""), item]));
    // A confirmed native snapshot remains authoritative for real windows, but
    // it does not contain the deliberately excluded host Monitor HWND above.
    // Reinsert only that frozen self row after the snapshot so it cannot be
    // lost on every successful refresh.
    const currentWindowRows = handlesConfirmed
      ? [...handleByHwnd.values(), ...monitorPopupWindows]
      : windows;
    const currentWindows = [...new Map(currentWindowRows
      .filter((item) => /^[0-9]+$/.test(String(item?.hwnd || "")) && String(item.hwnd) !== "0" && (item.visible !== false || Boolean(item.iconic)))
      .map((item) => [String(item.hwnd), item])).values()];
    const liveWindows = currentWindows.map((item) => {
      const hwnd = String(item?.hwnd || "");
      const previous = previousByHwnd.get(hwnd);
      return { ...previous, ...item, conversationKey: String(item?.conversationKey || previous?.conversationKey || actByHwnd.get(hwnd)?.conversationKey || "") };
    });
    rememberMonitorDesktopWindows(desktopId, liveWindows);
    await refreshMonitorBctThumbnailProjectionForDesktop(desktopId);

    // Physical window existence/geometry/Z-order is native Windows truth. ACT only enriches identity.

    // Capture is optional visual content and must never decide whether a window exists in Monitor.

    const visibleWindows = liveWindows.filter((item) => !Boolean(item?.iconic));

    // Reconcile rendered windows against the current Native HWND snapshot. A minimized

    // window is still present in liveWindows, while a closed/destroyed window is absent.

    const liveHwndSet = new Set(liveWindows.map((item) => String(item?.hwnd || "")).filter(Boolean));

    const desktopTile = [...monitorDesktopThumbs.children].find((item) => String(item.dataset.desktopId || "") === String(desktopId));

    const desktopVisual = desktopTile?.querySelector(".monitor-desktop-thumb-visual");

    if (desktopVisual) {

      for (const stale of [...desktopVisual.querySelectorAll(".monitor-desktop-thumb-window")]) {

        const staleHwnd = String(stale.dataset.hwnd || "");

        if (!staleHwnd || liveHwndSet.has(staleHwnd)) continue;

        removeMonitorV2Window(staleHwnd);

        monitorThumbnailService.dispose(staleHwnd);

      }

    }

    const items = [...visibleWindows].sort((a,b)=>Number(b.z||0)-Number(a.z||0));

    // Coverage is complete; concurrency is bounded inside ThumbnailService.
    // Placeholder frames remain visible only while a capture is unavailable.
    const captureItems = MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED
      ? items.filter((item) => monitorWindowCanRefreshPixels(item) && !monitorWindowUsesFrozenCapture(item))
      : [];

    const frames = items.map((item) => ({
              capturedAt: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? Date.now() : 0,

      item,

      dataUri: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? String(item.frozenDataUri) : monitorWindowFallbackDataUri(item),

      captureState: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "captured" : "placeholder",

      physicalSource: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "monitor-frozen" : "windows-native",

      semanticSource: item?.conversationKey ? "act-enriched" : "none"

    }));

    const frameByHwnd = new Map(frames.map((entry) => [String(entry.item?.hwnd || ""), entry]));

    if (profile === "thumb") {

      // Desktop cards show real window pixels. Small captures plus a short HWND cache

      // keep ACT identity/state polling responsive; the label SVG is fallback only.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item?.hwnd || "");

        let dataUri = "";

        dataUri = await monitorGetWindowCapture(hwnd, "thumb");

        if (!dataUri) continue;

        const frameEntry = frameByHwnd.get(hwnd);

        if(frameEntry){
  const meta=monitorWindowCaptureService("thumb").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

      }

    } else {

      // Large selected preview keeps the real pixels. Native messaging is serialized,

      // so capture one window at a time to avoid starving identity/selection requests.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item.hwnd || "");

        const dataUri = await monitorGetWindowCapture(hwnd, "preview");
        if (dataUri) {

          const frameEntry = frameByHwnd.get(hwnd);

          if(frameEntry){
  const meta=monitorWindowCaptureService("preview").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

        }

      }

    }

    const observedWindowHwnds = [...new Set([

      ...visibleWindows.map((item) => String(item?.hwnd || "")),

      ...(handlesConfirmed ? handleSnapshot.windows : [])

        .filter((item) => Boolean(item?.visible) && !Boolean(item?.iconic))

        .map((item) => String(item?.hwnd || ""))

    ].filter(Boolean))];

    const frame = { at: Date.now(), meta: { ...meta, windows: visibleWindows, observedWindowHwnds }, frames };

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

    monitorFrameCache.set(cacheKey, frame);
    while (monitorFrameCache.size > MONITOR_FRAME_CACHE_LIMIT) {
      const oldestKey = monitorFrameCache.keys().next().value;
      if (!oldestKey) break;
      monitorFrameCache.delete(oldestKey);
    }

    return frame;

  })().finally(() => monitorFrameInflight.delete(cacheKey));

  monitorFrameInflight.set(cacheKey, job);

  return job;

}
//@@FN_END:captureDesktopFrame

//@@FN_START:clearMonitorThumbnailRecovery
function clearMonitorThumbnailRecovery(){

  monitorTrashedDesktops.clear(); persistMonitorTrashedDesktops();

  for(const [key,item] of [...monitorRecoveryRecordStore.trash]) if(String(item?.trash_source||"list")==="thumbnail"){monitorRecoveryRecordStore.trash.delete(key);monitorRecoveryRecordStore.trashedKeys.add(String(key));}

  persistMonitorTrashedNodes(); if(monitorObservedState.snapshot())renderWorkers(monitorObservedState.snapshot()); refreshMonitorRecoveryMenu();

}
//@@FN_END:clearMonitorThumbnailRecovery

//@@FN_START:ensureMonitorCurrentWallpaperSnapshot
async function ensureMonitorCurrentWallpaperSnapshot(desktopIdValue) {
  const desktopId = String(desktopIdValue || "").trim();
  const currentDesktopId = String(monitorDesktopIdentityState.snapshot().currentDesktopId || "").trim();
  if (!desktopId || desktopId !== currentDesktopId || !monitorIsActiveDesktopRenderer() || monitorCurrentWallpaperCaptureBusy) return false;

  monitorCurrentWallpaperCaptureBusy = true;
  try {
    const retryDelays = [0, 160, 420];
    for (const delay of retryDelays) {
      if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
      if (String(monitorDesktopIdentityState.snapshot().currentDesktopId || "").trim() !== desktopId || !monitorIsActiveDesktopRenderer()) return false;

      const capture = await monitorCoreNative({
        type:"captureCurrentDesktopWallpaper",
        maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,
        maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,
        quality:68
      }).catch(() => null);
      const capturedDesktopId = String(capture?.desktopId || "").trim();
      const rawDataUri = capture?.ok && capturedDesktopId.toLowerCase() === desktopId.toLowerCase() ? String(capture?.dataUri || "") : "";
      if (!rawDataUri.startsWith("data:image/")) continue;

      const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);
      if (!String(dataUri || "").startsWith("data:image/")) continue;

      monitorRememberWallpaperEntry(monitorWallpaperActuals, desktopId, dataUri, MONITOR_WALLPAPER_ACTUAL_LIMIT);
      monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);
      invalidateMonitorDesktopFrames(desktopId);

      await chrome.runtime.sendMessage({
        type:"monitor-update-popup-runtime",
        desktopId,
        hwnd:String(monitorDesktopIdentityState.snapshot().hostWindowHwnd || ""),
        wallpaperDataUri:dataUri
      }).catch(() => null);
      return true;
    }
    return false;
  } finally {
    monitorCurrentWallpaperCaptureBusy = false;
  }
}
//@@FN_END:ensureMonitorCurrentWallpaperSnapshot

//@@FN_START:getObservedWallpaper
async function getObservedWallpaper(desktopId, force = false) {

  if (!MONITOR_PIXEL_VISUALS_ENABLED || !desktopId) return "";

  const actual = monitorWallpaperActuals.get(desktopId);
  // Explicit refresh must consult Native, not reuse an indefinitely retained image.
  if (!force && actual?.dataUri) {
    monitorWallpaperActuals.delete(desktopId);
    monitorWallpaperActuals.set(desktopId, actual);
    return actual.dataUri;
  }
  const cached = monitorWallpaperCache.get(desktopId);

  if (!force && cached && Date.now() - cached.at <= MONITOR_WALLPAPER_CACHE_MS) { monitorWallpaperCache.delete(desktopId); monitorWallpaperCache.set(desktopId, cached); return cached.dataUri; }

  // Wallpaper fallback removed: only a genuine Native result is accepted.

  try {

    const response = await monitorCoreNative({
      type: "getDesktopVisualSnapshot",
      desktopId,
      maxWidth: MONITOR_WALLPAPER_MAX_WIDTH,
      maxHeight: MONITOR_WALLPAPER_MAX_HEIGHT,
      quality: 68
    });

    const rawDataUri = response?.wallpaper?.dataUri || "";
    const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);

    if (dataUri) monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);

    return dataUri;

  } catch (_) { return ""; }

}
//@@FN_END:getObservedWallpaper

//@@FN_START:monitorFreezeDesktopThumbnail
async function monitorFreezeDesktopThumbnail(desktopId,wallpaperDataUri=""){

  if(!desktopId)return "";

  try{

    const width=320,height=180;

    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;

    const ctx=canvas.getContext("2d",{alpha:false});if(!ctx)return "";

    ctx.fillStyle="#121821";ctx.fillRect(0,0,width,height);

    const wallpaper=String(wallpaperDataUri||await getObservedWallpaper(desktopId,false).catch(()=>""));

    const wallpaperImage=await monitorDeletedDesktopLoadImage(wallpaper);

    if(wallpaperImage)monitorDeletedDesktopDrawCover(ctx,wallpaperImage,width,height);

    const tile=[...monitorDesktopThumbs.children].find((button)=>String(button.dataset.desktopId||"")===String(desktopId));

    const visual=tile?.querySelector(".monitor-desktop-thumb-visual");

    if(visual&&visual.dataset.monitorFrameReady!=="1")await refreshDesktopThumb(visual,desktopId).catch(()=>false);

    let painted=0;

    if(visual){

      const images=[...visual.querySelectorAll(".monitor-desktop-thumb-window")].filter((node)=>String(node.src||"")).sort((a,b)=>Number(a.style.zIndex||a.dataset.nativeZIndex||0)-Number(b.style.zIndex||b.dataset.nativeZIndex||0));

      for(const node of images){

        const image=await monitorDeletedDesktopLoadImage(node.src);

        if(!image)continue;

        const left=(parseFloat(node.style.left)||0)*width/100,top=(parseFloat(node.style.top)||0)*height/100;

        const w=(parseFloat(node.style.width)||0)*width/100,h=(parseFloat(node.style.height)||0)*height/100;

        if(w<=0||h<=0)continue;

        ctx.drawImage(image,left,top,w,h);painted+=1;

      }

    }

    if(!painted){

      const frame=await captureDesktopFrame(desktopId,"thumb").catch(()=>null);

      if(frame?.meta){

        const vw=Math.max(1,Number(frame.meta.previewVirtualWidth??frame.meta.virtualWidth)||1),vh=Math.max(1,Number(frame.meta.previewVirtualHeight??frame.meta.virtualHeight)||1);

        const vl=Number(frame.meta.previewVirtualLeft??frame.meta.virtualLeft??0),vt=Number(frame.meta.previewVirtualTop??frame.meta.virtualTop??0);

        for(const entry of Array.isArray(frame.frames)?frame.frames:[]){

          const image=await monitorDeletedDesktopLoadImage(entry?.dataUri),item=entry?.item||{};

          if(!image)continue;

          const left=((Number(item.left)-vl)/vw)*width,top=((Number(item.top)-vt)/vh)*height,w=(Number(item.width)/vw)*width,h=(Number(item.height)/vh)*height;

          if(![left,top,w,h].every(Number.isFinite)||w<=0||h<=0)continue;

          ctx.drawImage(image,left,top,w,h);painted+=1;

        }

      }

    }

    try{return canvas.toDataURL("image/webp",0.66)||canvas.toDataURL("image/png");}

    catch(_){return canvas.toDataURL("image/png");}

  }catch(_){return "";}

}
//@@FN_END:monitorFreezeDesktopThumbnail

//@@FN_START:monitorLightweightWallpaperDataUri
async function monitorLightweightWallpaperDataUri(dataUri) {
  const source = String(dataUri || "");
  if (!source.startsWith("data:image/")) return source;
  try {
    const image = await new Promise((resolve, reject) => {
      const node = new Image();
      node.onload = () => resolve(node);
      node.onerror = reject;
      node.src = source;
    });
    const width = Math.max(1, Number(image.naturalWidth || image.width || 1));
    const height = Math.max(1, Number(image.naturalHeight || image.height || 1));
    const scale = Math.min(1, MONITOR_WALLPAPER_MAX_WIDTH / width, MONITOR_WALLPAPER_MAX_HEIGHT / height);
    if (scale >= 1) return source;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d", { alpha:false });
    if (!ctx) return source;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const compact = canvas.toDataURL("image/jpeg", 0.68);
    canvas.width = 1;
    canvas.height = 1;
    return compact || source;
  } catch (_) {
    return source;
  }
}
//@@FN_END:monitorLightweightWallpaperDataUri

//@@FN_START:monitorRememberWallpaperEntry
function monitorRememberWallpaperEntry(map, desktopId, dataUri, limit) {
  const key = String(desktopId || "");
  if (!key || !dataUri) return;
  map.delete(key);
  map.set(key, { dataUri, at: Date.now() });
  while (map.size > limit) {
    const oldestKey = map.keys().next().value;
    if (!oldestKey) break;
    map.delete(oldestKey);
  }
}
//@@FN_END:monitorRememberWallpaperEntry

//@@FN_START:monitorRevokeThumbWindowCaptureSource
function monitorRevokeThumbWindowCaptureSource(source) {
  const value = String(source || "");
  if (!value.startsWith("blob:")) return;
  URL.revokeObjectURL(value);
  monitorRenderDiagnostics.blobRevokes += 1;
}
//@@FN_END:monitorRevokeThumbWindowCaptureSource

//@@FN_START:monitorThumbnailLayoutWatch
async function monitorThumbnailLayoutWatch() {

  const desktopIds = monitorDesktopIdentityState.snapshot().desktopIds.filter(Boolean);

  const hostHwnd = String(monitorDesktopIdentityState.snapshot().hostWindowHwnd || "").trim();

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
//@@FN_END:monitorThumbnailLayoutWatch

//@@FN_START:monitorThumbnailProjectionRuntimeDiagnostics
function monitorThumbnailProjectionRuntimeDiagnostics() {
  if(!monitorDesktopThumbs)return [];
  return [...monitorDesktopThumbs.children].map((button)=>{
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    return {
      desktop_id:String(button.dataset.desktopId||visual?.dataset?.desktopId||""),
      status:String(visual?.dataset?.monitorNodeOverlayStatus||"NOT_RENDERED"),
      candidates:Number(visual?.dataset?.monitorNodeOverlayCandidates)||0,
      matched:Number(visual?.dataset?.monitorNodeOverlayMatched)||0,
      rendered:Number(visual?.dataset?.monitorNodeOverlayRendered)||0,
    };
  });
}
//@@FN_END:monitorThumbnailProjectionRuntimeDiagnostics

//@@FN_START:reconcileFrame
function reconcileFrame(container, frame, className) {

  if (!frame?.meta) return;

  const existing = new Map([...container.querySelectorAll(`.${className}`)].map(img => [img.dataset.hwnd, img]));
  const previousAgeLabels = new Map([...container.querySelectorAll(".monitor-window-capture-age-label")].map(label => [label.dataset.hwnd, label]));

  const observedSource = Array.isArray(frame.meta?.observedWindowHwnds) ? frame.meta.observedWindowHwnds : (Array.isArray(frame.meta?.windows) ? frame.meta.windows.map((item)=>item?.hwnd) : []);

  const observedHwnds = new Set(observedSource.map((item)=>String(item||"")).filter(Boolean));

  const vw = Math.max(1, Number(frame.meta.previewVirtualWidth ?? frame.meta.virtualWidth) || 1), vh = Math.max(1, Number(frame.meta.previewVirtualHeight ?? frame.meta.virtualHeight) || 1);

  const vl = Number(frame.meta.previewVirtualLeft ?? frame.meta.virtualLeft ?? 0), vt = Number(frame.meta.previewVirtualTop ?? frame.meta.virtualTop ?? 0);

  container.dataset.monitorPreviewVirtualLeft = String(vl);
  container.dataset.monitorPreviewVirtualTop = String(vt);
  container.dataset.monitorPreviewVirtualWidth = String(vw);
  container.dataset.monitorPreviewVirtualHeight = String(vh);

  for (const entry of frame.frames) {

    const key = String(entry.item.hwnd || "");

    let img = existing.get(key);

    if (!img) {

      img = document.createElement("img"); img.className = className; img.dataset.hwnd = key; img.alt = ""; container.append(img);

    }

    img.title = entry.item.title || "";

    img.dataset.physicalSource = entry.physicalSource || "windows-native";

    img.dataset.semanticSource = entry.semanticSource || (entry.item?.conversationKey ? "act-enriched" : "none");

    const captureTitle=String(entry.item?.title||"");
    const frozen=entry.physicalSource==="monitor-frozen";
    const freshEntry=frozen||monitorCaptureMatchesCurrentWindow(entry.captureTitle,captureTitle,entry.capturedAt);
    const nextCaptureState=freshEntry?(entry.captureState||"placeholder"):"placeholder";
    const previousFresh=monitorCaptureMatchesCurrentWindow(img.dataset.monitorCaptureTitle,captureTitle,img.dataset.monitorCapturedAt);
    const couldKeep=previousFresh&&(
      monitorShouldKeepExistingCapture(img.dataset.captureState,img.src,nextCaptureState)
      ||["held","stale"].includes(img.dataset.captureState)
    );
    const captureView = monitorChooseCaptureView({
      previousState: img.dataset.captureState,
      previousSource: couldKeep ? img.src : "",
      previousCapturedAt: Number(img.dataset.monitorCapturedAt || 0),
      nextState: nextCaptureState, nextSource: nextCaptureState==="captured"?entry.dataUri:"",
      nextCapturedAt: nextCaptureState==="captured"?Number(entry.capturedAt||Date.now()):0, now: Date.now()
    }, bwmUiLayoutControl?.read?.()?.captureFallback);
    img.dataset.captureState = captureView.state;
    img.dataset.monitorCapturedAt = String(captureView.capturedAt);
    if(captureView.state==="captured"&&nextCaptureState==="captured")img.dataset.monitorCaptureTitle=captureTitle;
    else if(!couldKeep)delete img.dataset.monitorCaptureTitle;
    img.dataset.captureFailureReason = nextCaptureState === "captured" ? "" :
      Number(entry.item?.cloaked || 0) !== 0 ? "CLOAKED" :
      !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED ? "CAPTURE_DISABLED" : "WGC_UNAVAILABLE";
    img.classList.toggle("monitor-window-capture-placeholder", captureView.state === "placeholder");
    img.classList.toggle("monitor-window-capture-stale", captureView.state === "stale");

    // Captured pixels are independent from ACT/node decoration. Identity delay may hide

    // a badge temporarily, but must never suppress the browser image itself.

    img.style.left = `${((Number(entry.item.left) - vl) / vw) * 100}%`;

    img.style.top = `${((Number(entry.item.top) - vt) / vh) * 100}%`;

    img.style.width = `${(Number(entry.item.width) / vw) * 100}%`; img.style.height = `${(Number(entry.item.height) / vh) * 100}%`;

    const nativeZ = Math.max(0, Number(entry.item.z) || 0);

    const nativeZIndex = String(10000 - Math.min(nativeZ, 9999));

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");

    const renderedSource = captureView.state === "placeholder" && !captureView.source ? monitorWindowFallbackDataUri(entry.item) : captureView.source;
    if (img.src !== renderedSource) img.src = renderedSource;
    img.title = captureView.label ? String(entry.item.title || "") + " - " + captureView.label : String(entry.item.title || "");
    let ageLabel = previousAgeLabels.get(key);
    if (captureView.label) {
      if (!ageLabel) {
        ageLabel = document.createElement("span");
        ageLabel.className = "monitor-window-capture-age-label";
        ageLabel.dataset.hwnd = key;
        container.append(ageLabel);
      }
      ageLabel.textContent = captureView.label;
      ageLabel.style.left = "calc(" + img.style.left + " + 3px)";
      ageLabel.style.top = "calc(" + img.style.top + " + " + img.style.height + " - 20px)";
      ageLabel.style.zIndex = String(Number(nativeZIndex) + 1);
    } else {
      ageLabel?.remove();
    }
    previousAgeLabels.delete(key);

    try {

      applyPersistentMonitorRoleClass(img, key);

      img.classList.toggle("monitor-window-row-hovered", Boolean(monitorHoveredHwnd) && key === monitorHoveredHwnd && !monitorSelectedHwnds.has(key));

      syncMonitorStatusLayer(img, key); syncMonitorPauseOverlay(img, key);

      syncMonitorDesktopNumberBadge(img, key); syncMonitorNonChatCountdown(img, key);

    } catch (error) { console.warn("DesktopWindow Monitor frame decoration delayed", key, error); }

    if (!img.dataset.monitorDragBound) {

      img.dataset.monitorDragBound = "1";

      img.draggable = false;

      img.addEventListener("pointerdown", beginMonitorWindowPointerDrag);

    }

    existing.delete(key);

  }

  for (const stale of existing.values()) {

    const key=String(stale.dataset.hwnd||"");

    // A transient WGC snapshot failure is not a window disappearance. Keep the last good

    // pixels and decorations while Native still reports the HWND on this desktop.

    if(observedHwnds.has(key)){applyPersistentMonitorRoleClass(stale,key);syncMonitorPauseOverlay(stale,key);syncMonitorDesktopNumberBadge(stale,key);syncMonitorNonChatCountdown(stale,key);continue;}

    stale.parentElement?.querySelectorAll(".monitor-window-status-layer, .monitor-window-pause-overlay, .monitor-window-desktop-badge, .monitor-window-non-chat-countdown").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();});

    stale.remove();

  }

  for (const unownedAgeLabel of previousAgeLabels.values()) { if (!observedHwnds.has(String(unownedAgeLabel.dataset.hwnd || ""))) unownedAgeLabel.remove(); }
if (monitorSelectedHwnds.size) applyMonitorWindowHighlight(monitorHighlightedHwnd, { preserve: true });

  scheduleMonitorHoverRecheck();

}
//@@FN_END:reconcileFrame

//@@FN_START:refreshBackgroundThumbs
async function refreshBackgroundThumbs(...desktopIds) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return [];
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refreshBackground) return desktopIds.filter(Boolean);
  const selectedDesktopId = String(monitorDesktopIdentityState.snapshot().desktopIds[monitorDesktopIdentityState.snapshot().selectedIndex] || "");
  const ids = new Set(desktopIds.map((id) => String(id || "")).filter(Boolean));
  if (selectedDesktopId) ids.delete(selectedDesktopId);
  const failed = [];
  for (const desktopId of ids) {
    const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
    if (!visual?.isConnected) continue;
    const result = await renderer.refreshBackground(visual, desktopId).catch(() => null);
    if (result?.wallpaperReady !== true) failed.push(desktopId);
  }
  return failed;
}
//@@FN_END:refreshBackgroundThumbs

//@@FN_START:refreshDesktopDropThumbnails
async function refreshDesktopDropThumbnails(sourceDesktopId, targetDesktopId) {

  invalidateMonitorDesktopFrames(sourceDesktopId, targetDesktopId);

  await new Promise((resolve) => setTimeout(resolve, 140));

  for (const desktopId of [sourceDesktopId, targetDesktopId]) {

    const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === desktopId);

    const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

    if (visual) await refreshDesktopThumb(visual, desktopId);

  }

  await refreshObservedWindows();

}
//@@FN_END:refreshDesktopDropThumbnails

//@@FN_START:decorateMonitorThumbnailWindows
function decorateMonitorThumbnailWindows(tile) {
  for (const image of tile.querySelectorAll(".monitor-desktop-thumb-window")) {
    const hwnd = String(image.dataset.hwnd || "");
    try {
      applyPersistentMonitorRoleClass(image,hwnd);
      image.classList.toggle("monitor-window-row-hovered",
        Boolean(monitorHoveredHwnd) && hwnd===monitorHoveredHwnd && !monitorSelectedHwnds.has(hwnd));
      syncMonitorStatusLayer(image,hwnd);
      syncMonitorPauseOverlay(image,hwnd);
      syncMonitorDesktopNumberBadge(image,hwnd);
      syncMonitorNonChatCountdown(image,hwnd);
    } catch (error) { console.warn("Monitor thumbnail V2 badge delayed",hwnd,error); }
  }
  syncMonitorThumbnailTabBadges(tile,"monitor-desktop-thumb-window");
}
//@@FN_END:decorateMonitorThumbnailWindows

//@@FN_START:refreshDesktopThumb
async function refreshDesktopThumb(visual, desktopId) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED || !visual?.isConnected) return false;
  if (String(visual.dataset.desktopId || "").toLowerCase() !== String(desktopId || "").toLowerCase()) return false;
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer) return false;
  const result = await renderer.refresh(visual,desktopId);
  return result?.ok === true;
}
//@@FN_END:refreshDesktopThumb

//@@FN_START:monitorThumbnailBackgroundRuntimeDiagnostics
function monitorThumbnailBackgroundRuntimeDiagnostics() {
  const visuals = [...(monitorDesktopThumbs?.querySelectorAll?.(".monitor-desktop-thumb-visual") || [])];
  return visuals.map((visual) => ({
    desktop_id:String(visual.dataset.desktopId || ""),
    layer_mode:String(visual.dataset.monitorThumbnailLayerMode || globalThis.MonitorDesktopThumbnailV2?.mode || "unknown"),
    card_renderer:String(monitorDesktopThumbs?.dataset?.thumbnailCardRenderer || "unknown"),
    card_renderer_reason:String(monitorDesktopThumbs?.dataset?.thumbnailCardRendererReason || ""),
    card_renderer_error:String(monitorDesktopThumbs?.dataset?.thumbnailCardRendererError || "").slice(0,120),
    capture:String(visual.dataset.wallpaperCapture || "unobserved"),
    source:String(visual.dataset.wallpaperSource || "none"),
    accepted_kind:String(visual.dataset.wallpaperAcceptedKind || ""),
    accepted_at_ms:Number(visual.dataset.wallpaperAcceptedAt || 0),
    failure_reason:String(visual.dataset.wallpaperFailureReason || "").slice(0,120),
    thumbnail_ready:String(visual.dataset.monitorThumbnailReady || ""),
    composite_ready:String(visual.dataset.monitorThumbnailCompositeReady || ""),
    frame_ready:String(visual.dataset.monitorFrameReady || ""),
    actual_windows:Number(visual.dataset.monitorThumbnailWindows || 0),
    captured_windows:visual.querySelectorAll(".monitor-desktop-thumb-window[data-capture-state='captured']").length,
    failed_windows:visual.querySelectorAll(".monitor-desktop-thumb-window[data-capture-state='failed']").length,
    has_background_image:Boolean(visual.style.backgroundImage),
    has_background_color:Boolean(visual.style.backgroundColor)
  }));
}
//@@FN_END:monitorThumbnailBackgroundRuntimeDiagnostics

//@@FN_START:refreshInitialBackgroundThumbs
async function refreshInitialBackgroundThumbs() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) {
    monitorInitialThumbStage = "disabled";
    return false;
  }
  const selectedId = monitorDesktopIdentityState.snapshot().desktopIds[monitorDesktopIdentityState.snapshot().selectedIndex] || "";
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refreshBackground) {
    monitorInitialThumbStage = "renderer-unavailable";
    monitorInitialThumbError = "THUMBNAIL_BACKGROUND_RENDERER_UNAVAILABLE";
    return false;
  }
  let pending = [
    selectedId,
    ...monitorDesktopIdentityState.snapshot().desktopIds.filter((id) => id && id !== selectedId)
  ].filter(Boolean);
  if (!pending.length) {
    monitorInitialThumbStage = "no-desktops";
    monitorInitialThumbError = "NO_DESKTOP_IDS";
    return false;
  }

  monitorInitialThumbStage = "background-requesting";
  monitorInitialThumbError = "";
  const retryDelays = [160, 420];
  for (let attempt = 0; pending.length; attempt += 1) {
    const failed = [];
    for (const desktopId of pending) {
      const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (!visual?.isConnected) { failed.push(desktopId); continue; }
      const result = await renderer.refreshBackground(visual, desktopId).catch(() => null);
      if (result?.wallpaperReady !== true) failed.push(desktopId);
    }
    pending = failed;
    if (!pending.length || attempt >= retryDelays.length) break;
    await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
  }
  monitorInitialThumbStage = pending.length ? "background-failed" : "background-ready";
  monitorInitialThumbError = pending.length ? `UNREADY_DESKTOPS:${pending.join(",")}` : "";
  return pending.length === 0;
}
//@@FN_END:refreshInitialBackgroundThumbs

//@@FN_START:refreshInitialWindowThumbs
async function refreshInitialWindowThumbs() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  const renderer = globalThis.MonitorDesktopThumbnailV2;
  if (!renderer?.refresh) {
    monitorInitialThumbStage = "window-renderer-unavailable";
    monitorInitialThumbError = "THUMBNAIL_WINDOW_RENDERER_UNAVAILABLE";
    return false;
  }
  const selectedId = monitorDesktopIdentityState.snapshot().desktopIds[monitorDesktopIdentityState.snapshot().selectedIndex] || "";
  const desktopIds = [
    selectedId,
    ...monitorDesktopIdentityState.snapshot().desktopIds.filter((id) => id && id !== selectedId)
  ].filter(Boolean);
  if (!desktopIds.length) return false;

  monitorInitialThumbStage = "windows-requesting";
  monitorInitialThumbError = "";
  let pending = desktopIds;
  const retryDelays = [180, 500];
  for (let attempt = 0; pending.length; attempt += 1) {
    const failed = [];
    for (const desktopId of pending) {
      const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);
      const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
      if (!visual?.isConnected) { failed.push(desktopId); continue; }
      const result = await renderer.refresh(visual, desktopId).catch(() => null);
      if (result?.frameReady !== true) failed.push(desktopId);
    }
    pending = failed;
    if (!pending.length || attempt >= retryDelays.length) break;
    await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
  }
  monitorInitialThumbStage = pending.length ? "windows-partial" : "windows-ready";
  monitorInitialThumbError = pending.length ? `UNREADY_WINDOW_DESKTOPS:${pending.join(",")}` : "";
  return pending.length === 0;
}
//@@FN_END:refreshInitialWindowThumbs

//@@FN_START:refreshInitialSelectedThumb
async function refreshInitialSelectedThumb({ allowWindows = true } = {}) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;
  if (!monitorInitialThumbBatchDone) {
    monitorInitialThumbStage = "background-starting";
    monitorInitialThumbError = "";
    const refreshTask = refreshInitialBackgroundThumbs();
    const pendingReportTimer = setTimeout(() => {
      void monitorPublishSharedInstance("thumbnail-background-pending");
    }, 2500);
    const backgroundReady = await refreshTask.catch((error) => {
      monitorInitialThumbStage = "background-exception";
      monitorInitialThumbError = String(error?.message || error || "BACKGROUND_EXCEPTION").slice(0,160);
      return false;
    });
    clearTimeout(pendingReportTimer);
    monitorInitialThumbBatchDone = backgroundReady === true;
  }
  if (!monitorInitialThumbBatchDone) {
    await monitorPublishSharedInstance("thumbnail-background-failed").catch(() => null);
    return false;
  }
  if (!allowWindows) {
    monitorInitialThumbStage = "windows-awaiting-host";
    monitorInitialThumbError = "";
    await monitorPublishSharedInstance("thumbnail-windows-awaiting-host").catch(() => null);
    return true;
  }
  const hostHwnd = String(monitorDesktopIdentityState.snapshot().hostWindowHwnd || "").trim();
  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") {
    monitorInitialThumbStage = "windows-awaiting-host";
    monitorInitialThumbError = "MONITOR_HOST_HWND_UNRESOLVED";
    await monitorPublishSharedInstance("thumbnail-windows-awaiting-host").catch(() => null);
    return true;
  }
  const windowsReady = monitorInitialWindowBatchDone || await refreshInitialWindowThumbs().catch((error) => {
    monitorInitialThumbStage = "windows-exception";
    monitorInitialThumbError = String(error?.message || error || "WINDOW_EXCEPTION").slice(0,160);
    return false;
  });
  monitorInitialWindowBatchDone = windowsReady === true;
  await monitorPublishSharedInstance(
    windowsReady ? "thumbnail-composite-ready" : "thumbnail-windows-partial"
  ).catch(() => null);
  scheduleInitialSemanticThumbSync();
  void checkMonitorDeploymentUpdate();
  return true;
}
//@@FN_END:refreshInitialSelectedThumb

//@@FN_START:refreshMonitorBctThumbnailProjectionForDesktop
async function refreshMonitorBctThumbnailProjectionForDesktop(desktopId) {
  if (!Array.isArray(monitorNodePanelListState.snapshot()) || !monitorNodePanelListState.snapshot().length) return false;

  // Native thumbnail capture and the RCC/Chrome snapshot arrive independently.
  // Resolve once while this desktop's HWND geometry is fresh so the semantic
  // N-label is attached to the real browser rectangle rather than to a node card.
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  if (!monitorBctProjectionHasUnresolvedLineage()) return true;

  const chromeLocations = [...monitorWindowDesktopLocations.values()].filter((location) =>
    String(location?.desktopId || "") === String(desktopId || "") &&
    String(location?.className || "") === "Chrome_WidgetWin_1" &&
    Number(location?.width) > 0 && Number(location?.height) > 0
  );
  if (!chromeLocations.length) return false;

  const locationKey = chromeLocations.map((location) =>
    `${location.hwnd}:${location.left}:${location.top}:${location.width}:${location.height}:${location.iconic ? 1 : 0}`
  ).sort().join(",");
  const attemptKey = `${monitorBctProjectionGeneration}:${desktopId}:${locationKey}`;
  if (monitorBctThumbnailProjectionAttemptKeys.has(attemptKey)) return false;
  monitorBctThumbnailProjectionAttemptKeys.add(attemptKey);
  if (monitorBctThumbnailProjectionAttemptKeys.size > 24) {
    monitorBctThumbnailProjectionAttemptKeys = new Set([attemptKey]);
  }

  await refreshMonitorBctBrowserWindowGeometry();
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  return !monitorBctProjectionHasUnresolvedLineage();
}
//@@FN_END:refreshMonitorBctThumbnailProjectionForDesktop

//@@FN_START:refreshSelectedThumb
async function refreshSelectedThumb() {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return false;

  const desktopId = monitorDesktopIdentityState.snapshot().desktopIds[monitorDesktopIdentityState.snapshot().selectedIndex] || "";

  if (!desktopId) return false;

  const tile = [...monitorDesktopThumbs.children].find((button) => button.dataset.desktopId === desktopId);

  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");

  if (!visual) return false;
  return await refreshDesktopThumb(visual, desktopId);

}
//@@FN_END:refreshSelectedThumb

//@@FN_START:scheduleInitialSemanticThumbSync
function scheduleInitialSemanticThumbSync(delay = 180) {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return;
  if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight) return;
  if (monitorInitialSemanticThumbSyncTimer) clearTimeout(monitorInitialSemanticThumbSyncTimer);
  monitorInitialSemanticThumbSyncTimer = setTimeout(async () => {
    monitorInitialSemanticThumbSyncTimer = 0;
    if (monitorInitialSemanticThumbSyncDone || monitorInitialSemanticThumbSyncInflight || !monitorInitialThumbBatchDone) return;
    const state = monitorObservedState.snapshot();
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
//@@FN_END:scheduleInitialSemanticThumbSync

//@@FN_START:scheduleMonitorThumbnailProjectionReceipt
function scheduleMonitorThumbnailProjectionReceipt() {
  const diagnostics=monitorThumbnailProjectionRuntimeDiagnostics();
  const signature=JSON.stringify(diagnostics);
  if(signature===monitorThumbnailProjectionPublishSignature)return;
  monitorThumbnailProjectionPublishSignature=signature;
  if(monitorThumbnailProjectionPublishTimer)clearTimeout(monitorThumbnailProjectionPublishTimer);
  monitorThumbnailProjectionPublishTimer=setTimeout(()=>{
    monitorThumbnailProjectionPublishTimer=0;
    void monitorPublishSharedInstance("thumbnail-projection");
  },500);
}
//@@FN_END:scheduleMonitorThumbnailProjectionReceipt

//@@FN_START:settleNewDesktopWallpaper
async function settleNewDesktopWallpaper(createdId) {

  if (!createdId) return false;

  const renderer=globalThis.MonitorDesktopThumbnailV2;
  const tile = [...monitorDesktopThumbs.children].find((item) => item.dataset.desktopId === createdId);
  const visual = tile?.querySelector(".monitor-desktop-thumb-visual");
  const started = Date.now(); let ready = false;

  while (Date.now() - started < 5000) {

    if (visual) {
      const result=await renderer?.refreshBackground?.(visual,createdId,{forceWallpaper:true}).catch(()=>null);
      if(result?.wallpaperReady===true){ready=true;break;}
    }

    await new Promise((resolve) => setTimeout(resolve, 160));

  }

  if (!ready) return false;

  monitorWallpaperCache.delete(createdId);

  if (visual) {
    syncMonitorPreviewBackground(visual,createdId);
  }
  return Boolean(renderer?.acceptedBackground?.(visual,createdId));
}
//@@FN_END:settleNewDesktopWallpaper

//@@FN_START:syncMonitorAllDesktopThumbnailNodeBadges
function syncMonitorAllDesktopThumbnailNodeBadges() {
  for (const button of monitorDesktopThumbs.children) {
    const visual=button.querySelector(".monitor-desktop-thumb-visual");
    if (visual?.isConnected) syncMonitorThumbnailTabBadges(visual,"monitor-desktop-thumb-window");
  }
  syncMonitorBctNodeLocationLabels();
  syncMonitorMinimizedNodeBadges(monitorObservedState.snapshot());
  syncMonitorBctNodeTargetHighlight();
  scheduleMonitorThumbnailProjectionReceipt();
}
//@@FN_END:syncMonitorAllDesktopThumbnailNodeBadges

//@@FN_START:syncMonitorThumbnailTabBadges
function syncMonitorThumbnailTabBadges(container, className) {

  if (className !== "monitor-desktop-thumb-window") return;
  if (globalThis.MonitorDesktopThumbnailV2?.allowsLayer?.("nodes") === false) {
    container.querySelectorAll(
      ".monitor-thumbnail-node-overlay, .monitor-thumbnail-tab-badge, .monitor-window-desktop-badge-thumb, .monitor-window-desktop-badge"
    ).forEach((node) => node.remove());
    container.dataset.monitorNodeOverlayStatus = "DISABLED_BY_LAYER_POLICY";
    container.dataset.monitorNodeOverlayCandidates = "0";
    container.dataset.monitorNodeOverlayMatched = "0";
    container.dataset.monitorNodeOverlayRendered = "0";
    return {status:"DISABLED_BY_LAYER_POLICY",candidates:0,matched:0,rendered:0};
  }
  const projection = globalThis.MonitorBctThumbnailProjection;
  if (!projection?.render) {
    container.dataset.monitorNodeOverlayStatus = "MODULE_MISSING";
    container.dataset.monitorNodeOverlayRendered = "0";
    return;
  }
  const selectedNode = (Array.isArray(monitorNodePanelListState.snapshot()) ? monitorNodePanelListState.snapshot() : []).find((node) =>
    monitorNodePanelSelection.get() && monitorBctNodeSelectionKey(node) === monitorNodePanelSelection.get()
  );
  const selectedHwnd = selectedNode
    ? monitorDisplayHwndForBrowserWindowId(selectedNode.windowId, monitorObservedState.snapshot(), selectedNode.instanceId, selectedNode.sessionId)
    : "";
  const diagnostics = projection.render({
    container,
    state: monitorObservedState.snapshot(),
    locations: monitorWindowDesktopLocations,
    highlightedHwnd: monitorBctNodeHighlightedHwnd,
    selectedNodeHwnd: selectedHwnd,
    selectedNodeToken: String(selectedNode?.nodeLabel || "").replace(/^N/, "") || "?",
    selectedNodeTabId: Number(selectedNode?.tabId),
    numbersForHwnd: (hwnd, state) => monitorBadgeNodeNumbersForHwnd(hwnd, state, { includeTabIds: true }),
  });
  container.dataset.monitorNodeOverlayStatus = String(diagnostics.status || "UNKNOWN");
  container.dataset.monitorNodeOverlayCandidates = String(Number(diagnostics.candidates) || 0);
  container.dataset.monitorNodeOverlayMatched = String(Number(diagnostics.matched) || 0);
  container.dataset.monitorNodeOverlayRendered = String(Number(diagnostics.rendered) || 0);
  scheduleMonitorThumbnailProjectionReceipt();
  return diagnostics;
}
//@@FN_END:syncMonitorThumbnailTabBadges
