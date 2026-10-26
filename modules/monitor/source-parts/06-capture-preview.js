function monitorNativeWithTimeout(message, timeoutMs = 2500) {

  return new Promise((resolve, reject) => {

    let done = false;

    const timer = setTimeout(() => {

      if (done) return;

      done = true;

      try { monitorNativePort?.disconnect(); } catch (_) {}

      reject(new Error("MONITOR_NATIVE_TIMEOUT"));

    }, Math.max(250, Number(timeoutMs) || 2500));

    monitorNative(message).then((value) => { if (done) return; done = true; clearTimeout(timer); resolve(value); }, (error) => { if (done) return; done = true; clearTimeout(timer); reject(error); });

  });

}

async function approveMonitorNodeChatChange(worker, nodeState, button) {

  const binding=nodeState?.nodeBinding||{}, oldKey=String(nodeState?.previousConversationKey||binding.conversation_key||"").trim();

  const newKey=String(nodeState?.currentConversationKey||worker?.conversation_key||"").trim(); const hwnd=String(nodeState?.hwnd||binding.hwnd||"").trim();

  if(!oldKey||!newKey||oldKey===newKey||!hwnd){setMonitorStatus("챗 변경 승인 실패 · identity 부족",false);return;}

  button.disabled=true; const oldText=button.textContent; button.textContent="…";

  try{

    const response=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}); const state=response?.ok?await response.json():null;

    const endpoints=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===newKey);

    const currentEndpoint=nodeState?.endpoint||worker?.__endpoint||null;
    const currentTabId=Number(currentEndpoint?.tab_id||binding?.tab_id||0);
    const currentProfile=String(currentEndpoint?.profile_id||worker?.profile_id||binding?.profile_id||"").toUpperCase();

    let approvedEndpoint=null;
    if(currentEndpoint&&String(currentEndpoint?.conversation_key||"").trim()===newKey){
      const direct=endpoints.filter(ep=>
        Number(ep?.tab_id||0)===currentTabId
        && (!currentProfile||String(ep?.profile_id||"").toUpperCase()===currentProfile)
      );
      if(direct.length===1)approvedEndpoint=direct[0];
    }

    if(!approvedEndpoint&&currentTabId>0){
      const byTab=endpoints.filter(ep=>
        Number(ep?.tab_id||0)===currentTabId
        && (!currentProfile||String(ep?.profile_id||"").toUpperCase()===currentProfile)
      );
      if(byTab.length===1)approvedEndpoint=byTab[0];
      else if(byTab.length>1)throw new Error("현재 탭의 새 챗 endpoint가 중복됨");
    }

    if(!approvedEndpoint){
      const matching=endpoints.filter(ep=>String(monitorLocationForEndpoint(ep)?.hwnd||"")===hwnd);
      if(matching.length!==1)throw new Error(matching.length>1?"현재 창과 일치하는 새 챗 endpoint가 중복됨":"현재 탭/창의 새 챗 endpoint를 확인하지 못함");
      approvedEndpoint=matching[0];
    }

    const oldRoleSlot=(Array.isArray(state?.organization?.role_slots)?state.organization.role_slots:[]).find(x=>String(x?.state||"").toUpperCase()==="ACTIVE"&&String(x?.conversation_key||"").trim()===oldKey);

    if(oldRoleSlot){

      const role=String(oldRoleSlot?.role||"").toUpperCase();

      if(["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"].includes(role)){

        const r=await fetch(`${ORCHESTRATOR_ROLE_ADMIN_URL}/replace`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({role,conversation_key:newKey,expected_generation:Number(oldRoleSlot.generation||0)})});

        const d=await r.json().catch(()=>null); if(!r.ok||!d?.ok)throw new Error(d?.error||`HTTP ${r.status}`);

      }

    }

    const next={...binding,conversation_key:newKey,profile_id:String(approvedEndpoint?.profile_id||binding.profile_id||"").toUpperCase(),title:String(approvedEndpoint?.title||worker?.title||binding.title||""),window_instance_id:String(approvedEndpoint?.window_instance_id||approvedEndpoint?.metadata?.window_instance_id||binding.window_instance_id||"")};

    const stored=monitorStoreNodeBinding(next,approvedEndpoint);

    monitorRememberApprovedChatTransition(stored?.node_identity_key||binding?.node_identity_key||monitorStableBrowserNodeKey({...worker,__endpoint:approvedEndpoint}),stored?.profile_id||binding.profile_id,oldKey,newKey);

    await refreshAiMonitor();

    setMonitorStatus(`${next.node_label||"노드"} 승인 · 새 챗과 매칭 유지`,true);

  }catch(error){setMonitorStatus(`챗 변경 승인 실패 · ${error?.message||error}`,false);}finally{button.textContent=oldText;button.disabled=false;}

}

async function restoreMonitorNodeChatChange(worker,nodeState,button){

  const binding=nodeState?.nodeBinding||{}; const key=String(binding.conversation_key||nodeState?.previousConversationKey||"").trim(); const profile=String(binding.profile_id||worker?.profile_id||"").toUpperCase(); const targetDesktopId=String(binding.desktop_id||"");

  if(!key||!profile){setMonitorStatus("원래 창 복구 실패 · 원래 대화 정보 없음",false);return;}

  button.disabled=true; const oldText=button.textContent; button.textContent="…";

  try{

    const stateResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}); const state=stateResponse?.ok?await stateResponse.json():null;

    const open=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN"&&String(ep?.conversation_key||"").trim()===key);

    if(open.length>1)throw new Error("원래 대화가 여러 창에 열려 있음");

    const currentEndpoint=nodeState?.endpoint||worker?.__endpoint||null;
    const targetTabId=Number(currentEndpoint?.tab_id||binding?.tab_id||0);
    if(!Number.isInteger(targetTabId)||targetTabId<=0)throw new Error("현재 탭 ID 확인 실패");
    const otherOpen=open.filter(ep=>Number(ep?.tab_id||0)!==targetTabId);
    if(otherOpen.length)throw new Error("원래 대화가 다른 탭에 이미 열려 있음");
    let endpoint=String(currentEndpoint?.conversation_key||"").trim()===key ? currentEndpoint : null;

    if(!endpoint){
      const nav=await chrome.runtime.sendMessage({type:"monitor-navigate-chat-tab",tabId:targetTabId,conversationKey:key}).catch(error=>({ok:false,error:error?.message||String(error)}));
      if(!nav?.ok)throw new Error(nav?.error||"현재 탭 복구 실패");
    }

    for(let i=0;i<24&&!endpoint;i++){
      await new Promise(r=>setTimeout(r,250));
      const rr=await actFetch(ORCHESTRATOR_MONITOR_STATE_URL,{cache:"no-store"});
      const ss=rr?.ok?await rr.json():null;
      const matches=(Array.isArray(ss?.endpoints)?ss.endpoints:[]).filter(ep=>
        String(ep?.presence_state||"").toUpperCase()==="OPEN"
        && String(ep?.conversation_key||"").trim()===key
        && Number(ep?.tab_id||0)===targetTabId
      );
      if(matches.length>1)throw new Error("복구 endpoint 중복");
      if(matches.length===1)endpoint=matches[0];
    }

    if(!endpoint)throw new Error("복구된 대화가 ACT에 등록되지 않음");

    const hwnd=endpointOsWindowHandle(endpoint); if(!hwnd)throw new Error("복구된 창 HWND 확인 실패");

    if(targetDesktopId)await moveMonitorWindowToDesktop(hwnd,"",targetDesktopId);

    const next={...binding,conversation_key:key,profile_id:profile,title:String(endpoint?.title||binding.title||""),window_instance_id:String(endpoint?.window_instance_id||endpoint?.metadata?.window_instance_id||binding.window_instance_id||"")};

    monitorStoreNodeBinding(next,endpoint); await refreshAiMonitor(); setMonitorStatus(`${next.node_label||"노드"} 복구 · 현재 탭을 원래 챗으로 되돌림`,true);

  }catch(error){setMonitorStatus(`원래 챗 복구 실패 · ${error?.message||error}`,false);}finally{button.textContent=oldText;button.disabled=false;}

}

async function restoreMonitorAllRecovery(button,listRecords,items){

  if(!button||button.disabled)return; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  try{for(const item of listRecords||[])restoreMonitorTrashRecord(item?.conversation_key);for(const item of items||[]){const temp=document.createElement("button");temp.textContent="복구";await restoreMonitorDetachedTask(item,temp);}}

  finally{button.textContent=old;button.disabled=false;refreshMonitorRecoveryMenu();}

}

