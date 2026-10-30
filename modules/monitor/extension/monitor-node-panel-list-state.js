// Authoritative *Monitor UI projection* of the exact RCC/BCT node list.
// Upstream BCT/RCC retains the true node/session/UUID identity authority.
// Preserve reference identity for optimistic render rollback fences.
(() => {
  "use strict";
  function create() {
    let nodes=null, revision=0;
    const snapshot=()=>nodes;
    function replace(next) {
      if(next!==null && !Array.isArray(next))
        throw new TypeError("NODE_PANEL_LIST_INVALID");
      nodes=next;
      revision++;
      return nodes;
    }
    function rollbackIfCurrent(expected,previous) {
      if(nodes!==expected)return false;
      replace(previous);
      return true;
    }
    return Object.freeze({snapshot,replace,rollbackIfCurrent,revision:()=>revision});
  }
  globalThis.MonitorNodePanelListState=Object.freeze({create});
})();
