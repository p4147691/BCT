"use strict";
// Thumbnail compositor. It owns layer order and exposes the compatibility API;
// background and HWND pixels live in separate modules behind injected ports.
(function installMonitorDesktopThumbnailV2(root) {
  const contract=root.MonitorThumbnailContract;
  const backgrounds=root.MonitorThumbnailBackgroundLayer;
  const windows=root.MonitorThumbnailWindowLayer;
  let instance=null;

  function configure({visualSource,readFrame=null,afterWindowRender=null}={}){
    const background=backgrounds.create({contract,visualSource});
    const windowLayer=windows.create({contract});
    const attached=new WeakMap();
    function resolve(visual,desktopId){
      const backgroundState=background.resolve(visual,desktopId);
      const windowState=windowLayer.resolve(visual,desktopId);
      if(!backgroundState||!windowState)return null;
      let control=attached.get(visual);
      if(!control||control.desktopId!==backgroundState.desktopId){
        control={desktopId:backgroundState.desktopId,active:null,activeOptions:null,queued:null,lastResult:null};
        attached.set(visual,control);
        visual.dataset.monitorThumbnailRenderer="v2";
        visual.dataset.monitorThumbnailLayers="background,windows,overlay";
      }
      return {desktopId:backgroundState.desktopId,background:backgroundState,windows:windowState,control};
    }

    const normalizeOptions=options=>({
      forceWallpaper:options?.forceWallpaper===true||options?.force===true,
      includeWindows:options?.includeWindows!==false
    });
    const mergeOptions=(left,right)=>({
      forceWallpaper:Boolean(left?.forceWallpaper||right?.forceWallpaper),
      includeWindows:Boolean(left?.includeWindows||right?.includeWindows)
    });

    async function runOnce(visual,desktopId,options){
      const state=resolve(visual,desktopId);
      if(!state)return Object.freeze({ok:false,wallpaperReady:false,frameReady:false,reason:"INVALID_TARGET"});
      const wallpaperReady=await background.refresh(visual,desktopId,{force:options.forceWallpaper});
      if(!visual?.isConnected||contract.normalizeDesktopId(visual.dataset?.desktopId)!==state.desktopId)
        return Object.freeze({ok:false,wallpaperReady:false,frameReady:false,reason:"TARGET_DETACHED"});
      let frameReady=null;
      if(options.includeWindows){
        if(typeof readFrame!=="function"){
          frameReady=false;
        }else{
          const frameToken=windowLayer.beginFrame(visual,desktopId);
          let frame=null;
          try{frame=await readFrame(desktopId);}catch(_){frame=null;}
          if(!frame||!visual.isConnected){
            windowLayer.frameFailure(visual,desktopId,"FRAME_UNAVAILABLE",frameToken);
            frameReady=false;
          }else{
            frameReady=windowLayer.windowFrame(visual,desktopId,frame,{
              frameToken,
              afterRender:typeof afterWindowRender==="function"?afterWindowRender:undefined
            });
          }
        }
      }
      const ok=wallpaperReady===true&&(frameReady===null||frameReady===true);
      const result=Object.freeze({ok,wallpaperReady:wallpaperReady===true,frameReady,reason:ok?"":!wallpaperReady?"WALLPAPER_UNAVAILABLE":"FRAME_UNAVAILABLE"});
      const current=attached.get(visual);
      if(current===state.control){
        current.lastResult=result;
        visual.dataset.monitorThumbnailReady=ok?"1":"failed";
      }
      return result;
    }

    function refresh(visual,desktopId,rawOptions={}){
      const state=resolve(visual,desktopId);
      if(!state)return Promise.resolve(Object.freeze({ok:false,wallpaperReady:false,frameReady:false,reason:"INVALID_TARGET"}));
      const control=state.control,options=normalizeOptions(rawOptions);
      if(control.active){
        if(options.forceWallpaper||
            (options.includeWindows&&!control.activeOptions?.includeWindows))
          control.queued=mergeOptions(control.queued,options);
        return control.active;
      }
      const task=(async()=>{
        let next=options,result;
        do{
          control.activeOptions=next;
          result=await runOnce(visual,desktopId,next);
          if(attached.get(visual)!==control)break;
          next=control.queued;
          control.queued=null;
        }while(next);
        return result;
      })();
      const active=task.finally(()=>{
        if(control.active===active){control.active=null;control.activeOptions=null;}
      });
      control.active=active;
      return active;
    }

    async function refreshBackground(visual,desktopId,options={}){
      return await refresh(visual,desktopId,{...options,includeWindows:false});
    }
    instance=Object.freeze({
      resolve,
      wallpaper:(visual,desktopId,reply,generation)=>background.apply(visual,desktopId,reply,generation),
      refresh,
      refreshBackground,
      refreshWallpaper:async(visual,desktopId,options)=>(await refreshBackground(visual,desktopId,options)).wallpaperReady,
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
    refresh:(...args)=>instance?.refresh(...args)??Promise.resolve(Object.freeze({ok:false,wallpaperReady:false,frameReady:false,reason:"NOT_CONFIGURED"})),
    refreshBackground:(...args)=>instance?.refreshBackground(...args)??Promise.resolve(Object.freeze({ok:false,wallpaperReady:false,frameReady:null,reason:"NOT_CONFIGURED"})),
    refreshWallpaper:(...args)=>instance?.refreshWallpaper(...args)??Promise.resolve(false),
    beginFrame:(...args)=>instance?.beginFrame(...args)??null,
    removeWindow:(...args)=>instance?.removeWindow(...args)??false,
    windowFrame:(...args)=>instance?.windowFrame(...args)??false,
    frameFailure:(...args)=>instance?.frameFailure(...args)??false,
    invalidate:(...args)=>instance?.invalidate(...args)
  };
  root.MonitorDesktopThumbnailV2=Object.freeze(api);
})(globalThis);
