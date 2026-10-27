"use strict";
// Thumbnail compositor. It owns layer order and exposes the compatibility API;
// background and HWND pixels live in separate modules behind injected ports.
(function installMonitorDesktopThumbnailV2(root) {
  const contract=root.MonitorThumbnailContract;
  const policies=root.MonitorThumbnailLayerPolicy;
  const backgrounds=root.MonitorThumbnailBackgroundLayer;
  const windows=root.MonitorThumbnailWindowLayer;
  const interactions=root.MonitorThumbnailInteractionLayer;
  let instance=null;

  function configure({visualSource,readFrame=null,interactionPorts=null,afterWindowRender=null,layerPolicy=null}={}){
    const policy=layerPolicy?.allows
      ? layerPolicy
      : policies?.create?.(policies?.MODES?.FULL||"full")||Object.freeze({mode:"full",allows:()=>true,enabledLayers:["background","windows","interaction","semantic","summary"]});
    const background=backgrounds.create({contract,visualSource});
    const windowLayer=windows.create({contract});
    const interactionLayer=policy.allows("interaction")&&interactions?.create&&typeof interactionPorts?.moveWindow==="function"
      ?interactions.create({contract,...interactionPorts})
      :null;
    const attached=new WeakMap();
    function clearDisabledLayers(visual){
      if(!policy.allows("windows")){
        for(const node of Array.from(visual?.querySelectorAll?.(
          ".monitor-desktop-thumb-window, .monitor-thumb-v2-status"
        )||[]))node.remove?.();
      }
      if(!policy.allows("semantic")){
        for(const node of Array.from(visual?.querySelectorAll?.(
          ".monitor-thumbnail-node-overlay, .monitor-thumbnail-tab-badge, .monitor-window-status-layer, .monitor-window-pause-overlay, .monitor-window-desktop-badge, .monitor-window-non-chat-countdown, .monitor-thumbnail-z-rail, .monitor-window-capture-age-label"
        )||[]))node.remove?.();
      }
      if(!policy.allows("summary")){
        for(const node of Array.from(visual?.querySelectorAll?.(
          ".monitor-thumbnail-summary, .monitor-thumbnail-summary-layer"
        )||[]))node.remove?.();
      }
    }
    function resolve(visual,desktopId){
      const backgroundState=background.resolve(visual,desktopId);
      if(!backgroundState)return null;
      clearDisabledLayers(visual);
      const windowState=policy.allows("windows")?windowLayer.resolve(visual,desktopId):null;
      if(policy.allows("windows")&&!windowState)return null;
      let control=attached.get(visual);
      if(!control||control.desktopId!==backgroundState.desktopId){
        control={desktopId:backgroundState.desktopId,active:null,activeOptions:null,queued:null,lastResult:null};
        attached.set(visual,control);
        visual.dataset.monitorThumbnailRenderer="v2";
        visual.dataset.monitorThumbnailLayerMode=String(policy.mode||"full");
        visual.dataset.monitorThumbnailLayers=(policy.enabledLayers||[]).join(",");
      }
      return {desktopId:backgroundState.desktopId,background:backgroundState,windows:windowState,control};
    }

    const normalizeOptions=options=>({
      forceWallpaper:options?.forceWallpaper===true||options?.force===true,
      includeWindows:policy.allows("windows")&&options?.includeWindows!==false
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
            const hasSemantic=policy.allows("semantic")&&typeof afterWindowRender==="function";
            const afterRender=interactionLayer||hasSemantic
              ?(target,id)=>{interactionLayer?.reconcile(target,id);if(hasSemantic)afterWindowRender(target,id);}
              :undefined;
            frameReady=windowLayer.windowFrame(visual,desktopId,frame,{frameToken,afterRender});
          }
        }
      }
      // Background acceptance and HWND-frame acceptance are independent layer
      // contracts. Other virtual desktops can legitimately have no capturable
      // HWND pixels (for example CLOAKED/WGC-unavailable) while their exact-GUID
      // wallpaper is already valid. Keep `ok` as the compatibility signal for
      // the bottom/background layer and expose full composition separately.
      const backgroundReady=wallpaperReady===true;
      const compositeReady=backgroundReady&&(frameReady===null||frameReady===true);
      const result=Object.freeze({
        ok:backgroundReady,
        wallpaperReady:backgroundReady,
        frameReady,
        compositeReady,
        reason:backgroundReady?"":"WALLPAPER_UNAVAILABLE",
        frameReason:frameReady===false?"FRAME_UNAVAILABLE":""
      });
      const current=attached.get(visual);
      if(current===state.control){
        current.lastResult=result;
        visual.dataset.monitorThumbnailReady=backgroundReady?"1":"failed";
        visual.dataset.monitorThumbnailCompositeReady=compositeReady?"1":backgroundReady?"partial":"failed";
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
        // A request can arrive after the active pass consumed `queued` but
        // before its finally handler clears `active`.  In that narrow window a
        // full refresh used to inherit the background-only result and its HWND
        // pass was silently lost.  Join the active pass first, then repeat only
        // when this caller asked for windows and no window pass actually ran.
        return control.active.then(result=>{
          if(attached.get(visual)!==control)return result;
          if(options.includeWindows&&result?.frameReady===null)
            return refresh(visual,desktopId,rawOptions);
          return result;
        });
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
      mode:String(policy.mode||"full"),
      allowsLayer:layer=>policy.allows(layer),
      resolve,
      wallpaper:(visual,desktopId,reply,generation)=>background.apply(visual,desktopId,reply,generation),
      acceptedBackground:(visual,desktopId)=>background.accepted(visual,desktopId),
      refresh,
      refreshBackground,
      refreshWallpaper:async(visual,desktopId,options)=>(await refreshBackground(visual,desktopId,options)).wallpaperReady,
      beginFrame:(...args)=>policy.allows("windows")?windowLayer.beginFrame(...args):null,
      removeWindow:(...args)=>policy.allows("windows")?windowLayer.removeWindow(...args):false,
      windowEvent:(...args)=>policy.allows("windows")?windowLayer.windowEvent(...args):false,
      windowFrame:(...args)=>policy.allows("windows")?windowLayer.windowFrame(...args):false,
      frameFailure:(...args)=>policy.allows("windows")?windowLayer.frameFailure(...args):false,
      cancelInteraction:()=>interactionLayer?.cancel?.(),
      invalidate:(visual,desktopId)=>background.invalidate(visual,desktopId)
    });
    return instance;
  }

  const api={
    configure,
    get mode(){return instance?.mode||"unconfigured";},
    allowsLayer:layer=>instance?.allowsLayer(layer)??true,
    resolve:(...args)=>instance?.resolve(...args)??null,
    wallpaper:(...args)=>instance?.wallpaper(...args)??false,
    acceptedBackground:(...args)=>instance?.acceptedBackground(...args)??null,
    refresh:(...args)=>instance?.refresh(...args)??Promise.resolve(Object.freeze({ok:false,wallpaperReady:false,frameReady:false,reason:"NOT_CONFIGURED"})),
    refreshBackground:(...args)=>instance?.refreshBackground(...args)??Promise.resolve(Object.freeze({ok:false,wallpaperReady:false,frameReady:null,reason:"NOT_CONFIGURED"})),
    refreshWallpaper:(...args)=>instance?.refreshWallpaper(...args)??Promise.resolve(false),
    beginFrame:(...args)=>instance?.beginFrame(...args)??null,
    removeWindow:(...args)=>instance?.removeWindow(...args)??false,
    windowEvent:(...args)=>instance?.windowEvent(...args)??false,
    windowFrame:(...args)=>instance?.windowFrame(...args)??false,
    frameFailure:(...args)=>instance?.frameFailure(...args)??false,
    invalidate:(...args)=>instance?.invalidate(...args)
  };
  root.MonitorDesktopThumbnailV2=Object.freeze(api);
})(globalThis);
