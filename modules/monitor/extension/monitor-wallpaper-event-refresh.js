"use strict";
// Event-only wallpaper refresh. No timer, polling, old-image fallback, or HWND capture.
(function installWallpaperEventRefresh(root) {
  const generations = new Map();
  function normalizeIds(ids) {
    return [...new Set((Array.isArray(ids) ? ids : []).map(x=>String(x||"").trim()).filter(Boolean))];
  }
  async function notify({desktopIds, invalidate, read, display, onObserved} = {}) {
    if (typeof invalidate!=="function" || typeof read!=="function" || typeof display!=="function")
      throw new TypeError("WALLPAPER_EVENT_ADAPTER_INVALID");
    const ids = normalizeIds(desktopIds);
    const results = await Promise.all(ids.map(async desktopId => {
      const generation = (generations.get(desktopId) || 0) + 1;
      generations.set(desktopId, generation);
      invalidate(desktopId);
      let source = "", reason = "";
      try { source = String(await read(desktopId) || ""); }
      catch (e) { reason = String(e?.message || "NATIVE_CAPTURE_FAILED"); }
      if (generations.get(desktopId) !== generation)
        return {desktopId, applied:false, reason:"STALE_CAPTURE_RESPONSE"};
      const valid = /^data:image\/(?:png|jpeg|webp);base64,/.test(source);
      const outcome = {desktopId, applied:true, status:valid?"captured":"failed", reason:valid?"":reason||"NO_REAL_WALLPAPER_PIXELS"};
      display(desktopId, valid?source:"", outcome);
      onObserved?.(outcome);
      return outcome;
    }));
    return results;
  }
  root.MonitorWallpaperEventRefresh = Object.freeze({ notify });
})(globalThis);
