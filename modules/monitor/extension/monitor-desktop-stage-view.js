// DesktopStage owns the visible current/host/observed desktop DOM projection.
// The exact Native GUID topology and selection authority remain injected upstream.
(() => {
  "use strict";
  function create({body} = {}) {
    if(!body?.dataset||!body?.classList)throw new TypeError("DESKTOP_STAGE_DOM_REQUIRED");
    function showTopology(state) {
      const currentId=String(state?.currentDesktopId||"");
      const hostId=String(state?.hostDesktopId||"");
      const observedId=String(state?.observedDesktopId||"");
      const selected=Number(state?.selectedIndex)||0;
      const current=Number(state?.currentIndex)||0;
      body.dataset.monitorActiveDesktopId=currentId;
      body.dataset.monitorHostDesktopId=hostId;
      return showPreview({desktopId:observedId,index:selected,currentIndex:current});
    }
    function showPreview({desktopId,index,currentIndex} = {}) {
      const selected=Math.max(0,Number(index)||0),current=Math.max(0,Number(currentIndex)||0);
      body.dataset.monitorObservedDesktopId=String(desktopId||"");
      body.dataset.monitorPreviewDesktop=String(selected+1);
      body.classList.toggle("monitor-preview-remote",selected!==current);
      return Object.freeze({desktopId:body.dataset.monitorObservedDesktopId,
        previewIndex:selected,currentIndex:current});
    }
    return Object.freeze({showTopology,showPreview});
  }
  globalThis.MonitorDesktopStageView=Object.freeze({create});
})();
