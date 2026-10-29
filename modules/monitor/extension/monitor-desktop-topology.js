// The one topology projection policy for DesktopStage + DesktopStrip.
// Pure: no Native/Chrome/DOM effects, no second desktop identity cache.
(() => {
  "use strict";
  function project({observed,previous={},sharedSelection={}}) {
    const desktopIds=Array.isArray(observed?.desktopIds)?observed.desktopIds:[];
    const count=Math.max(1,Number(observed?.count)||desktopIds.length||1);
    const currentIndex=Math.min(Math.max(0,Number(observed?.currentIndex)||0),Math.max(0,count-1));
    const currentDesktopId=desktopIds[currentIndex]||null;
    const reportedHostId=typeof observed?.hostDesktopId==="string"&&
      desktopIds.includes(observed.hostDesktopId)?observed.hostDesktopId:null;
    const hostAmbiguous=observed?.hostWindowAmbiguous===true;
    const previousHostId=previous.hostDesktopId;
    const hostDesktopId=hostAmbiguous?null:
      (reportedHostId||(previousHostId&&desktopIds.includes(previousHostId)?previousHostId:null));
    const previousHostHwnd=String(previous.hostWindowHwnd||"").trim();
    const raw=String(observed?.hostWindowHwnd||"");
    const reportedHostHwnd=/^\d+$/.test(raw)&&raw!=="0"?raw:null;
    const hostWindowHwnd=hostAmbiguous?null:(reportedHostHwnd||previous.hostWindowHwnd||null);
    const hostWindowChanged=hostAmbiguous?Boolean(previousHostHwnd):
      Boolean(reportedHostHwnd&&reportedHostHwnd!==previousHostHwnd);
    const sharedId=sharedSelection.ready&&sharedSelection.desktopId&&
      desktopIds.includes(sharedSelection.desktopId)?sharedSelection.desktopId:null;
    const previousObservedId=previous.observedDesktopId;
    const observedDesktopId=sharedId||
      (previousObservedId&&desktopIds.includes(previousObservedId)?previousObservedId:
        (reportedHostId||currentDesktopId||desktopIds[0]||null));
    const selectedIndex=Math.max(0,desktopIds.indexOf(observedDesktopId));
    const state={count,currentIndex,selectedIndex,currentDesktopId,hostDesktopId,
      hostWindowHwnd,observedDesktopId,desktopIds};
    return Object.freeze({state,hostWindowChanged,previousCurrentDesktopId:previous.currentDesktopId});
  }
  globalThis.MonitorDesktopTopology=Object.freeze({project});
})();