async function restoreMonitorRebootSnapshot(button) {

  const items=[...(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[])];

  if(!items.length||monitorRebootRestoreActive||!button)return {ok:false,status:"IGNORED",results:[]};

  monitorRebootRestoreActive=true; button.disabled=true; const old=button.textContent; button.textContent="전체 복원 중…";

  const results=[];

  try{    for(const item of items){

      const key=String(item?.conversation_key||"").trim(); if(!key)continue;

      monitorRebootRestorePendingKeys.add(key);

      const temp=document.createElement("button");temp.textContent="복구";

      const result=await restoreMonitorDetachedTask({...item,__reboot_restore:true},temp);

      results.push(result||{ok:false,status:"FAILED",conversationKey:key,error:"복구 결과 없음"});

      if(result?.ok){

        const r=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null),state=r?.ok?await r.json().catch(()=>null):null;

        const ep=(Array.isArray(state?.endpoints)?state.endpoints:[]).find((x)=>String(x?.conversation_key||"").trim()===key&&String(x?.presence_state||"").toUpperCase()==="OPEN");

        if(ep){

          const resolved=monitorExactConversationWindow(key,state,Date.now(),ep);

          const hwnd=String(resolved?.location?.hwnd||endpointOsWindowHandle(ep)||"").trim();

          const target=monitorDesktopState.desktopIds[Math.max(0,Number(item.desktop||1)-1)]||String(item.desktop_id||"");

          if(/^\d+$/.test(hwnd)&&hwnd!=="0"&&target){

            const moved=await monitorNative({type:"moveWindowToDesktop",hwnd,desktopId:target}).catch(()=>null);

            if(moved&&moved.ok===false)result.positionWarning=String(moved.error||"원래 데스크톱 이동 실패");

          }

        }

      }

      monitorRebootRestorePendingKeys.delete(key); await refreshAiMonitor();

    }

    const failed=results.filter((row)=>!row?.ok);

    const opened=results.filter((row)=>row?.ok&&row?.status==="RESTORED").length;

    const existing=results.filter((row)=>row?.ok&&row?.status==="ALREADY_OPEN").length;

    if(failed.length){

      const names=failed.slice(0,3).map((row)=>row?.nodeLabel||String(row?.conversationKey||"").slice(0,8)).join(", ");

      setMonitorStatus(`전체 복원 일부 실패 · 새로 ${opened} · 이미 열림 ${existing} · 실패 ${failed.length}${names?` · ${names}`:""}`,false);

    }else setMonitorStatus(`이전 상태 전체 복원 완료 · 새로 ${opened} · 이미 열림 ${existing}`,true);

    return {ok:failed.length===0,status:failed.length?"PARTIAL":"COMPLETE",results};  }catch(error){

    setMonitorStatus(`전체 복원 실패 · ${error?.message||error}`,false);

    return {ok:false,status:"FAILED",error:String(error?.message||error),results};

  }finally{

    for(const item of items)monitorRebootRestorePendingKeys.delete(String(item?.conversation_key||""));

    monitorRebootRestoreActive=false;

    const expected=items.filter((item)=>String(item?.conversation_key||"").trim()).length;

    const allVerified=results.length===expected&&results.every((row)=>row?.ok);

    button.disabled=false; button.textContent=old;

    if(monitorLastAiState){if(allVerified)monitorCaptureRebootSnapshot(monitorLastAiState);renderWorkers(monitorLastAiState);}

  }

}

function createMonitorContextContinueButton(item) {
  const captured = { ...item };
  return globalThis.MonitorContextResume.createButton({
    target: captured,
    fetcher: actFetch,
    openConversation: () => restoreMonitorDetachedTask(captured, document.createElement('button')),
  });
}

function createMonitorProjectContextRecallButton() {
  return globalThis.MonitorProjectContextRecall.createButton({
    fetcher: actFetch,
    openConversation: target => restoreMonitorDetachedTask(target, document.createElement('button')),
  });
}

function createMonitorWorkRecoveryButton() {
  return globalThis.MonitorWorkRecovery.createButton({
    fetcher: actFetch,
    openConversation: target => restoreMonitorDetachedTask(target, document.createElement('button')),
  });
}

