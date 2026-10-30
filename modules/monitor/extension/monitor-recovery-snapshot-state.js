// Sole owner of Monitor's persistent reboot-recovery projection.
// It never restores, launches, persists, or operates on Chrome/Native itself.
(() => {
  "use strict";
  function create(initial={captured_at_ms:0,items:[]}) {
    let revision=0;
    function normalize(input) {
      if(!input||typeof input!=="object"||Array.isArray(input))
        throw new TypeError("REBOOT_SNAPSHOT_INVALID");
      const items=Array.isArray(input.items)?[...input.items]:[];
      return Object.freeze({...input,items:Object.freeze(items)});
    }
    let current=normalize(initial);
    function replace(next) {
      current=normalize(next);
      revision++;
      return current;
    }
    return Object.freeze({snapshot:()=>current,replace,revision:()=>revision});
  }
  globalThis.MonitorRecoverySnapshotState=Object.freeze({create});
})();
