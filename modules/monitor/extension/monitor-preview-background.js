"use strict";
// Owns the full Monitor window backdrop. It consumes only an already validated
// desktop background snapshot; Native I/O and thumbnail DOM stay outside.
(function installMonitorPreviewBackground(root) {
  function create({element,contract}={}) {
    if (!element || !contract?.normalizeDesktopId) throw new TypeError("Preview background requires element and contract");
    let activeDesktopId="";
    let acceptedSnapshot=null;

    function begin(desktopId) {
      const id=contract.normalizeDesktopId(desktopId);
      if (!contract.isDesktopId(id)) return false;
      if (activeDesktopId !== id) {
        activeDesktopId=id;
        acceptedSnapshot=null;
        element.style.backgroundImage="";
        element.style.backgroundColor="";
        element.dataset.captureState="pending";
      }
      element.dataset.desktopId=id;
      return true;
    }

    function apply(desktopId,snapshot) {
      const id=contract.normalizeDesktopId(desktopId);
      if (!begin(id) || !snapshot?.ok || contract.normalizeDesktopId(snapshot.desktopId)!==id) return false;
      if (snapshot.kind==="solid" && /^#[0-9a-f]{6}$/i.test(String(snapshot.color||""))) {
        element.style.backgroundImage="";
        element.style.backgroundColor=String(snapshot.color).toUpperCase();
      } else if (snapshot.kind==="photo" && contract.isImage(snapshot.dataUri)) {
        element.style.backgroundColor=String(snapshot.baseColor).toUpperCase();
        element.style.backgroundImage="url("+JSON.stringify(String(snapshot.dataUri))+")";
      } else return false;
      acceptedSnapshot=snapshot;
      element.dataset.captureState="captured";
      element.dataset.wallpaperKind=String(snapshot.kind);
      element.dataset.wallpaperProof=String(snapshot.proof||"");
      return true;
    }

    function failed(desktopId) {
      if (!begin(desktopId)) return false;
      if (!acceptedSnapshot) element.dataset.captureState="failed";
      return Boolean(acceptedSnapshot);
    }

    function clear(desktopId="") {
      activeDesktopId=contract.normalizeDesktopId(desktopId);
      acceptedSnapshot=null;
      element.style.backgroundImage="";
      element.style.backgroundColor="";
      element.dataset.desktopId=activeDesktopId;
      element.dataset.captureState="cleared";
      element.dataset.wallpaperKind="";
      element.dataset.wallpaperProof="";
    }

    return Object.freeze({begin,apply,failed,clear,get desktopId(){return activeDesktopId;},get snapshot(){return acceptedSnapshot;}});
  }
  root.MonitorPreviewBackground=Object.freeze({create});
})(globalThis);