async function restoreMonitorDetachedTask(item, button) {

  const key=String(item?.conversation_key||"").trim();

  let profile=String(item?.profile_id||"").trim().toUpperCase();

  const nodeLabel=String(item?.node_label||"").trim();

  if(!key||!button)return {ok:false,status:"INVALID",conversationKey:key,profileId:profile,nodeLabel,error:"복구 대상 정보 없음"};

  if(button.disabled||monitorDetachedRestorePending.has(key))return {ok:false,status:"BUSY",conversationKey:key,profileId:profile,nodeLabel,error:"이미 복구 진행 중"};

  monitorDetachedRestorePending.add(key);

  button.disabled=true; const original=button.textContent; button.textContent="복구 중…";

  try{

    const preResponse=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

    if(!preResponse?.ok)throw new Error("ACT 상태 확인 실패");

    const preState=await preResponse.json().catch(()=>null);

    if(!preState)throw new Error("ACT 상태 응답 해석 실패");

    const exactEndpoints=(Array.isArray(preState?.endpoints)?preState.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key);
    const observedProfiles=[...new Set(exactEndpoints.map((candidate)=>String(candidate?.profile_id||"").trim().toUpperCase()).filter(Boolean))];
    if(!profile){
      if(observedProfiles.length!==1)throw new Error(observedProfiles.length ? "복구 대상 Chrome 프로필이 여러 개라 자동으로 선택할 수 없음" : "복구 대상 Chrome 프로필이 ACT에 기록되어 있지 않음");
      profile=observedProfiles[0];
    }else if(observedProfiles.length&& !observedProfiles.includes(profile))throw new Error("기록의 Chrome 프로필이 ACT endpoint 기록과 다름");
    const alreadyOpen=exactEndpoints.filter((candidate)=>String(candidate?.presence_state||"").toUpperCase()==="OPEN");

    if(alreadyOpen.length>1)throw new Error("같은 대화의 OPEN endpoint가 여러 개임");    let endpoint=alreadyOpen[0]||null;

    let status=endpoint?"ALREADY_OPEN":"RESTORED";

    if(endpoint&&profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("이미 열린 대화의 Chrome 프로필이 복구 기록과 다름");

    if(!endpoint){

      const launch=await monitorNative({type:"restoreChatGptConversation",profileId:profile,conversationKey:key}).catch((error)=>({ok:false,error:String(error?.message||error)}));

      if(!launch?.ok||!launch?.launched)throw new Error(`브라우저 복구 실행 실패 · ${launch?.error||"Native Host 응답 없음"}`);

      for(let i=0;i<30&&!endpoint;i+=1){

        await new Promise((resolve)=>setTimeout(resolve,500));

        const response=await actFetch(ORCHESTRATOR_STATE_URL,{cache:"no-store"}).catch(()=>null);

        const state=response?.ok?await response.json().catch(()=>null):null;

        const matches=(Array.isArray(state?.endpoints)?state.endpoints:[]).filter((candidate)=>String(candidate?.conversation_key||"").trim()===key&&String(candidate?.presence_state||"").toUpperCase()==="OPEN");

        if(matches.length>1)throw new Error("Ambiguous OPEN endpoints after restore.");

        if(matches.length===1)endpoint=matches[0];

      }

      if(!endpoint)throw new Error("브라우저는 실행했지만 15초 안에 ACT endpoint가 등록되지 않음");

      if(profile&&String(endpoint?.profile_id||"").trim().toUpperCase()!==profile)throw new Error("Restored endpoint profile mismatch.");

    }

    monitorHiddenGhosts.delete(key); monitorGhostPersist();

    if(!item?.__reboot_restore)monitorClosedConversationPickerOpen=false;

    await refreshAiMonitor();

    if(!item?.__reboot_restore)setMonitorStatus(`${nodeLabel||"대화"} 복구 완료${status==="ALREADY_OPEN"?" · 이미 열려 있음":""}`,true);

    return {ok:true,status,conversationKey:key,profileId:profile,nodeLabel,endpoint};

  }catch(error){

    const message=String(error?.message||error);

    setMonitorStatus(`${nodeLabel||"대화"} 복구 실패 · ${message}`,false);

    button.title=message;

    console.warn("DesktopWindow Monitor conversation recovery failed",{conversationKey:key,profileId:profile,nodeLabel,error:message});

    return {ok:false,status:"FAILED",conversationKey:key,profileId:profile,nodeLabel,error:message};  }finally{

    monitorDetachedRestorePending.delete(key);

    button.textContent=original; button.disabled=false;

    if(monitorLastAiState)renderWorkers(monitorLastAiState);

  }

}

let monitorCoreNativePort = null;

const monitorCoreNativePending = [];

function ensureMonitorCoreNativePort() {

  if (monitorCoreNativePort) return monitorCoreNativePort;

  const port = chrome.runtime.connectNative(MONITOR_CORE_HOST);

  monitorCoreNativePort = port;

  port.onMessage.addListener((response) => {

    if (response?.type === "shellMirrorChanged" || response?.subscribed === true) {

      window.dispatchEvent(new CustomEvent("desktopwindow-shell-native-event", { detail: response }));

      return;

    }

    if (response?.event === true) return; // Unsolicited native events cannot consume command replies.
    const pending = monitorCoreNativePending.shift();

    if (pending) pending.resolve(response);

  });

  port.onDisconnect.addListener(() => {

    const error = chrome.runtime.lastError?.message || "Monitor Core Native Host 연결 종료";

    monitorCoreNativePort = null;

    while (monitorCoreNativePending.length) monitorCoreNativePending.shift().reject(new Error(error));

  });

  // Core port carries request/response traffic only. Uncorrelated subscription
  // messages used to consume the next pending request response.

  return port;

}

function monitorCoreNative(message) {
  return MonitorNativeTrace.request("core", message, () => monitorCoreNativeRequest(message));
}

function monitorCoreNativeRequest(message) {

  return new Promise((resolve, reject) => {

    const port = ensureMonitorCoreNativePort(); monitorCoreNativePending.push({ resolve, reject });

    try { port.postMessage(message); } catch (error) { monitorCoreNativePending.pop(); reject(error); }

  });

}

let monitorWallpaperToken = 0;

const monitorWallpaperCache = new Map();
const monitorWallpaperActuals = new Map();

// Substitution wallpaper map removed.

const MONITOR_WALLPAPER_CACHE_MS = 15000;

const MONITOR_WALLPAPER_CACHE_LIMIT = 3;

const MONITOR_WALLPAPER_ACTUAL_LIMIT = 8;
const MONITOR_WALLPAPER_MAX_WIDTH = 960;
const MONITOR_WALLPAPER_MAX_HEIGHT = 600;
// Wallpaper pixels are bounded and cached separately. Individual window captures
// stay disabled until decoded-image ownership in the native capture path is fixed.
const MONITOR_PIXEL_VISUALS_ENABLED = true;
// Per-window pixels use the isolated one-frame WGC helper. Native capture is
// bounded to two concurrent requests and the helper exits after each snapshot.
const MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED = true;

function monitorRememberWallpaperEntry(map, desktopId, dataUri, limit) {
  const key = String(desktopId || "");
  if (!key || !dataUri) return;
  map.delete(key);
  map.set(key, { dataUri, at: Date.now() });
  while (map.size > limit) {
    const oldestKey = map.keys().next().value;
    if (!oldestKey) break;
    map.delete(oldestKey);
  }
}

async function monitorLightweightWallpaperDataUri(dataUri) {
  const source = String(dataUri || "");
  if (!source.startsWith("data:image/")) return source;
  try {
    const image = await new Promise((resolve, reject) => {
      const node = new Image();
      node.onload = () => resolve(node);
      node.onerror = reject;
      node.src = source;
    });
    const width = Math.max(1, Number(image.naturalWidth || image.width || 1));
    const height = Math.max(1, Number(image.naturalHeight || image.height || 1));
    const scale = Math.min(1, MONITOR_WALLPAPER_MAX_WIDTH / width, MONITOR_WALLPAPER_MAX_HEIGHT / height);
    if (scale >= 1) return source;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d", { alpha:false });
    if (!ctx) return source;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    const compact = canvas.toDataURL("image/jpeg", 0.68);
    canvas.width = 1;
    canvas.height = 1;
    return compact || source;
  } catch (_) {
    return source;
  }
}

const monitorFrameCache = new Map();

const monitorFrameInflight = new Map();

let monitorFrameGeneration = 0;
const monitorFrameDesktopGenerations = new Map();

function monitorDesktopFrameGeneration(desktopId) {
  const key = String(desktopId || "");
  return `${monitorFrameGeneration}.${Number(monitorFrameDesktopGenerations.get(key) || 0)}`;
}

const MONITOR_FRAME_CACHE_LIMIT = 4;
const MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS = 15000;
const MONITOR_WINDOW_CAPTURE_MAX_AGE_MS = 30000;
function monitorCaptureMatchesCurrentWindow(captureTitle,currentTitle,capturedAt,now=Date.now()){
  const age=Number(now)-Number(capturedAt||0);
  return Boolean(String(captureTitle||"").trim())
    && String(captureTitle||"").trim()===String(currentTitle||"").trim()
    && Number.isFinite(age)&&age>=0&&age<=MONITOR_WINDOW_CAPTURE_MAX_AGE_MS;
}

function monitorRevokeThumbWindowCaptureSource(source) {
  const value = String(source || "");
  if (!value.startsWith("blob:")) return;
  URL.revokeObjectURL(value);
  monitorRenderDiagnostics.blobRevokes += 1;
}

if (!globalThis.MonitorThumbnailService?.create) {
  throw new Error("MonitorThumbnailService module is not loaded");
}

// Profiles intentionally have separate caches (thumbnail, preview and frozen),
// but they all consume the same WGC/native capture resource.  A single gate
// prevents a mixed-profile refresh from turning three per-profile limits into
// six simultaneous native captures.
const monitorCaptureScheduler = (() => {
  // One WGC snapshot at a time keeps desktop interaction responsive. Refresh
  // queues remain coalesced by HWND, so this trades a little thumbnail latency
  // for a bounded CPU/GPU burst rather than dropping a requested frame.
  const maxConcurrent = 1;
  const queue = [];
  let active = 0;
  let maxObservedActive = 0;

  const drain = () => {
    while (active < maxConcurrent && queue.length) {
      const next = queue.shift();
      if (!next) continue;
      active += 1;
      maxObservedActive = Math.max(maxObservedActive, active);
      Promise.resolve()
        .then(next.task)
        .then(next.resolve, next.reject)
        .finally(() => {
          active = Math.max(0, active - 1);
          drain();
        });
    }
  };

  return Object.freeze({
    run(task) {
      return new Promise((resolve, reject) => {
        queue.push({ task, resolve, reject });
        drain();
      });
    },
    stats() {
      return Object.freeze({ maxConcurrent, active, queued: queue.length, maxObservedActive });
    }
  });
})();

function createMonitorWindowCaptureService({ maxEntries, maxWidth, maxHeight, quality }) {
  return globalThis.MonitorThumbnailService.create({
  maxConcurrent: 2,
  maxEntries,
  maxWidth,
  maxHeight,
  async capture({ hwnd, reason, maxWidth, maxHeight }) {
    return monitorCaptureScheduler.run(async () => {
      monitorRenderDiagnostics.captureRuns += 1;
      const captureTitle=String(monitorWindowDesktopLocations.get(String(hwnd))?.title||"");
      const capturedAt=Date.now();
      const capture = await monitorCoreNative({
        type: "captureWindow",
        hwnd,
        maxWidth,
        maxHeight,
        quality,
        reason
      }).catch(() => null);
      const source = capture?.ok ? String(capture.dataUri || "") : "";
      if (!source || capture?.captureEngine !== "wgc-oneshot") {
        monitorRevokeThumbWindowCaptureSource(source);
        monitorRenderDiagnostics.captureFailure += 1;
        return null;
      }
      const objectUrl = monitorCaptureDataUriToObjectUrl(source);
      monitorRenderDiagnostics.captureSuccess += 1;
      return {
        value: objectUrl,
        dispose: () => monitorRevokeThumbWindowCaptureSource(objectUrl),
        meta: {
          captureEngine: capture.captureEngine,
          width: Number(capture.width || 0),
          height: Number(capture.height || 0),
          captureTitle,capturedAt
        }
      };
    });
  }
  });
}

const monitorThumbnailCaptureServices = Object.freeze({
  thumb: createMonitorWindowCaptureService({ maxEntries: 12, maxWidth: 480, maxHeight: 270, quality: 52 }),
  preview: createMonitorWindowCaptureService({ maxEntries: 6, maxWidth: 960, maxHeight: 540, quality: 68 }),
  frozen: createMonitorWindowCaptureService({ maxEntries: 32, maxWidth: 960, maxHeight: 540, quality: 68 })
});

function monitorWindowCaptureService(profile) {
  if (profile === "frozen") return monitorThumbnailCaptureServices.frozen;
  return profile === "preview" ? monitorThumbnailCaptureServices.preview : monitorThumbnailCaptureServices.thumb;
}

const monitorThumbnailService = Object.freeze({
  async requestSnapshot(hwnd, reason = "unspecified", profile = "thumb") {
    monitorRenderDiagnostics.captureRequests += 1;
    const key = String(hwnd || "").trim();
    if (!key || !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED) return "";
    const item = monitorWindowDesktopLocations.get(key);
    if (monitorWindowUsesFrozenCapture(item)) {
      const shared = String(item?.frozenDataUri || "");
      if (shared.startsWith("data:image/")) return shared;
    }
    const captureProfile = monitorWindowUsesFrozenCapture(item) ? "frozen" : profile;
    const service = monitorWindowCaptureService(captureProfile);
    const cached = service.getCached(key);
    if(cached&&!monitorCaptureMatchesCurrentWindow(cached.meta?.captureTitle,item?.title,cached.meta?.capturedAt))service.invalidate(key);
    const result = await service.requestSnapshot(key, reason).catch(() => null);
    return String(result?.value || "");
  },
  invalidate(hwnd) {
    const key = String(hwnd || "").trim();
    if (monitorWindowUsesFrozenCapture(monitorWindowDesktopLocations.get(key))) return false;
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.invalidate(key) || changed;
    return changed;
  },
  dispose(hwnd) {
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.dispose(hwnd) || changed;
    return changed;
  },
  disposeAll() {
    for (const service of Object.values(monitorThumbnailCaptureServices)) service.disposeAll();
  },
  stats() {
    const profiles = Object.fromEntries(Object.entries(monitorThumbnailCaptureServices).map(([name, service]) => [name, service.stats()]));
    const totals = Object.values(profiles).reduce((sum, profile) => {
      for (const key of ["requested", "cacheHits", "coalesced", "queued", "started", "completed", "failed", "staleDiscarded", "evicted", "disposedResults", "active", "queuedNow", "cached", "trackedWindows"]) sum[key] = Number(sum[key] || 0) + Number(profile[key] || 0);
      sum.maxObservedActive = Math.max(Number(sum.maxObservedActive || 0), Number(profile.maxObservedActive || 0));
      return sum;
    }, {});
    return { ...totals, profiles, nativeCapture: monitorCaptureScheduler.stats() };
  }
});

window.addEventListener("pagehide", () => {
  stopMonitorBctNativePreview();
  monitorThumbnailService.disposeAll();
}, { once:true });

async function monitorGetWindowCapture(hwnd, profile = "thumb") {
  return monitorThumbnailService.requestSnapshot(hwnd, "desktop-frame", profile);
}

let monitorOwnFrozenCaptureHwnd = "";
let monitorOwnFrozenCaptureAttemptedHwnd = "";
let monitorOwnFrozenCaptureBusy = false;

async function ensureMonitorOwnFrozenSnapshot() {
  const hwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();
  const desktopId = String(monitorDesktopState.hostDesktopId || "").trim();
  if (!monitorIsActiveDesktopRenderer()) {
    monitorOwnFrozenCaptureAttemptedHwnd = "";
    return false;
  }
  if (!/^\d+$/.test(hwnd) || hwnd === "0" || !desktopId) return false;
  if (monitorOwnFrozenCaptureHwnd === hwnd) return true;
  if (monitorOwnFrozenCaptureAttemptedHwnd === hwnd || monitorOwnFrozenCaptureBusy) return false;

  monitorOwnFrozenCaptureAttemptedHwnd = hwnd;
  monitorOwnFrozenCaptureBusy = true;
  try {
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (String(monitorDesktopState.hostWindowHwnd || "") !== hwnd || !monitorIsActiveDesktopRenderer()) return false;

    const runtime = await chrome.runtime.sendMessage({ type:"monitor-list-popup-runtime" }).catch(() => null);
    const existing = (Array.isArray(runtime?.windows) ? runtime.windows : [])
      .find((item) => String(item?.hwnd || "") === hwnd);
    if (String(existing?.frozenDataUri || "").startsWith("data:image/")) {
      monitorOwnFrozenCaptureHwnd = hwnd;
      return true;
    }

    // Startup capture can race the popup becoming WGC-ready. Retry only this HWND
    // a bounded number of times; there is no recurring timer or background polling.
    const retryDelays = [0, 160, 420];
    for (let attempt = 0; attempt < retryDelays.length; attempt += 1) {
      if (retryDelays[attempt] > 0) await new Promise((resolve) => setTimeout(resolve, retryDelays[attempt]));
      if (String(monitorDesktopState.hostWindowHwnd || "") !== hwnd || !monitorIsActiveDesktopRenderer()) return false;
      const capture = await monitorCoreNative({
        type:"captureWindow",
        hwnd,
        maxWidth:960,
        maxHeight:540,
        quality:68,
        reason:"monitor-self-frozen"
      }).catch(() => null);
      const dataUri = capture?.ok && capture?.captureEngine === "wgc-oneshot" ? String(capture.dataUri || "") : "";
      if (!dataUri.startsWith("data:image/")) continue;

      const saved = await chrome.runtime.sendMessage({
        type:"monitor-update-popup-runtime",
        desktopId,
        hwnd,
        frozenDataUri:dataUri
      }).catch(() => null);
      if (!saved?.ok) continue;
      monitorOwnFrozenCaptureHwnd = hwnd;
      return true;
    }
    return false;
  } finally {
    monitorOwnFrozenCaptureBusy = false;
  }
}


let monitorCurrentWallpaperCaptureBusy = false;

async function ensureMonitorCurrentWallpaperSnapshot(desktopIdValue) {
  const desktopId = String(desktopIdValue || "").trim();
  const currentDesktopId = String(monitorDesktopState.currentDesktopId || "").trim();
  if (!desktopId || desktopId !== currentDesktopId || !monitorIsActiveDesktopRenderer() || monitorCurrentWallpaperCaptureBusy) return false;

  monitorCurrentWallpaperCaptureBusy = true;
  try {
    const retryDelays = [0, 160, 420];
    for (const delay of retryDelays) {
      if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
      if (String(monitorDesktopState.currentDesktopId || "").trim() !== desktopId || !monitorIsActiveDesktopRenderer()) return false;

      const capture = await monitorCoreNative({
        type:"captureCurrentDesktopWallpaper",
        maxWidth:MONITOR_WALLPAPER_MAX_WIDTH,
        maxHeight:MONITOR_WALLPAPER_MAX_HEIGHT,
        quality:68
      }).catch(() => null);
      const capturedDesktopId = String(capture?.desktopId || "").trim();
      const rawDataUri = capture?.ok && capturedDesktopId.toLowerCase() === desktopId.toLowerCase() ? String(capture?.dataUri || "") : "";
      if (!rawDataUri.startsWith("data:image/")) continue;

      const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);
      if (!String(dataUri || "").startsWith("data:image/")) continue;

      monitorRememberWallpaperEntry(monitorWallpaperActuals, desktopId, dataUri, MONITOR_WALLPAPER_ACTUAL_LIMIT);
      monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);
      invalidateMonitorDesktopFrames(desktopId);

      await chrome.runtime.sendMessage({
        type:"monitor-update-popup-runtime",
        desktopId,
        hwnd:String(monitorDesktopState.hostWindowHwnd || ""),
        wallpaperDataUri:dataUri
      }).catch(() => null);
      return true;
    }
    return false;
  } finally {
    monitorCurrentWallpaperCaptureBusy = false;
  }
}

