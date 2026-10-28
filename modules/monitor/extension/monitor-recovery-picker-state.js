// Recovery overlay visibility belongs to one UI state owner.
(() => {
  "use strict";
  function create() {
    let open=false;
    const isOpen=()=>open;
    function show() {open=true;return open;}
    function close() {open=false;return open;}
    function toggle() {open=!open;return open;}
    return Object.freeze({isOpen,show,close,toggle});
  }
  globalThis.MonitorRecoveryPickerState=Object.freeze({create});
})();
