// Canonical DesktopStage + DesktopStrip identity owner.
// All state mutations go through replace/patch; readers receive a stable,
// frozen snapshot until the next accepted mutation.
(() => {
  "use strict";
  function create(initial) {
    let revision=0;
    function normalized(value) {
      const input=value && typeof value==="object" ? value : {};
      const desktopIds=Array.isArray(input.desktopIds) ? [...input.desktopIds] : [];
      return Object.freeze({
        ...input,desktopIds:Object.freeze(desktopIds)
      });
    }
    let current=normalized(initial);
    const snapshot=()=>current;
    function replace(value) {
      const next=normalized(value);
      current=next;revision++;
      return current;
    }
    function patch(fields) {
      if(!fields || typeof fields!=="object" || Array.isArray(fields))
        throw new TypeError("DESKTOP_STATE_PATCH_INVALID");
      return replace({...current,...fields});
    }
    return Object.freeze({snapshot,replace,patch,revision:()=>revision});
  }
  globalThis.MonitorDesktopIdentityState=Object.freeze({create});
})();