let monitorThumbBatchGeneration = 0;

let monitorThumbBatchInflight = null;

function monitorCapturePaused() {
  return Boolean(monitorWindowPointerDrag || monitorDesktopPointerDrag);
}

function monitorIsActiveDesktopRenderer() {
  const hostDesktopId = String(monitorDesktopState.hostDesktopId || "").trim();
  const currentDesktopId = String(monitorDesktopState.currentDesktopId || "").trim();
  // Preserve startup/recovery until native host identity is known. After that,
  // only the Monitor on the current Windows virtual desktop may capture pixels.
  if (!hostDesktopId || !currentDesktopId) return true;
  return hostDesktopId === currentDesktopId;
}

async function getObservedWallpaper(desktopId, force = false) {

  if (!MONITOR_PIXEL_VISUALS_ENABLED || !desktopId) return "";

  const actual = monitorWallpaperActuals.get(desktopId);
  // Explicit refresh must consult Native, not reuse an indefinitely retained image.
  if (!force && actual?.dataUri) {
    monitorWallpaperActuals.delete(desktopId);
    monitorWallpaperActuals.set(desktopId, actual);
    return actual.dataUri;
  }
  const cached = monitorWallpaperCache.get(desktopId);

  if (!force && cached && Date.now() - cached.at <= MONITOR_WALLPAPER_CACHE_MS) { monitorWallpaperCache.delete(desktopId); monitorWallpaperCache.set(desktopId, cached); return cached.dataUri; }

  // Wallpaper fallback removed: only a genuine Native result is accepted.

  try {

    const response = await monitorCoreNative({
      type: "getDesktopVisualSnapshot",
      desktopId,
      maxWidth: MONITOR_WALLPAPER_MAX_WIDTH,
      maxHeight: MONITOR_WALLPAPER_MAX_HEIGHT,
      quality: 68
    });

    const rawDataUri = response?.wallpaper?.dataUri || "";
    const dataUri = await monitorLightweightWallpaperDataUri(rawDataUri);

    if (dataUri) monitorRememberWallpaperEntry(monitorWallpaperCache, desktopId, dataUri, MONITOR_WALLPAPER_CACHE_LIMIT);

    return dataUri;

  } catch (_) { return ""; }

}

