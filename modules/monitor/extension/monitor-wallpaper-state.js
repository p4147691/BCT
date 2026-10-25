"use strict";
// Deterministic wallpaper-only state machine. No fallback pixels and no polling.
// Native owns the physical wallpaper. The monitor owns only presentation state.
(function installWallpaperState(root) {
  const state = new Map();
  function text(v) { return String(v ?? "").trim(); }
  function onChange(desktopId) {
    const key = text(desktopId);
    if (!key) return null;
    const prev = state.get(key) || { generation: 0 };
    const next = Object.freeze({generation: prev.generation + 1, status:"pending", source:"", observedAt:0, reason:"wallpaper-changed"});
    state.set(key,next); return next;
  }
  function resolve(desktopId, generation, result, at = Date.now()) {
    const key = text(desktopId), current = state.get(key);
    if (!key || !current || current.generation !== generation) return Object.freeze({applied:false,reason:"stale-result"});
    const source = text(result?.dataUri);
    const valid = result?.ok === true && /^data:image\/(?:jpeg|png|webp);base64,/.test(source);
    const next=Object.freeze({generation,status:valid?"captured":"failed",
      source:valid?source:"",observedAt:valid?at:0,
      reason:valid?"":text(result?.error)||"NO_REAL_WALLPAPER_PIXELS"});
    state.set(key,next); return Object.freeze({applied:true,...next});
  }
  function begin(desktopId) { return onChange(desktopId); }
  function current(desktopId) { return state.get(text(desktopId)) || null; }
  function discard(desktopId) { state.delete(text(desktopId)); }
  root.MonitorWallpaperState=Object.freeze({begin,onChange,resolve,current,discard});
})(globalThis);
