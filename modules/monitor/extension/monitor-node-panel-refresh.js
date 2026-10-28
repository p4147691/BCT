// NodePanel refresh lifecycle owner: one inflight read, one coalesced follow-up.
// RCC/BCT reading and the existing DOM renderer are injected application ports.
(() => {
  "use strict";
  function create({run, onBusy, onError, enqueue} = {}) {
    if (![run,onBusy,onError,enqueue].every(fn=>typeof fn==="function"))
      throw new TypeError("NODE_PANEL_REFRESH_PORTS_REQUIRED");
    let busy=false, pending=false, disposed=false;
    async function refresh() {
      if(disposed) return false;
      if(busy) { pending=true; return false; }
      busy=true; pending=false;
      onBusy(true);
      try { await run(); return true; }
      catch(error) { onError(error); return false; }
      finally {
        busy=false;
        onBusy(false);
        if(!disposed && pending) {
          pending=false;
          enqueue(()=>void refresh());
        }
      }
    }
    function snapshot() {
      return Object.freeze({busy,pending,disposed});
    }
    function destroy() { disposed=true; pending=false; }
    return Object.freeze({refresh,snapshot,destroy});
  }
  globalThis.MonitorNodePanelRefresh=Object.freeze({create});
})();