async function applyObservedWallpaper(desktopId, force = false) {

  const token = ++monitorWallpaperToken;
  const wallpaperState = globalThis.MonitorWallpaperState;
  const request = wallpaperState?.begin?.(desktopId);

  const dataUri = await getObservedWallpaper(desktopId, force);

  if (token !== monitorWallpaperToken) return;
  const recorded = request ? wallpaperState.resolve(desktopId, request.generation,
    {ok:Boolean(dataUri),dataUri,error:dataUri ? "" : "NATIVE_WALLPAPER_UNAVAILABLE"}) : null;
  if (request && !recorded?.applied) return;

  if (dataUri) {

    monitorPreviewWallpaper.style.backgroundImage = `url("${dataUri}")`;

    monitorPreviewWallpaper.dataset.desktopId = String(desktopId || "");
    monitorPreviewWallpaper.dataset.captureState = "captured";
  } else {
    monitorPreviewWallpaper.style.backgroundImage = "";
    monitorPreviewWallpaper.dataset.desktopId = String(desktopId || "");
    monitorPreviewWallpaper.dataset.captureState = "failed";
  }

}

function monitorActDesktopVisualForDesktop(desktopId, state = monitorLastAiState) {

  const visual = state?.node_state?.desktop_visual;

  if (String(visual?.authority || "") !== "ACT" || String(visual?.source || "") !== "ACT_NATIVE_OBSERVER") return null;

  const desk = (Array.isArray(visual?.desktops) ? visual.desktops : []).find((row) => String(row?.desktop_id || "") === String(desktopId || ""));

  if (!desk) return null;

  const viewport = desk?.viewport || {};

  const windows = (Array.isArray(desk?.windows) ? desk.windows : []).map((row) => ({

    hwnd:String(row?.hwnd||""), left:Number(row?.rect?.left||0), top:Number(row?.rect?.top||0),

    width:Number(row?.rect?.width||0), height:Number(row?.rect?.height||0), z:Number(row?.z||0),

    conversationKey:String(row?.conversation_key||"")

  })).filter((row) => /^\d+$/.test(row.hwnd) && row.hwnd !== "0");

  return {ok:true, authority:"ACT", desktopId:String(desktopId||""), windows,

    previewVirtualLeft:Number(viewport.left||0), previewVirtualTop:Number(viewport.top||0),

    previewVirtualWidth:Number(viewport.width||0), previewVirtualHeight:Number(viewport.height||0)};

}

function monitorWindowUsesFrozenCapture(item) {
  return monitorIsOwnWindowTitle(item?.title);
}

function monitorWindowCanRefreshPixels(item) {
  // DWM keeps off-desktop windows alive but reports them as cloaked. WGC can
  // return a formally successful, solid grey frame for those HWNDs. Never let
  // that transient frame replace the last useful capture.
  return Number(item?.cloaked || 0) === 0;
}

function monitorShouldKeepExistingCapture(existingState, existingSource, nextState) {
  const source = String(existingSource || "");
  return String(nextState || "") !== "captured"
    && String(existingState || "") === "captured"
    && (source.startsWith("blob:") || source.startsWith("data:image/"));
}

function monitorChooseCaptureView(input, settings) {
  // The layout module owns the normal last-good policy. Keep a minimal,
  // non-throwing fallback so a partially copied presentation payload cannot
  // abort the whole thumbnail render loop before the deployment gate rejects
  // that inconsistent payload.
  const chooser = globalThis.MonitorUiLayout?.chooseCaptureView;
  if (typeof chooser === "function") return chooser(input, settings);
  const now = Number.isFinite(input?.now) ? Number(input.now) : Date.now();
  const source = String(input?.nextSource || "");
  if (String(input?.nextState || "") === "captured" &&
      (source.startsWith("blob:") || source.startsWith("data:image/"))) {
    const observedAt = Number(input?.nextCapturedAt || 0);
    return {state:"captured",source,capturedAt:
      Number.isFinite(observedAt) && observedAt > 0 && observedAt <= now ? observedAt : now,label:""};
  }
  return {state:"placeholder",source:"",capturedAt:0,label:""};
}

