"use strict";
// Thumbnail compositor. It owns layer order and exposes the compatibility API;
// background and HWND pixels live in separate modules behind injected ports.
(function installMonitorDesktopThumbnailV2(root) {
  const contract=root.MonitorThumbnailContract;
  const backgrounds=root.MonitorThumbnailBackgroundLayer;
  const windows=root.MonitorThumbnailWindowLayer;
  let instance=null;

  function configure({visualSource}={}){
    const background=backgrounds.create({contract,visualSource});
    const windowLayer=windows.create({contract});
    const attached=new WeakMap();
    function resolve(visual,desktopId){
      const backgroundState=background.resolve(visual,desktopId);
      const windowState=windowLayer.resolve(visual,desktopId);
      if(!backgroundState||!windowState)return null;
      if(attached.get(visual)!==backgroundState.desktopId){
        attached.set(visual,backgroundState.desktopId);
        visual.dataset.monitorThumbnailRenderer="v2";
        visual.dataset.monitorThumbnailLayers="background,windows,overlay";
      }
      return {desktopId:backgroundState.desktopId,background:backgroundState,windows:windowState};
    }
    instance=Object.freeze({
      resolve,
      wallpaper:(visual,desktopId,reply,generation)=>background.apply(visual,desktopId,reply,generation),
      refreshWallpaper:(visual,desktopId,options)=>background.refresh(visual,desktopId,options),
      beginFrame:windowLayer.beginFrame,
      removeWindow:windowLayer.removeWindow,
      windowFrame:windowLayer.windowFrame,
      frameFailure:windowLayer.frameFailure,
      invalidate:(visual,desktopId)=>background.invalidate(visual,desktopId)
    });
    return instance;
  }

  const api={
    configure,
    resolve:(...args)=>instance?.resolve(...args)??null,
    wallpaper:(...args)=>instance?.wallpaper(...args)??false,
    refreshWallpaper:(...args)=>instance?.refreshWallpaper(...args)??Promise.resolve(false),
    beginFrame:(...args)=>instance?.beginFrame(...args)??null,
    removeWindow:(...args)=>instance?.removeWindow(...args)??false,
    windowFrame:(...args)=>instance?.windowFrame(...args)??false,
    frameFailure:(...args)=>instance?.frameFailure(...args)??false,
    invalidate:(...args)=>instance?.invalidate(...args)
  };
  root.MonitorDesktopThumbnailV2=Object.freeze(api);
})(globalThis);
