"use strict";
// Owns only HWND image nodes, geometry, z-order and capture failure state.
(function installMonitorThumbnailWindowLayer(root) {
  const authentic = /^(?:data:image\/(?:jpeg|png|webp);base64,|blob:)/i;
  const validPixels = value => typeof value === "string" && authentic.test(value);
  const norm = value => String(value || "").trim().toLowerCase();
  const percent = (n, origin, range) => (((Number(n) - origin) / range) * 100) + "%";
  const noop = () => {};

  function create({contract} = {}) {
    if (!contract?.isDesktopId) throw new TypeError("Thumbnail window layer requires contract");
    const states = new WeakMap();

    function resolve(visual,desktopId) {
      const id=norm(desktopId);
      if(!visual || !contract.isDesktopId(id) || norm(visual.dataset?.desktopId)!==id)return null;
      let state=states.get(visual);
      if(!state || state.desktopId!==id){
        for(const node of Array.from(visual.querySelectorAll(
          ".monitor-desktop-thumb-window, .monitor-window-capture-age-label, .monitor-thumb-v2-status"
        )))node.remove();
        state={desktopId:id,generation:0,windows:new Map()};
        states.set(visual,state);
      }
      return state;
    }

    function beginFrame(visual,desktopId){const state=resolve(visual,desktopId);return state?++state.generation:null;}

    function removeWindow(visual,desktopId,hwnd){
      const state=states.get(visual),key=String(hwnd||"");
      if(!state||state.desktopId!==norm(desktopId))return false;
      const view=state.windows.get(key);if(!view)return false;
      ++state.generation;view.image.remove();view.status.remove();state.windows.delete(key);
      visual.dataset.monitorThumbnailWindows=String(state.windows.size);return true;
    }

    function windowFrame(visual,desktopId,frame,bindings={}){
      const state=resolve(visual,desktopId);
      if(!state||!frame?.meta||!Array.isArray(frame.frames))return false;
      if(bindings.frameToken!=null&&state.generation!==bindings.frameToken)return false;
      if(norm(frame.meta.desktopId)!==state.desktopId)return false;
      const originX=Number(frame.meta.previewVirtualLeft??frame.meta.virtualLeft??0);
      const originY=Number(frame.meta.previewVirtualTop??frame.meta.virtualTop??0);
      const width=Number(frame.meta.previewVirtualWidth??frame.meta.virtualWidth);
      const height=Number(frame.meta.previewVirtualHeight??frame.meta.virtualHeight);
      if(!(width>0&&height>0))return false;
      const observed=new Set((Array.isArray(frame.meta.observedWindowHwnds)
        ?frame.meta.observedWindowHwnds:frame.frames.map(x=>x?.item?.hwnd))
        .map(x=>String(x||"")).filter(x=>/^\d+$/.test(x)));
      const seen=new Set();
      for(const entry of frame.frames){
        const item=entry?.item||{},hwnd=String(item.hwnd||"");
        if(!/^\d+$/.test(hwnd)||hwnd==="0"||item.iconic===true||!observed.has(hwnd))continue;
        const rect=[item.left,item.top,item.width,item.height].map(Number);
        if(!rect.every(Number.isFinite)||!(rect[2]>0&&rect[3]>0))continue;
        seen.add(hwnd);let view=state.windows.get(hwnd);
        if(!view){
          const image=visual.ownerDocument.createElement("img");
          image.className="monitor-desktop-thumb-window";image.dataset.hwnd=hwnd;image.alt="";image.draggable=false;visual.append(image);
          const status=visual.ownerDocument.createElement("span");
          status.className="monitor-thumb-v2-status";status.dataset.hwnd=hwnd;visual.append(status);
          view={image,status};state.windows.set(hwnd,view);
        }
        const {image,status}=view;
        image.style.left=percent(rect[0],originX,width);image.style.top=percent(rect[1],originY,height);
        image.style.width=percent(rect[2],0,width);image.style.height=percent(rect[3],0,height);
        const z=String(10000-Math.min(9999,Math.max(0,Number(item.z)||0)));
        image.dataset.nativeZIndex=z;image.style.setProperty("z-index",z,"important");
        status.style.left=image.style.left;status.style.top=image.style.top;status.style.zIndex=String(Number(z)+1);
        const recorded=Number(entry.capturedAt||0),age=Date.now()-recorded;
        const fresh=recorded>0&&age>=0&&age<=15000;
        const pixels=entry.captureState==="captured"&&entry.physicalSource!=="monitor-frozen"
          &&Number(item.cloaked||0)===0&&fresh&&validPixels(entry.dataUri)?entry.dataUri:"";
        if(pixels){
          if(image.getAttribute("src")!==pixels)image.setAttribute("src",pixels);
          image.dataset.captureState="captured";image.dataset.captureFailureReason="";
          image.dataset.monitorCapturedAt=String(recorded);image.dataset.monitorCaptureTitle=String(entry.captureTitle||item.title||"");
          image.classList.remove("monitor-thumb-v2-failed");status.hidden=true;status.textContent="";
        }else{
          image.removeAttribute("src");
          const reason=Number(item.cloaked)?"CLOAKED":entry.physicalSource==="monitor-frozen"?"SAVED_FRAME_REJECTED"
            :entry.captureState==="captured"&&!fresh?"STALE_CAPTURE":"NO_REAL_CAPTURE";
          image.dataset.captureState="failed";image.dataset.captureFailureReason=reason;image.dataset.monitorCapturedAt="0";
          image.classList.add("monitor-thumb-v2-failed");status.hidden=false;status.textContent="캡처 실패 · "+reason;
        }
        image.title=String(item.title||"")+(pixels?"":" · "+image.dataset.captureFailureReason);
        image.dataset.physicalSource=String(entry.physicalSource||"windows-native");
        image.dataset.semanticSource=String(entry.semanticSource||"none");
      }
      for(const [hwnd,view] of state.windows){if(seen.has(hwnd))continue;view.image.remove();view.status.remove();state.windows.delete(hwnd);}
      visual.dataset.monitorFrameReady="1";visual.dataset.monitorThumbnailWindows=String(state.windows.size);
      (bindings.afterRender||noop)(visual,desktopId);return true;
    }

    function frameFailure(visual,desktopId,reason="FRAME_UNAVAILABLE",frameToken=null){
      const state=resolve(visual,desktopId);
      if(!state||(frameToken!=null&&state.generation!==frameToken))return false;
      for(const {image,status} of state.windows.values()){
        image.removeAttribute("src");image.dataset.captureState="failed";image.dataset.captureFailureReason=reason;
        image.dataset.monitorCapturedAt="0";image.classList.add("monitor-thumb-v2-failed");
        status.hidden=false;status.textContent="캡처 실패 · "+reason;
      }
      visual.dataset.monitorFrameReady="failed";return true;
    }

    return Object.freeze({resolve,beginFrame,removeWindow,windowFrame,frameFailure});
  }
  root.MonitorThumbnailWindowLayer=Object.freeze({create});
})(globalThis);