function monitorWindowFallbackDataUri(item = null) {
  const policy = bwmUiLayoutControl?.read?.()?.captureFallback;
  if (policy?.mode !== "legacy") {
    // Transparent canvas keeps exact HWND geometry and drag target.
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270"><rect x="8" y="8" width="214" height="52" rx="8" fill="#1b2431" fill-opacity=".94" stroke="#56687e"/><rect x="19" y="19" width="26" height="28" rx="4" fill="#3b82f6"/><path d="M26 28h13m-13 6h13m-13 6h10" stroke="#fff" stroke-width="2"/><text x="55" y="39" fill="#e8edf5" font-family="Segoe UI,sans-serif" font-size="17">Preview unavailable</text></svg>';
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }
  const title = String(item?.title || "창 미리보기").trim() || "창 미리보기";
  const label = title.length > 18 ? `${title.slice(0, 17)}…` : title;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="270" viewBox="0 0 480 270"><rect width="480" height="270" fill="#161a20"/><rect x="18" y="18" width="444" height="234" rx="14" fill="#202630" stroke="#475160" stroke-width="2"/><rect x="42" y="52" width="46" height="46" rx="8" fill="#3b82f6"/><path d="M53 65h24v5H53zm0 10h24v5H53zm0 10h16v5H53z" fill="#fff"/><text x="106" y="82" fill="#e8edf5" font-family="Segoe UI, sans-serif" font-size="22">${label.replace(/[&<>]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;"})[character])}</text><text x="42" y="132" fill="#9aa6b5" font-family="Segoe UI, sans-serif" font-size="16">미리보기 대신 앱 정보 표시</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

async function captureDesktopFrame(desktopId, profile = "main") {
  if (!MONITOR_FEATURE_DESKTOP_VISUALS_ENABLED) return null;

  if (!desktopId) return null;

  const hostHwnd = String(monitorDesktopState.hostWindowHwnd || "").trim();

  if (!/^\d+$/.test(hostHwnd) || hostHwnd === "0") return null;

  const hasHostHwnd = true;

  const generation = monitorDesktopFrameGeneration(desktopId);

  const cacheKey = `${generation}:${desktopId}:${profile}:${hasHostHwnd ? hostHwnd : "ambiguous-host"}`;

  const cached = monitorFrameCache.get(cacheKey);
  if(cached&&Date.now()-Number(cached.at||0)<=MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS)return cached;
  if(cached)monitorFrameCache.delete(cacheKey);

  if (monitorFrameInflight.has(cacheKey)) return monitorFrameInflight.get(cacheKey);

  const job = (async () => {

    const actMeta = monitorActDesktopVisualForDesktop(desktopId);

    // Window geometry/minimize state must come from the live Windows observer.

    // ACT metadata is still useful for identity, but stale ACT rects must never

    // override the actual desktop position shown in the preview/thumbs.

    const nativeMeta = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindows", desktopId, hostWindowHwnd: hostHwnd }

      : { type: "getDesktopWindows", desktopId }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    const meta = nativeMeta?.ok ? nativeMeta : actMeta;

    if (!meta?.ok) return null;

    const actByHwnd = new Map((Array.isArray(actMeta?.windows) ? actMeta.windows : []).map((item) => [String(item?.hwnd || ""), item]));

    const popupRuntime = await chrome.runtime.sendMessage({ type:"monitor-list-popup-runtime" }).catch(() => null);
    const monitorPopupWindows = (Array.isArray(popupRuntime?.windows) ? popupRuntime.windows : [])
      .filter((item) => String(item?.desktopId || "") === String(desktopId));
    const windowRows = [...(Array.isArray(meta.windows) ? meta.windows : []), ...monitorPopupWindows];
    const windows = [...new Map(windowRows.map((item) => [String(item?.hwnd || ""), item])).values()]

      .map((item) => ({ ...item, conversationKey: String(item?.conversationKey || actByHwnd.get(String(item?.hwnd || ""))?.conversationKey || "") }));

    const handleSnapshot = await monitorNative(hasHostHwnd

      ? { type: "getDesktopWindowHandles", desktopId, hostWindowHwnd: hostHwnd, includeMonitorWindows: true }

      : { type: "getDesktopWindowHandles", desktopId, includeMonitorWindows: true }).catch(() => null);

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;
    // Only a successful native snapshot can add/remove physical windows.
    const handlesConfirmed = handleSnapshot?.ok === true && Array.isArray(handleSnapshot.windows);
    const handleByHwnd = new Map((handlesConfirmed ? handleSnapshot.windows : []).map((item) => [String(item?.hwnd || ""), item]));
    const previousByHwnd = new Map(windows.map((item) => [String(item?.hwnd || ""), item]));
    const currentWindows = handlesConfirmed
      ? [...handleByHwnd.values()].filter((item) => /^[0-9]+$/.test(String(item?.hwnd || "")) && String(item.hwnd) !== "0" && (item.visible !== false || Boolean(item.iconic)))
      : windows;
    const liveWindows = currentWindows.map((item) => {
      const hwnd = String(item?.hwnd || "");
      const previous = previousByHwnd.get(hwnd);
      return { ...previous, ...item, conversationKey: String(item?.conversationKey || previous?.conversationKey || actByHwnd.get(hwnd)?.conversationKey || "") };
    });
    rememberMonitorDesktopWindows(desktopId, liveWindows);
    await refreshMonitorBctThumbnailProjectionForDesktop(desktopId);

    // Physical window existence/geometry/Z-order is native Windows truth. ACT only enriches identity.

    // Capture is optional visual content and must never decide whether a window exists in Monitor.

    const visibleWindows = liveWindows.filter((item) => !Boolean(item?.iconic));

    // Reconcile rendered windows against the current Native HWND snapshot. A minimized

    // window is still present in liveWindows, while a closed/destroyed window is absent.

    const liveHwndSet = new Set(liveWindows.map((item) => String(item?.hwnd || "")).filter(Boolean));

    const desktopTile = [...monitorDesktopThumbs.children].find((item) => String(item.dataset.desktopId || "") === String(desktopId));

    const desktopVisual = desktopTile?.querySelector(".monitor-desktop-thumb-visual");

    if (desktopVisual) {

      for (const stale of [...desktopVisual.querySelectorAll(".monitor-desktop-thumb-window")]) {

        const staleHwnd = String(stale.dataset.hwnd || "");

        if (!staleHwnd || liveHwndSet.has(staleHwnd)) continue;

        removeMonitorV2Window(staleHwnd);

        monitorThumbnailService.dispose(staleHwnd);

      }

    }

    const items = [...visibleWindows].sort((a,b)=>Number(b.z||0)-Number(a.z||0));

    // Coverage is complete; concurrency is bounded inside ThumbnailService.
    // Placeholder frames remain visible only while a capture is unavailable.
    const captureItems = MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED
      ? items.filter(monitorWindowCanRefreshPixels)
      : [];

    const frames = items.map((item) => ({
              capturedAt: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? Date.now() : 0,

      item,

      dataUri: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? String(item.frozenDataUri) : monitorWindowFallbackDataUri(item),

      captureState: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "captured" : "placeholder",

      physicalSource: monitorWindowUsesFrozenCapture(item) && String(item?.frozenDataUri || "").startsWith("data:image/") ? "monitor-frozen" : "windows-native",

      semanticSource: item?.conversationKey ? "act-enriched" : "none"

    }));

    const frameByHwnd = new Map(frames.map((entry) => [String(entry.item?.hwnd || ""), entry]));

    if (profile === "thumb") {

      // Desktop cards show real window pixels. Small captures plus a short HWND cache

      // keep ACT identity/state polling responsive; the label SVG is fallback only.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item?.hwnd || "");

        let dataUri = "";

        dataUri = await monitorGetWindowCapture(hwnd, "thumb");

        if (!dataUri) continue;

        const frameEntry = frameByHwnd.get(hwnd);

        if(frameEntry){
  const meta=monitorWindowCaptureService("thumb").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

      }

    } else {

      // Large selected preview keeps the real pixels. Native messaging is serialized,

      // so capture one window at a time to avoid starving identity/selection requests.

      for (const item of captureItems) {
        if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

        const hwnd = String(item.hwnd || "");

        const dataUri = await monitorGetWindowCapture(hwnd, "preview");
        if (dataUri) {

          const frameEntry = frameByHwnd.get(hwnd);

          if(frameEntry){
  const meta=monitorWindowCaptureService("preview").getCached(hwnd)?.meta;
  if(monitorCaptureMatchesCurrentWindow(meta?.captureTitle,item?.title,meta?.capturedAt)){
    frameEntry.dataUri=dataUri;frameEntry.captureState="captured";
    frameEntry.capturedAt=Number(meta.capturedAt);frameEntry.captureTitle=String(meta.captureTitle);
  }
}

        }

      }

    }

    const observedWindowHwnds = [...new Set([

      ...visibleWindows.map((item) => String(item?.hwnd || "")),

      ...(handlesConfirmed ? handleSnapshot.windows : [])

        .filter((item) => Boolean(item?.visible) && !Boolean(item?.iconic))

        .map((item) => String(item?.hwnd || ""))

    ].filter(Boolean))];

    const frame = { at: Date.now(), meta: { ...meta, windows: visibleWindows, observedWindowHwnds }, frames };

    if (generation !== monitorDesktopFrameGeneration(desktopId)) return null;

    monitorFrameCache.set(cacheKey, frame);
    while (monitorFrameCache.size > MONITOR_FRAME_CACHE_LIMIT) {
      const oldestKey = monitorFrameCache.keys().next().value;
      if (!oldestKey) break;
      monitorFrameCache.delete(oldestKey);
    }

    return frame;

  })().finally(() => monitorFrameInflight.delete(cacheKey));

  monitorFrameInflight.set(cacheKey, job);

  return job;

}

function syncMonitorPauseOverlay(img, hwnd) {

  if (!img?.parentElement) return;

  const key = String(hwnd || "");

  let overlay = [...img.parentElement.querySelectorAll(".monitor-window-pause-overlay")].find((node)=>node.dataset.hwnd===key);

  const paused = img.classList.contains("monitor-window-paused");
  const userAttentionDetail = monitorHwndUserAttentionDetail(key, monitorLastAiState);
  const conversationKey=monitorVisualConversationForHwnd(key,monitorLastAiState);
  const completionDetail=monitorChatAlertDetail(conversationKey);

  const activity=monitorHwndIsGenerating(key, monitorLastAiState) ? "play" : (completionDetail?.activity || (paused ? "pause" : ""));
  const warning=userAttentionDetail?.warning === true || completionDetail?.warning === true;
  if (!activity && !warning) { overlay?.remove(); return; }

  if (!overlay) { overlay=document.createElement("span"); overlay.className="monitor-window-pause-overlay"; overlay.dataset.hwnd=key; img.parentElement.append(overlay); }

  const detail=userAttentionDetail||completionDetail||{tone:"general",label:"채팅 작업 완료"};

  delete overlay.dataset.symbol; overlay.title=detail.label;
  globalThis.MonitorStatusIcon?.render?.(overlay,{activity,warning});

  for(const tone of ["general","success","failure","review","question","input","action"]) overlay.classList.remove(`monitor-alert-tone-${tone}`);

  overlay.classList.add(`monitor-alert-tone-${detail.tone}`);

  overlay.classList.toggle("monitor-window-pause-overlay-thumb", img.classList.contains("monitor-desktop-thumb-window"));

  overlay.style.left=img.style.left; overlay.style.top=img.style.top; overlay.style.width=img.style.width; overlay.style.height=img.style.height;

  const z=Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)); overlay.style.zIndex=String(z);

}

function monitorAgeIdentityForWorkerGroup(members, state = monitorLastAiState) {

  const list=(Array.isArray(members)?members:[]).filter((worker)=>worker&&String(worker?.conversation_key||"").trim());

  if(!list.length)return { worker:null, conversationKey:"", profileId:"", ageing:0, nodeNumber:0 };

  const ranked=list.map((worker,index)=>{

    const physical=monitorCanonicalPhysicalLocation(worker,state);

    const label=String(physical?.label||resolveStableMonitorLocation(worker,state)||"").trim().toUpperCase();

    const match=/^D\d+-(\d+)$/.exec(label);

    return {worker,index,nodeNumber:match?Number(match[1]):Number.MAX_SAFE_INTEGER};

  }).sort((a,b)=>a.nodeNumber-b.nodeNumber||a.index-b.index);

  const picked=ranked[0]; const worker=picked?.worker||list[0];

  const conversationKey=String(worker?.conversation_key||"").trim();

  const profileId=String(worker?.profile_id||"").toUpperCase();

  const ghost=conversationKey?monitorGhostCache.get(conversationKey):null;

  return { worker, conversationKey, profileId, ageing:ghost?monitorGhostAgeing(ghost):0, nodeNumber:Number.isFinite(picked?.nodeNumber)&&picked.nodeNumber<Number.MAX_SAFE_INTEGER?picked.nodeNumber:0 };

}

function monitorAgeIdentityForHwnd(hwnd, state = monitorLastAiState) {

  const key=String(hwnd||"").trim(); if(!key||!state)return { worker:null, conversationKey:"", profileId:"", ageing:0, nodeNumber:0 };

  const workers=monitorWorkersForState(state).filter((worker)=>{

    if(classifyMonitorWorker(worker)!=="chatgpt"||!String(worker?.conversation_key||"").trim())return false;

    const location=monitorEndpointLocation(worker,state);

    return String(monitorResolvedWorkerHwnd(worker,state,location)||"").trim()===key;

  });

  return monitorAgeIdentityForWorkerGroup(workers,state);

}

function monitorObservedDesktopForHwnd(hwnd, state = monitorLastAiState) {
  const key=String(hwnd||"").trim();
  if(!key||!state)return null;
  const observer=state?.node_state?.observer||null;
  if(String(observer?.source||"")==="ACT_NATIVE_OBSERVER"){
    const row=(Array.isArray(observer?.windows)?observer.windows:[]).find((item)=>String(item?.hwnd||"").trim()===key);
    if(row){
      const desktopId=String(row?.desktop_id||"").trim();
      const desktopRow=(Array.isArray(observer?.desktops)?observer.desktops:[]).find((item)=>String(item?.desktop_id||"").trim()===desktopId);
      const desktop=Number(desktopRow?.index)||0;
      if(desktopId)return {desktopId,desktop,authority:"ACT_NATIVE_OBSERVER"};
    }
  }
  const remembered=monitorWindowDesktopLocations.get(key);
  const desktopId=String(remembered?.desktopId||"").trim();
  if(!desktopId)return null;
  const desktop=monitorDesktopState.desktopIds.indexOf(desktopId)+1;
  return {desktopId,desktop:desktop>0?desktop:0,authority:"MONITOR_NATIVE_EVENT"};
}

function monitorActNodeNumbersForHwnd(hwnd, state = monitorLastAiState) {
  const key=String(hwnd||"").trim();
  if(!key||!state)return [];
  if(String(state?.node_state?.observer?.source||"")!=="ACT_NATIVE_OBSERVER") return [];
  const observed=monitorObservedDesktopForHwnd(key,state);
  if(!observed)return [];
  const numbers=new Set();
  const actNodes=Array.isArray(state?.node_state?.nodes)?state.node_state.nodes:[];
  for(const node of actNodes){
    if(String(node?.identity_authority||"")!=="ACT_TAB_CHAT") continue;
    if(String(node?.hwnd||"").trim()!==key) continue;
    const parts=monitorNodeIdentityParts(node?.node_label,node?.desktop_id);
    if(!parts.nodeNumber)continue;
    const slot=parts.nodeNumber;
    // Thumbnail node badges follow ACT_TAB_CHAT identity + exact HWND.
    // Desktop metadata may lag a move and must not hide an otherwise valid node number.
    if(Number.isInteger(slot)&&slot>0)numbers.add(slot);
  }
  return [...numbers].sort((a,b)=>a-b);
}

function monitorBadgeNodeNumbersForHwnd(hwnd, state = monitorLastAiState) {
  // BCT/RCC owns conversation labels, and Native/ACT maps the physical HWND.
  // A missing HWND hides only the thumbnail overlay, never the node list.
  if (Array.isArray(monitorBctWindowNodesCache)) {
    const matched = monitorBctWindowNodesCache.filter((node) =>
      monitorDisplayHwndForBrowserWindowId(node.windowId, state, node.instanceId, node.sessionId) === String(hwnd));
    return [...new Set(matched.map((node) => {
      const match = /^N(\d+)$/.exec(String(node.nodeLabel || "").trim());
      return match ? Number(match[1]) : 0;
    }).filter((n) => Number.isSafeInteger(n) && n > 0))];
  }
  return monitorActNodeNumbersForHwnd(hwnd, state);
}

function syncMonitorDesktopNumberBadge(img, hwnd) {

  if (!img?.parentElement) return;

  const key=String(hwnd||""), state=monitorLastAiState;

  let badge=[...img.parentElement.querySelectorAll(".monitor-window-desktop-badge")].find((node)=>node.dataset.hwnd===key);
  if(img.classList.contains("monitor-desktop-thumb-window")){
    badge?.remove();
    // Render once after the full Native frame is reconciled. Re-entering the
    // renderer here used to apply the window's physical offset to its child
    // badge a second time and made the result depend on image iteration order.
    return;
  }

  if(!state){badge?.remove();return;}

  const unique=monitorBadgeNodeNumbersForHwnd(key,state);

  if(!unique.length){ badge?.remove(); return; }

  if(!badge){badge=document.createElement("span");badge.className="monitor-node-number-badge monitor-window-desktop-badge";badge.dataset.hwnd=key;img.parentElement.append(badge);}

  badge.textContent=unique.length>1?unique.join("/"):String(unique[0]);

  badge.title=unique.length>1?`ACT 탭 노드 ${unique.join(" / ")}`:`ACT 노드 ${unique[0]}`;

  badge.style.left=img.style.left;badge.style.top=img.style.top;badge.style.zIndex=String(Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)));

}

