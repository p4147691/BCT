"use strict";
(function installMonitorHostWindowIdentity(root) {
  const hwndPattern = /^[1-9][0-9]*$/;
  const guidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const norm = value => String(value || "").trim().toLowerCase();
  function resolved(state) {
    return state?.ok === true && state.hostWindowAmbiguous !== true
      && hwndPattern.test(String(state.hostWindowHwnd || ""));
  }
  function verified(candidate, isOwnTitle) {
    if (!resolved(candidate) || typeof isOwnTitle !== "function"
        || !isOwnTitle(String(candidate.hostWindowTitle || ""))) return false;
    const id = String(candidate.hostDesktopId || "");
    return guidPattern.test(id) && Array.isArray(candidate.desktopIds)
      && candidate.desktopIds.some(x => norm(x) === norm(id));
  }
  async function resolve(initial, {title, bounds, requestNative, isOwnTitle} = {}) {
    if (!initial?.ok || resolved(initial) || typeof requestNative !== "function") return initial;
    let byTitle;
    try { byTitle = await requestNative({type:"getVirtualDesktops",hostTitle:String(title||"")}); }
    catch (_) { byTitle = null; }
    if (verified(byTitle,isOwnTitle)) return byTitle;
    if (!bounds || ![bounds.left,bounds.top,bounds.width,bounds.height].every(Number.isFinite)
        || !(bounds.width > 100 && bounds.height > 80)) return initial;
    let byGeometry;
    try {
      byGeometry = await requestNative({type:"getVirtualDesktops",hostTitle:"",
        left:bounds.left,top:bounds.top,width:bounds.width,height:bounds.height});
    } catch (_) { byGeometry = null; }
    return verified(byGeometry,isOwnTitle) ? byGeometry : initial;
  }
  root.MonitorHostWindowIdentity = Object.freeze({resolve, verified});
})(globalThis);
