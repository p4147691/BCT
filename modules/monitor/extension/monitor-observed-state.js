// App-level observed ACT/BCT state. Snapshot projection only;
// authoritative updates still arrive from existing ACT/RCC readers.
(() => {
  "use strict";
  function create() {
    let value=null,revision=0;
    return Object.freeze({
      snapshot:()=>value,
      replace(next) { value=next;revision++;return value; },
      revision:()=>revision
    });
  }
  globalThis.MonitorObservedState=Object.freeze({create});
})();