function syncMonitorNonChatCountdown(img, hwnd, now = Date.now()) {
  // Non-ChatGPT Chrome windows remain filtered by the grace-state logic, but
  // they are not Monitor nodes and must not receive a visible countdown.
  if (img?.parentElement) {
    img.parentElement.querySelectorAll(".monitor-window-non-chat-countdown").forEach((node) => node.remove());
  }
  return;

  if (!img?.parentElement) return;

  const key=String(hwnd||"");

  let badge=[...img.parentElement.querySelectorAll(".monitor-window-non-chat-countdown")].find((node)=>node.dataset.hwnd===key);

  if(monitorHwndHasOpenChatEndpoint(key)){monitorNonChatStartedByHwnd.delete(key);const loc=monitorWindowDesktopLocations.get(key);if(loc)loc.nonChatSince=0;badge?.remove();return;}

  const since=Number(monitorNonChatStartedByHwnd.get(key)||monitorWindowDesktopLocations.get(key)?.nonChatSince||0);

  const remaining=since>0 ? Math.max(0, MONITOR_NON_CHAT_GRACE_MS-(now-since)) : 0;

  if(!remaining){badge?.remove();return;}

  if(!badge){badge=document.createElement("span");badge.className="monitor-window-non-chat-countdown";badge.dataset.hwnd=key;img.parentElement.append(badge);}

  badge.textContent=`${Math.max(1,Math.ceil(remaining/1000))}s`;

  badge.title="ChatGPT가 아닌 페이지 · Monitor 연결 해제까지 남은 시간";

  badge.style.left=img.style.left;badge.style.top=img.style.top;badge.style.width=img.style.width;badge.style.height=img.style.height;

  badge.style.zIndex=String(Math.max(1, Number(img.style.zIndex || img.dataset.nativeZIndex || 1)));

  badge.classList.toggle("monitor-window-non-chat-countdown-thumb",img.classList.contains("monitor-desktop-thumb-window"));

}

