"use strict";
// Owns pointer input for HWND thumbnail surfaces. It never reads or writes
// wallpaper/window pixels and reaches Windows only through the injected move port.
(function installMonitorThumbnailInteractionLayer(root) {
  const noop = () => {};

  function create({contract, moveWindow, onError=noop, dragThreshold=5, feedbackMs=650}={}) {
    if (!contract?.isDesktopId) throw new TypeError("Thumbnail interaction layer requires contract");
    if (typeof moveWindow !== "function") throw new TypeError("Thumbnail interaction layer requires moveWindow port");
    const bindings=new WeakMap();
    let active=null;

    const desktopTile=node=>node?.closest?.(".monitor-desktop-thumb")||null;
    const desktopIdFor=node=>String(desktopTile(node)?.dataset?.desktopId||"").trim().toLowerCase();
    const validHwnd=value=>/^\d+$/.test(String(value||""))&&String(value)!=="0";

    function clearTargets(doc){
      for(const tile of Array.from(doc?.querySelectorAll?.(".monitor-desktop-thumb")||[]))
        tile.classList.remove("monitor-desktop-drop-target");
    }

    function targetAt(doc,x,y){
      return desktopTile(doc?.elementFromPoint?.(x,y));
    }

    function createGhost(image,event){
      const doc=image.ownerDocument,rect=image.getBoundingClientRect();
      const ghost=doc.createElement("div");
      ghost.className="monitor-node-drag-ghost monitor-thumbnail-window-drag-ghost";
      ghost.style.width=`${Math.max(28,rect.width)}px`;
      ghost.style.height=`${Math.max(20,rect.height)}px`;
      ghost.style.left="0px";ghost.style.top="0px";
      doc.body.append(ghost);moveGhost(ghost,event.clientX,event.clientY);return ghost;
    }

    function moveGhost(ghost,x,y){
      if(ghost)ghost.style.transform=`translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
    }

    function removeActiveListeners(state){
      const doc=state?.image?.ownerDocument,win=doc?.defaultView||root;
      doc?.removeEventListener?.("pointermove",onPointerMove,true);
      doc?.removeEventListener?.("pointerup",onPointerUp,true);
      doc?.removeEventListener?.("pointercancel",onPointerCancel,true);
      win?.removeEventListener?.("blur",onWindowBlur);
    }

    function cleanup(state){
      if(!state)return;
      removeActiveListeners(state);clearTargets(state.image?.ownerDocument);
      state.image?.classList.remove("monitor-window-dragging");state.ghost?.remove?.();
      try{state.image?.releasePointerCapture?.(state.pointerId);}catch(_){}
      if(active===state)active=null;
    }

    function begin(event,image){
      if(active||event.button!==0)return;
      const hwnd=String(image?.dataset?.hwnd||""),sourceDesktopId=desktopIdFor(image);
      if(!validHwnd(hwnd)||!contract.isDesktopId(sourceDesktopId))return;
      const doc=image.ownerDocument,win=doc.defaultView||root;
      active={pointerId:event.pointerId,image,hwnd,sourceDesktopId,startX:event.clientX,startY:event.clientY,moved:false,ghost:null};
      doc.addEventListener("pointermove",onPointerMove,true);
      doc.addEventListener("pointerup",onPointerUp,true);
      doc.addEventListener("pointercancel",onPointerCancel,true);
      win?.addEventListener?.("blur",onWindowBlur);
      try{image.setPointerCapture?.(event.pointerId);}catch(_){}
      event.preventDefault?.();event.stopPropagation?.();
    }

    function onPointerMove(event){
      const state=active;if(!state||event.pointerId!==state.pointerId)return;
      if(!state.moved&&Math.hypot(event.clientX-state.startX,event.clientY-state.startY)<dragThreshold)return;
      if(!state.moved){
        state.moved=true;state.ghost=createGhost(state.image,event);state.image.classList.add("monitor-window-dragging");
      }
      moveGhost(state.ghost,event.clientX,event.clientY);clearTargets(state.image.ownerDocument);
      const target=targetAt(state.image.ownerDocument,event.clientX,event.clientY);
      const targetDesktopId=String(target?.dataset?.desktopId||"").trim().toLowerCase();
      if(target&&contract.isDesktopId(targetDesktopId)&&targetDesktopId!==state.sourceDesktopId)
        target.classList.add("monitor-desktop-drop-target");
      event.preventDefault?.();
    }

    async function finish(event){
      const state=active;if(!state||event.pointerId!==state.pointerId)return;
      const target=state.moved?targetAt(state.image.ownerDocument,event.clientX,event.clientY):null;
      const targetDesktopId=String(target?.dataset?.desktopId||"").trim().toLowerCase();
      const shouldMove=state.moved&&contract.isDesktopId(targetDesktopId)&&targetDesktopId!==state.sourceDesktopId;
      cleanup(state);event.preventDefault?.();event.stopPropagation?.();
      if(!shouldMove)return;
      target.classList.add("monitor-desktop-drop-pending");
      try{
        const ok=await moveWindow({hwnd:state.hwnd,sourceDesktopId:state.sourceDesktopId,targetDesktopId});
        if(ok===true)target.classList.add("monitor-desktop-drop-success");
        else onError(new Error("WINDOW_MOVE_REJECTED"),{hwnd:state.hwnd,sourceDesktopId:state.sourceDesktopId,targetDesktopId});
      }catch(error){onError(error,{hwnd:state.hwnd,sourceDesktopId:state.sourceDesktopId,targetDesktopId});}
      finally{root.setTimeout(()=>target.classList.remove("monitor-desktop-drop-pending","monitor-desktop-drop-success"),feedbackMs);}
    }

    function cancel(event){
      const state=active;if(!state||(event?.pointerId!=null&&event.pointerId!==state.pointerId))return;
      cleanup(state);
    }
    function onPointerUp(event){void finish(event);}
    function onPointerCancel(event){cancel(event);}
    function onWindowBlur(){cancel();}

    function bind(image){
      if(!image||bindings.has(image))return false;
      const handler=event=>begin(event,image);bindings.set(image,handler);
      image.dataset.monitorDragBound="1";image.draggable=false;
      image.addEventListener("pointerdown",handler);return true;
    }

    function reconcile(visual,desktopId){
      const id=String(desktopId||"").trim().toLowerCase();
      if(!visual||!contract.isDesktopId(id)||String(visual.dataset?.desktopId||"").trim().toLowerCase()!==id)return false;
      for(const image of Array.from(visual.querySelectorAll?.(".monitor-desktop-thumb-window[data-hwnd]")||[]))bind(image);
      return true;
    }

    function clear(visual){
      for(const image of Array.from(visual?.querySelectorAll?.(".monitor-desktop-thumb-window[data-hwnd]")||[])){
        const handler=bindings.get(image);if(handler)image.removeEventListener("pointerdown",handler);
        bindings.delete(image);delete image.dataset.monitorDragBound;
      }
      if(active&&visual?.contains?.(active.image))cancel();
    }

    return Object.freeze({reconcile,clear,cancel,get dragging(){return active!==null;}});
  }

  root.MonitorThumbnailInteractionLayer=Object.freeze({create});
})(globalThis);