function syncMonitorStatusLayer(img, hwnd) {

  if (!img?.parentElement) return;

  const isThumb=img.classList.contains("monitor-desktop-thumb-window");

  const isPreview=img.classList.contains("monitor-window-preview");

  if (!isThumb && !isPreview) return;

  const key=String(hwnd||"");

  const surface=isThumb?"thumb":"preview";

  const parent=img.parentElement;

  let layer=[...parent.querySelectorAll(".monitor-window-status-layer")].find((node)=>node.dataset.hwnd===key&&node.dataset.surface===surface);

  if(!layer){

    layer=document.createElement("span");

    layer.className="monitor-window-status-layer";

    layer.dataset.hwnd=key;

    layer.dataset.surface=surface;

    layer.innerHTML='<span class="monitor-status-age"></span><span class="monitor-status-group"></span><span class="monitor-status-working"></span><span class="monitor-status-role"></span><span class="monitor-status-hover"></span><span class="monitor-status-selection"></span>';

  }

  if(img.nextElementSibling!==layer) parent.insertBefore(layer,img.nextSibling);

  layer.style.left=img.style.left;

  layer.style.top=img.style.top;

  layer.style.width=img.style.width;

  layer.style.height=img.style.height;

  const nativeZ=Math.max(1,Number(img.style.zIndex||img.dataset.nativeZIndex||1));

  layer.style.zIndex=String(nativeZ);

  const hue=img.style.getPropertyValue("--monitor-conversation-hue");

  if(hue) layer.style.setProperty("--monitor-conversation-hue",hue); else layer.style.removeProperty("--monitor-conversation-hue");

  const ageIdentity=monitorAgeIdentityForHwnd(key,monitorLastAiState);

  const age=Math.max(0,Math.min(100,Number(ageIdentity.ageing)||0));

  layer.style.setProperty("--monitor-window-age",`${age}%`);

  layer.classList.toggle("monitor-profile-google",ageIdentity.profileId==="GOOGLE");

  layer.classList.toggle("monitor-profile-naver",ageIdentity.profileId==="NAVER");

}

function reconcileFrame(container, frame, className) {

  if (!frame?.meta) return;

  const existing = new Map([...container.querySelectorAll(`.${className}`)].map(img => [img.dataset.hwnd, img]));
  const previousAgeLabels = new Map([...container.querySelectorAll(".monitor-window-capture-age-label")].map(label => [label.dataset.hwnd, label]));

  const observedSource = Array.isArray(frame.meta?.observedWindowHwnds) ? frame.meta.observedWindowHwnds : (Array.isArray(frame.meta?.windows) ? frame.meta.windows.map((item)=>item?.hwnd) : []);

  const observedHwnds = new Set(observedSource.map((item)=>String(item||"")).filter(Boolean));

  const vw = Math.max(1, Number(frame.meta.previewVirtualWidth ?? frame.meta.virtualWidth) || 1), vh = Math.max(1, Number(frame.meta.previewVirtualHeight ?? frame.meta.virtualHeight) || 1);

  const vl = Number(frame.meta.previewVirtualLeft ?? frame.meta.virtualLeft ?? 0), vt = Number(frame.meta.previewVirtualTop ?? frame.meta.virtualTop ?? 0);

  container.dataset.monitorPreviewVirtualLeft = String(vl);
  container.dataset.monitorPreviewVirtualTop = String(vt);
  container.dataset.monitorPreviewVirtualWidth = String(vw);
  container.dataset.monitorPreviewVirtualHeight = String(vh);

  for (const entry of frame.frames) {

    const key = String(entry.item.hwnd || "");

    let img = existing.get(key);

    if (!img) {

      img = document.createElement("img"); img.className = className; img.dataset.hwnd = key; img.alt = ""; container.append(img);

    }

    img.title = entry.item.title || "";

    img.dataset.physicalSource = entry.physicalSource || "windows-native";

    img.dataset.semanticSource = entry.semanticSource || (entry.item?.conversationKey ? "act-enriched" : "none");

    const captureTitle=String(entry.item?.title||"");
    const frozen=entry.physicalSource==="monitor-frozen";
    const freshEntry=frozen||monitorCaptureMatchesCurrentWindow(entry.captureTitle,captureTitle,entry.capturedAt);
    const nextCaptureState=freshEntry?(entry.captureState||"placeholder"):"placeholder";
    const previousFresh=monitorCaptureMatchesCurrentWindow(img.dataset.monitorCaptureTitle,captureTitle,img.dataset.monitorCapturedAt);
    const couldKeep=previousFresh&&(
      monitorShouldKeepExistingCapture(img.dataset.captureState,img.src,nextCaptureState)
      ||["held","stale"].includes(img.dataset.captureState)
    );
    const captureView = monitorChooseCaptureView({
      previousState: img.dataset.captureState,
      previousSource: couldKeep ? img.src : "",
      previousCapturedAt: Number(img.dataset.monitorCapturedAt || 0),
      nextState: nextCaptureState, nextSource: nextCaptureState==="captured"?entry.dataUri:"",
      nextCapturedAt: nextCaptureState==="captured"?Number(entry.capturedAt||Date.now()):0, now: Date.now()
    }, bwmUiLayoutControl?.read?.()?.captureFallback);
    img.dataset.captureState = captureView.state;
    img.dataset.monitorCapturedAt = String(captureView.capturedAt);
    if(captureView.state==="captured"&&nextCaptureState==="captured")img.dataset.monitorCaptureTitle=captureTitle;
    else if(!couldKeep)delete img.dataset.monitorCaptureTitle;
    img.dataset.captureFailureReason = nextCaptureState === "captured" ? "" :
      Number(entry.item?.cloaked || 0) !== 0 ? "CLOAKED" :
      !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED ? "CAPTURE_DISABLED" : "WGC_UNAVAILABLE";
    img.classList.toggle("monitor-window-capture-placeholder", captureView.state === "placeholder");
    img.classList.toggle("monitor-window-capture-stale", captureView.state === "stale");

    // Captured pixels are independent from ACT/node decoration. Identity delay may hide

    // a badge temporarily, but must never suppress the browser image itself.

    img.style.left = `${((Number(entry.item.left) - vl) / vw) * 100}%`;

    img.style.top = `${((Number(entry.item.top) - vt) / vh) * 100}%`;

    img.style.width = `${(Number(entry.item.width) / vw) * 100}%`; img.style.height = `${(Number(entry.item.height) / vh) * 100}%`;

    const nativeZ = Math.max(0, Number(entry.item.z) || 0);

    const nativeZIndex = String(10000 - Math.min(nativeZ, 9999));

    img.dataset.nativeZIndex = nativeZIndex;

    img.style.setProperty("z-index", nativeZIndex, "important");

    const renderedSource = captureView.state === "placeholder" && !captureView.source ? monitorWindowFallbackDataUri(entry.item) : captureView.source;
    if (img.src !== renderedSource) img.src = renderedSource;
    img.title = captureView.label ? String(entry.item.title || "") + " - " + captureView.label : String(entry.item.title || "");
    let ageLabel = previousAgeLabels.get(key);
    if (captureView.label) {
      if (!ageLabel) {
        ageLabel = document.createElement("span");
        ageLabel.className = "monitor-window-capture-age-label";
        ageLabel.dataset.hwnd = key;
        container.append(ageLabel);
      }
      ageLabel.textContent = captureView.label;
      ageLabel.style.left = "calc(" + img.style.left + " + 3px)";
      ageLabel.style.top = "calc(" + img.style.top + " + " + img.style.height + " - 20px)";
      ageLabel.style.zIndex = String(Number(nativeZIndex) + 1);
    } else {
      ageLabel?.remove();
    }
    previousAgeLabels.delete(key);

    try {

      applyPersistentMonitorRoleClass(img, key);

      img.classList.toggle("monitor-window-row-hovered", Boolean(monitorHoveredHwnd) && key === monitorHoveredHwnd && !monitorSelectedHwnds.has(key));

      syncMonitorStatusLayer(img, key); syncMonitorPauseOverlay(img, key);

      syncMonitorDesktopNumberBadge(img, key); syncMonitorNonChatCountdown(img, key);

    } catch (error) { console.warn("DesktopWindow Monitor frame decoration delayed", key, error); }

    if (!img.dataset.monitorDragBound) {

      img.dataset.monitorDragBound = "1";

      img.draggable = false;

      img.addEventListener("pointerdown", beginMonitorWindowPointerDrag);

    }

    existing.delete(key);

  }

  for (const stale of existing.values()) {

    const key=String(stale.dataset.hwnd||"");

    // A transient WGC snapshot failure is not a window disappearance. Keep the last good

    // pixels and decorations while Native still reports the HWND on this desktop.

    if(observedHwnds.has(key)){applyPersistentMonitorRoleClass(stale,key);syncMonitorPauseOverlay(stale,key);syncMonitorDesktopNumberBadge(stale,key);syncMonitorNonChatCountdown(stale,key);continue;}

    stale.parentElement?.querySelectorAll(".monitor-window-status-layer, .monitor-window-pause-overlay, .monitor-window-desktop-badge, .monitor-window-non-chat-countdown").forEach((node)=>{if(node.dataset.hwnd===key)node.remove();});

    stale.remove();

  }

  for (const unownedAgeLabel of previousAgeLabels.values()) { if (!observedHwnds.has(String(unownedAgeLabel.dataset.hwnd || ""))) unownedAgeLabel.remove(); }
if (monitorSelectedHwnds.size) applyMonitorWindowHighlight(monitorHighlightedHwnd, { preserve: true });

  scheduleMonitorHoverRecheck();

}

