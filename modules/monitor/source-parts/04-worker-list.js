function monitorGhostValidLease(ghost, state, now = Date.now()) {

  const leases = Array.isArray(state?.task_leases) ? state.task_leases : []; const taskId = String(ghost?.task_id || ""); const workerId = String(ghost?.worker_id || "").trim().toUpperCase();

  return leases.some((lease) => monitorGhostTime(lease?.expires_at) > now && (taskId ? String(lease?.task_id || "") === taskId : Boolean(workerId) && String(lease?.owner || "").trim().toUpperCase() === workerId));

}

function monitorGhostProtected(ghost) {

  const role=String(ghost?.role || "").toUpperCase(), status=String(ghost?.task_status || ghost?.work_status || "").toUpperCase();

  return ["ORCHESTRATOR","COORDINATOR_1","COORDINATOR_2"].includes(role) || ["RUNNING","NEEDS_REVIEW","FAILED","FAILURE","RECOVERY","RECOVERY_PENDING","BLOCKED"].includes(status);

}

function monitorGhostCanAutoHide(ghost, state, now = Date.now()) {

  if (monitorGhostProtected(ghost) || monitorGhostValidLease(ghost,state,now) || monitorGhostArchiveAgeing(ghost) < 80) return false;

  const status=String(ghost?.task_status || ghost?.work_status || "").toUpperCase(); if (!["SUCCEEDED","COMPLETED","COMPLETE","DONE","IDLE","AVAILABLE"].includes(status)) return false;

  const idleSince=Number(ghost?.completed_or_idle_ms || 0); return idleSince > 0 && now-idleSince >= 24*60*60*1000;

}

let monitorGhostPersistTimer = 0;

function monitorGhostPersist(immediate = false) {

  if (!monitorGhostStorageReady) return;

  const write = () => { monitorGhostPersistTimer = 0; const cache=[...monitorGhostCache.values()].sort((a,b)=>Number(b?.last_activity_ms||0)-Number(a?.last_activity_ms||0)).slice(0,MONITOR_GHOST_CACHE_MAX); chrome.storage.local.set({ [MONITOR_GHOST_CACHE_KEY]:cache, [MONITOR_GHOST_HIDDEN_KEY]:[...monitorHiddenGhosts].slice(0,MONITOR_GHOST_CACHE_MAX) }); };

  if (immediate) { if (monitorGhostPersistTimer) clearTimeout(monitorGhostPersistTimer); write(); return; }

  if (!monitorGhostPersistTimer) monitorGhostPersistTimer = setTimeout(write, 5000);

}

function monitorClosedConversationRecoveryItems(state = null) {

  const byKey=new Map();

  for(const g of monitorGhostCache.values()){const key=String(g?.conversation_key||"").trim();if(!g.open&&key&&!monitorTrashedConversationKeys.has(key))byKey.set(key,{...g,recovery_source:"일반 종료"});}

  const endpoints=Array.isArray(state?.endpoints)?state.endpoints:[]; let sharedChanged=false;

  const sharedItems=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).map((snap)=>{

    const key=String(snap?.conversation_key||"").trim(); if(!key)return snap; const ep=endpoints.find((x)=>String(x?.conversation_key||"").trim()===key)||null;

    const firstSeen=Number(monitorGhostTime(ep?.first_seen_at)||snap?.first_seen_ms||0); const closedAt=Number(monitorGhostTime(ep?.closed_at)||snap?.closed_at_ms||snap?.captured_at_ms||monitorRebootSnapshot?.captured_at_ms||0);

    if(firstSeen!==Number(snap?.first_seen_ms||0)||closedAt!==Number(snap?.closed_at_ms||0))sharedChanged=true;

    return {...snap,first_seen_ms:firstSeen,closed_at_ms:closedAt};

  });

  if(sharedChanged){monitorRebootSnapshot={...monitorRebootSnapshot,items:sharedItems};chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot});monitorPublishSharedRebootSnapshot();}

  const openKeys=new Set(endpoints.filter((x)=>String(x?.presence_state||"").toUpperCase()==="OPEN").map((x)=>String(x?.conversation_key||"").trim()).filter(Boolean));

  for(const snap of sharedItems){const key=String(snap?.conversation_key||"").trim();if(!key||monitorTrashedConversationKeys.has(key)||openKeys.has(key))continue;byKey.set(key,{...snap,open:false,recovery_source:"재부팅 이전"});}

  return [...byKey.values()].sort((a,b)=>{const ar=a.recovery_source==="재부팅 이전",br=b.recovery_source==="재부팅 이전";if(ar&&br)return Number(a.desktop||999)-Number(b.desktop||999)||Number(a.slot||999)-Number(b.slot||999);if(ar!==br)return ar?-1:1;return Number(b.closed_at_ms||b.captured_at_ms||0)-Number(a.closed_at_ms||a.captured_at_ms||0);});

}

function monitorClosedConversationPreviousLocation(ghost) {

  const d=Number(ghost?.desktop), s=Number(ghost?.slot);

  return Number.isInteger(d)&&d>0&&Number.isInteger(s)&&s>0 ? `D${d}-${s}` : "알 수 없음";

}

function monitorClosedConversationContextTitle(ghost) {

  const key=String(ghost?.conversation_key||"").trim(); const rec=monitorContextTitleRecord(key);

  const titles=[]; const add=(value)=>{const text=monitorContextTitlePart(value);if(text&&!titles.includes(text))titles.push(text);};

  if(rec?.manual_locked) add(rec?.manual_title);

  add(rec?.context_title);

  const recoveryCandidate=monitorContextTitlePart(ghost?.meaningful_title||ghost?.task_title||"");

  if(key && !rec?.manual_locked && !String(rec?.context_title||"").trim() && recoveryCandidate && !/^D\d+-\d+$/i.test(recoveryCandidate) && recoveryCandidate!=="알 수 없음") {

    const promoted={...rec,context_title:recoveryCandidate,title_source:"RECOVERY",title_updated_ms:Date.now(),manual_locked:false};

    monitorContextTitles.set(key,promoted); monitorPublishSharedContextTitle(key,promoted);

  }

  add(recoveryCandidate); add(ghost?.task_title);

  for(const item of [...(Array.isArray(ghost?.history)?ghost.history:[])].reverse()) add(item?.text);

  add(ghost?.title); return monitorGhostBoundText(titles.slice(0,3).join(" · ")||key.slice(0,8),96);

}

function renderMonitorClosedConversationRecoveryPanel(state) {

  const panel=document.createElement("div"); panel.className="monitor-closed-conversation-panel monitor-trash-recovery-panel";

  const items=monitorClosedConversationRecoveryItems(state);

  const makeHeader=(label,count,onClear,extras=[])=>{const head=document.createElement("div");head.className="monitor-trash-pane-header";const title=document.createElement("strong");title.textContent=`${label} (${count})`;const actions=document.createElement("span");actions.className="monitor-trash-pane-actions";for(const button of extras)if(button)actions.append(button);const clear=document.createElement("button");clear.type="button";clear.className="monitor-trash-clear-all";clear.textContent="다 비움";clear.disabled=!count;clear.addEventListener("click",(e)=>{e.stopPropagation();if(confirm(`${label} 항목을 모두 비울까요?`))onClear();});actions.append(clear);head.append(title,actions);return head;};

  const recoveryWorkers=monitorWorkersForState(state||{});

  const recoveryWorkerByKey=new Map(recoveryWorkers.map((worker)=>[String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim(),worker]).filter(([key])=>key));

  const recoveryEndpoints=Array.isArray(state?.endpoints)?state.endpoints:[];

  const recoveryNodeStatus=(key,record=null)=>{

    key=String(key||"").trim();

    const endpoint=recoveryEndpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key)||null;

    const open=String(endpoint?.presence_state||"").toUpperCase()==="OPEN";

    const worker=recoveryWorkerByKey.get(key)||null;

    const work=String(worker?resolveWorkerWorkState(worker,state):(record?.work_status||record?.task_status||"")).trim().toLowerCase();

    if(["running","working","busy","executing","in_progress"].includes(work))return {label:"처리 중",tone:"processing"};

    if(["waiting_resource","waiting","paused","queued","pending"].includes(work))return {label:"대기 중",tone:"waiting"};

    if(["needs_review","failed","failure","blocked","recovery","recovery_pending","degraded"].includes(work))return {label:"확인 필요",tone:"attention"};

    if(["succeeded","completed","complete","done"].includes(work))return {label:"완료",tone:"complete"};

    if(open)return {label:"활동 중",tone:"active"};

    return {label:"닫힘",tone:"closed"};

  };

  const appendRecoveryStatus=(row,key,record=null)=>{const status=recoveryNodeStatus(key,record);const badge=document.createElement("span");badge.className=`monitor-trash-node-status monitor-trash-node-status-${status.tone}`;badge.textContent=status.label;badge.title=`현재 상태: ${status.label}`;row.append(badge);};

  const noteRecords=[...monitorTrashedNotes.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const notePane=document.createElement("section");notePane.className="monitor-trash-pane monitor-trash-note-pane";notePane.append(makeHeader("삭제된 메모",noteRecords.length,clearMonitorTrashedNotes));const noteScroll=document.createElement("div");noteScroll.className="monitor-trash-pane-scroll";

  if(!noteRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";noteScroll.append(empty);}else for(const note of noteRecords){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-note-row";const info=document.createElement("div");info.className="monitor-closed-conversation-info monitor-trash-note-info";const noteTitle=document.createElement("strong");noteTitle.textContent=note.title||monitorNoteTitleFromText(note.body)||"메모";const lines=String(note.body||"").split(/\r?\n/);const firstLineIndex=lines.findIndex((line)=>line.trim());const notePreview=document.createElement("span");notePreview.textContent=(firstLineIndex>=0?lines.slice(firstLineIndex+1).join(" "):"").replace(/\s+/g," ").trim()||"내용 없음";info.append(noteTitle,notePreview);const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashedNote(note.id);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedNote(note.id);});row.append(info,restore,del);noteScroll.append(row);}notePane.append(noteScroll);panel.append(notePane);

  const renderTrashRows=(source,container)=>{const records=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")===source).sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));if(!records.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";container.append(empty);return;}for(const ghost of records){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-record-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost),at=Number(ghost?.trashed_at_ms||0),scope=String(ghost?.network_name||"미소속"),roles=Array.isArray(ghost?.role_tags)&&ghost.role_tags.length?` · ${ghost.role_tags.join(", ")}`:"";info.textContent=`${String(ghost?.node_label||"")} ${context} · ${scope}${roles} · ${location} · ${at?new Date(at).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"?"}`.trim();const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();restoreMonitorTrashRecord(ghost.conversation_key);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorTrashRecord(ghost.conversation_key),140);});row.append(info);if(source==="list")appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);container.append(row);}};

  const thumbRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")==="thumbnail");

  const desktopRecords=[...monitorTrashedDesktops.values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const thumbPane=document.createElement("section");thumbPane.className="monitor-trash-pane monitor-trash-thumbnail-pane";thumbPane.append(makeHeader("삭제된 데스크",thumbRecords.length+desktopRecords.length,clearMonitorThumbnailRecovery));const thumbScroll=document.createElement("div");thumbScroll.className="monitor-trash-pane-scroll";

  if(desktopRecords.length){

    const desktopGrid=document.createElement("div");desktopGrid.className="monitor-trash-desktop-grid";

    for(const item of desktopRecords){

      const card=document.createElement("div");card.className="monitor-trash-desktop-card";

      const visual=document.createElement("div");visual.className="monitor-trash-desktop-card-visual";

      const desktopNumber=Math.max(1,Number(item.desktop_number??item.desktopNumber??(Number(item.index||0)+1))||1);

      const badge=document.createElement("span");badge.className="monitor-desktop-number-badge monitor-trash-desktop-number";badge.textContent=`D${desktopNumber}`;

      const thumbnail=String(item.thumbnail||item.thumbnailDataUri||"");

      if(thumbnail){const image=document.createElement("img");image.className="monitor-trash-desktop-card-image";image.src=thumbnail;image.alt="";visual.append(image);}

      else{const placeholder=document.createElement("span");placeholder.className="monitor-trash-desktop-placeholder";placeholder.textContent="미리보기 없음";visual.append(placeholder);}

      visual.append(badge);

      const actions=document.createElement("div");actions.className="monitor-trash-desktop-card-actions";

      const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorTrashedDesktop(item.id,restore);});

      const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();deleteMonitorTrashedDesktop(item.id);});

      actions.append(restore,del);card.append(visual,actions);desktopGrid.append(card);

    }

    thumbScroll.append(desktopGrid);

  }

  renderTrashRows("thumbnail",thumbScroll);thumbPane.append(thumbScroll);

  let listRecords=[...monitorTrashRecords.values()].filter((x)=>String(x?.trash_source||"list")!=="thumbnail").sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const combined=[...listRecords.map((x)=>({kind:"trash",item:x,at:Number(x?.trashed_at_ms||0)})),...items.map((x)=>({kind:"closed",item:x,at:Number(x?.closed_at_ms||x?.captured_at_ms||0)}))].sort((a,b)=>b.at-a.at);

  const kept=combined.slice(0,20), dropped=combined.slice(20), keptKeys=new Set(kept.map((x)=>String(x.item?.conversation_key||"")));

  if(dropped.length){const dropKeys=new Set(dropped.map((x)=>String(x.item?.conversation_key||"")).filter(Boolean));for(const key of dropKeys){monitorTrashRecords.delete(key);monitorGhostCache.delete(key);monitorHiddenGhosts.delete(key);monitorTrashedConversationKeys.add(key);}monitorRebootSnapshot={...monitorRebootSnapshot,items:(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!dropKeys.has(String(x?.conversation_key||"")))};chrome.storage.local.set({[MONITOR_REBOOT_SNAPSHOT_KEY]:monitorRebootSnapshot});monitorPublishSharedRebootSnapshot();monitorGhostPersist(true);persistMonitorTrashedNodes();}

  listRecords=listRecords.filter((x)=>keptKeys.has(String(x?.conversation_key||"")));

  const visibleItems=kept.filter((x)=>x.kind==="closed").map((x)=>x.item);

  const convoCount=listRecords.length+visibleItems.length;

  const snapItems=(Array.isArray(monitorRebootSnapshot?.items)?monitorRebootSnapshot.items:[]).filter((x)=>!monitorTrashedConversationKeys.has(String(x?.conversation_key||"")));

  const full=document.createElement("button");full.type="button";full.className="monitor-detached-restore monitor-recovery-full";full.textContent=`전체 복원${convoCount?` (${convoCount})`:""}`;full.disabled=!convoCount||monitorRebootRestoreActive;full.title="삭제된 노드 복구 목록 전체 복원";full.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorAllRecovery(full,listRecords,visibleItems);});

  const reboot=document.createElement("button");reboot.type="button";reboot.className="monitor-detached-restore monitor-recovery-full";reboot.textContent=`재부팅 복원${snapItems.length?` (${snapItems.length})`:""}`;reboot.disabled=!snapItems.length||monitorRebootRestoreActive;reboot.title="재부팅 전 저장된 대화만 복원";reboot.addEventListener("click",(e)=>{e.stopPropagation();void restoreMonitorRebootSnapshot(reboot);});

  const convoPane=document.createElement("section");convoPane.className="monitor-trash-pane monitor-trash-conversation-pane";convoPane.append(makeHeader("삭제된 노드",convoCount,clearMonitorConversationRecovery,[full,reboot]));const convoScroll=document.createElement("div");convoScroll.className="monitor-trash-pane-scroll";

  if(listRecords.length)renderTrashRows("list",convoScroll);

  if(!visibleItems.length&&!listRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";convoScroll.append(empty);}

  for(const ghost of visibleItems){const row=document.createElement("div");row.className="monitor-closed-conversation-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=monitorClosedConversationPreviousLocation(ghost),context=monitorClosedConversationContextTitle(ghost);const created=Number(ghost?.first_seen_ms||0),closed=Number(ghost?.closed_at_ms||ghost?.captured_at_ms||0),rec=monitorContextTitleRecord(String(ghost?.conversation_key||""));const displayContext=(rec.manual_locked&&rec.manual_title)||rec.context_title||ghost.meaningful_title||context;const source=ghost.recovery_source||"일반 종료";const fmtDateTime=(ms)=>ms?new Date(ms).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).replace(/\. /g,".").replace(/\.$/,""):"?";const fmtTime=(ms)=>ms?new Date(ms).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false}):"?";const sameDay=created&&closed&&new Date(created).toDateString()===new Date(closed).toDateString();info.textContent=`${location} · ${displayContext} · ${fmtDateTime(created)} - ${sameDay?fmtTime(closed):fmtDateTime(closed)}`;info.title=`이전 위치 ${location} · ${source}`;const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";const restoring=monitorDetachedRestorePending.has(String(ghost?.conversation_key||""));restore.textContent=restoring?"복구 중…":"복구";restore.disabled=restoring;restore.addEventListener("click",(event)=>{event.stopPropagation();void restoreMonitorDetachedTask(ghost,restore);});row.addEventListener("contextmenu",(event)=>{event.preventDefault();event.stopPropagation();const existing=row.querySelector(".monitor-recovery-details");if(existing){existing.remove();return;}panel.querySelectorAll(".monitor-recovery-details").forEach((node)=>node.remove());const detail=document.createElement("div");detail.className="monitor-recovery-details";const key=String(ghost?.conversation_key||"");for(const [label,value] of [["이전 위치",location],["제목",displayContext],["복구 출처",source],["생성",created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"],["소멸",closed?new Date(closed).toLocaleString("ko-KR"):"알 수 없음"],["프로필",ghost.profile_id||"-"],["conversationKey",key||"-"]]){const line=document.createElement("div");line.className="monitor-recovery-detail-line";const k=document.createElement("b");k.textContent=label;const v=document.createElement("span");v.textContent=String(value);line.append(k,v);detail.append(line);}row.append(detail);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(event)=>{event.stopPropagation();row.classList.add("monitor-trash-removing");setTimeout(()=>deleteMonitorRecoveryRecord(ghost.conversation_key),140);});row.append(info);appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);convoScroll.append(row);}

  const contextRows = new Map([...convoScroll.querySelectorAll('.monitor-closed-conversation-row[data-recovery-key]')]
    .map(row => [row.dataset.recoveryKey, row]));
  for (const ghost of visibleItems) {
    const row = contextRows.get(String(ghost?.conversation_key || ''));
    if (row) row.append(createMonitorContextContinueButton(ghost));
  }
  const recoveryRowsByKey=new Map([...convoScroll.querySelectorAll(".monitor-closed-conversation-row[data-recovery-key]")].map((row)=>[String(row.dataset.recoveryKey||""),row]));for(const entry of kept){const key=String(entry?.item?.conversation_key||"");const row=recoveryRowsByKey.get(key);if(row)convoScroll.append(row);}convoPane.append(convoScroll);panel.append(convoPane,thumbPane);return panel;

}

function configureMonitorProviderLaunchButton(button, provider) {
  const normalizedProvider = String(provider || "").toUpperCase() === "GOOGLE" ? "GOOGLE" : "NAVER";
  const name = normalizedProvider === "GOOGLE" ? "Google" : "Naver";
  const type = normalizedProvider === "GOOGLE" ? "launchGoogleChatGpt" : "launchNaverChatGpt";

  button.dataset.provider = normalizedProvider;
  button.textContent = normalizedProvider === "GOOGLE" ? "G+" : "N+";
  button.title = `${name} ChatGPT 새 창 열기`;
  button.setAttribute("aria-label", `${name} ChatGPT 새 창 열기`);
  button.disabled = false;

  button.addEventListener("click", async () => {
    try {
      const result = await monitorNativeLaunchIsolated({ type });
      if (!result?.ok || !result?.launched) {
        throw new Error(result?.error || `${name} ChatGPT 실행 실패`);
      }
    } catch (error) {
      setMonitorStatus(`${name} ChatGPT 실행 실패 · ${error?.message || error}`, false);
    }
  });
}

function rememberMonitorWorkerPlacement(worker, state, location) {

  const key = String(worker?.conversation_key || "").trim();

  if (!key || !location?.desktop) return;

  const desktopIndex = Number(location.desktop) - 1;

  const desktopId = monitorDesktopState.desktopIds[desktopIndex] || "";

  if (!desktopId) return;

  monitorLastPlacementByConversation.set(key, { desktopId, desktop: Number(location.desktop), profileId: String(worker?.profile_id || "").trim().toUpperCase(), at: Date.now() });

}

async function syncMonitorPhysicalWorkplaces(state, force = false) {

  // Monitor is presentation/input UI and must never write physical workplace state.

  return;

}

const MONITOR_WORKER_ORDER_KEY = "desktopWindowMonitorWorkerOrderV1";

const monitorWorkerOrderByDesktop = new Map();

let monitorWorkerOrderReady = false;

function monitorPersistWorkerOrder() {

  if (!monitorWorkerOrderReady) return;

  const data={}; for(const [desktopId,keys] of monitorWorkerOrderByDesktop) data[desktopId]=[...new Set((Array.isArray(keys)?keys:[]).filter(Boolean))].slice(0,80);

  chrome.storage.local.set({[MONITOR_WORKER_ORDER_KEY]:data});

}

function monitorSetWorkerOrder(desktopId, keys) {

  const id=String(desktopId||"").trim(); if(!id)return;

  monitorWorkerOrderByDesktop.set(id,[...new Set((Array.isArray(keys)?keys:[]).map(String).filter(Boolean))]);

  monitorPersistWorkerOrder();

}

function monitorRemoveWorkerOrderKey(key) {

  const k=String(key||"").trim(); if(!k)return;

  for(const [id,keys] of monitorWorkerOrderByDesktop){const next=(keys||[]).filter(x=>String(x)!==k); if(next.length!==(keys||[]).length)monitorWorkerOrderByDesktop.set(id,next);}

}

function monitorMoveWorkerOrderKey(key, sourceDesktopId, targetDesktopId) {

  const k=String(key||"").trim(), target=String(targetDesktopId||"").trim(); if(!k||!target)return;

  monitorRemoveWorkerOrderKey(k); const next=[...(monitorWorkerOrderByDesktop.get(target)||[])]; next.push(k); monitorWorkerOrderByDesktop.set(target,[...new Set(next)]); monitorPersistWorkerOrder();

}

function monitorReorderWorkerKey(desktopId, key, targetKey, after=false) {

  const id=String(desktopId||"").trim(), k=String(key||"").trim(), t=String(targetKey||"").trim(); if(!id||!k||!t||k===t)return false;

  const current=[...(monitorWorkerOrderByDesktop.get(id)||[])].filter(x=>x!==k); let index=current.indexOf(t); if(index<0)return false; if(after)index+=1; current.splice(index,0,k); monitorSetWorkerOrder(id,current); return true;

}

function monitorListDisplaySlots(members, state) {

  const result=new Map();

  for(const worker of (Array.isArray(members)?members:[])){

    const stable=monitorStableNodeSlot(worker,state);

    if(stable)result.set(worker?.__display_key,`N${stable.slot} · D${stable.desktop}`);

  }

  return result;

}

function initializeMonitorWorkerOrderStorage() { chrome.storage.local.get([MONITOR_WORKER_ORDER_KEY],(data)=>{const raw=data?.[MONITOR_WORKER_ORDER_KEY]||{};for(const [id,keys] of Object.entries(raw))monitorWorkerOrderByDesktop.set(id,Array.isArray(keys)?keys.map(String):[]);monitorWorkerOrderReady=true;if(monitorLastAiState)renderWorkers(monitorLastAiState);}); }

let monitorWorkerPointerInteractionActive = false;

let monitorDeferredWorkerRenderState = null;

let monitorWorkerPointerReleaseTimer = 0;

const MONITOR_WORKER_CLICK_SETTLE_MS = 550;
const MONITOR_WORKER_RENDER_MIN_INTERVAL_MS = 120;
let monitorWorkerRenderTimer = 0;
let monitorWorkerRenderPendingState = null;
let monitorWorkerRenderInFlight = false;
let monitorWorkerRenderLastAt = 0;

function flushDeferredMonitorWorkerRender() {

  if (monitorWorkerPointerInteractionActive || !monitorDeferredWorkerRenderState) return;

  const deferred = monitorDeferredWorkerRenderState;

  monitorDeferredWorkerRenderState = null;

  renderWorkers(deferred);

}

function settleMonitorWorkerPointerInteraction(delay = MONITOR_WORKER_CLICK_SETTLE_MS) {

  clearTimeout(monitorWorkerPointerReleaseTimer);

  monitorWorkerPointerReleaseTimer = setTimeout(() => {

    monitorWorkerPointerInteractionActive = false;

    flushDeferredMonitorWorkerRender();

  }, delay);

}

monitorWorkers.addEventListener("pointerdown", (event) => {

  if (event.button !== 0 || !event.target.closest(".monitor-worker-row, .monitor-closed-conversation-row")) return;

  clearTimeout(monitorWorkerPointerReleaseTimer);

  monitorWorkerPointerInteractionActive = true;

}, true);

monitorWorkers.addEventListener("click", (event) => {

  if (!event.target.closest(".monitor-worker-row, .monitor-closed-conversation-row")) return;

  settleMonitorWorkerPointerInteraction();

});

document.addEventListener("pointerup", () => {

  if (monitorWorkerPointerInteractionActive) settleMonitorWorkerPointerInteraction();

}, true);

document.addEventListener("pointercancel", () => {

  if (monitorWorkerPointerInteractionActive) settleMonitorWorkerPointerInteraction(0);

}, true);

function monitorRenderDiagnosticText(){
  const elapsedMs=Math.max(1,Date.now()-monitorRenderDiagnostics.startedAt);
  const elapsedSec=elapsedMs/1000;
  let visibleWorkers=0;
  try{
    if(monitorLastAiState){
      const projected=monitorWorkersProjectionForState(monitorLastAiState);
      visibleWorkers=projected.filter((worker)=>isMonitorVisibleWorker(worker,monitorLastAiState)).length;
    }
  }catch(_){}
  const documentNodes=document.getElementsByTagName("*").length;
  const monitorNodes=monitorRoot?.querySelectorAll?.("*")?.length||0;
  const workerDomNodes=monitorWorkers?.querySelectorAll?.("*")?.length||0;
  const requestRate=(monitorRenderDiagnostics.renderRequests/elapsedSec).toFixed(2);
  const runRate=(monitorRenderDiagnostics.renderRuns/elapsedSec).toFixed(2);
  const roughCreates=monitorRenderDiagnostics.renderRuns*visibleWorkers*15;
  const roughListeners=monitorRenderDiagnostics.renderRuns*visibleWorkers*14;
  const thumbnailStats=monitorThumbnailService?.stats?.()||{};
  return [
    "Monitor 런타임 진단",
    MonitorNativeTrace.export(),
    `build: ${MONITOR_BUILD_ID}`,
    `renderer 시작: ${new Date(monitorRenderDiagnostics.startedAt).toLocaleString()}`,
    `pixel visuals: ${MONITOR_PIXEL_VISUALS_ENABLED} · window capture: ${MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED}`,
    `renderWorkers 요청: ${monitorRenderDiagnostics.renderRequests} · ${requestRate}/s`,
    `전체 worker DOM 렌더: ${monitorRenderDiagnostics.renderRuns} · ${runRate}/s`,
    `ACT 전체 갱신: ${monitorRenderDiagnostics.refreshRuns}회 · 최근 ${Math.round(monitorRenderDiagnostics.refreshLastMs)}ms · 최장 ${Math.round(monitorRenderDiagnostics.refreshSlowestMs)}ms`,
    `ACT 갱신 단계(최근): ${Object.entries(monitorRenderDiagnostics.refreshLastStages||{}).map(([name,ms])=>`${name} ${Math.round(Number(ms)||0)}ms`).join(" · ")||"아직 없음"}`,
    `현재 visible workers: ${visibleWorkers}`,
    `DOM nodes: document ${documentNodes} · Monitor ${monitorNodes} · worker panel ${workerDomNodes}`,
    `현재 구조: worker당 createElement 15곳 · listener 14곳`,
    `현재 worker 수 기준 누적 생성부하 추정: DOM ${roughCreates} · listener ${roughListeners}`,
    `pending render: ${Boolean(monitorWorkerRenderPendingState)} · in-flight: ${Boolean(monitorWorkerRenderInFlight)}`,
    `thumbnail service: requested ${Number(thumbnailStats.requested||0)} · started ${Number(thumbnailStats.started||0)} · completed ${Number(thumbnailStats.completed||0)} · failed ${Number(thumbnailStats.failed||0)}`,
    `thumbnail live: active ${Number(thumbnailStats.active||0)} · queued ${Number(thumbnailStats.queuedNow||0)} · cached ${Number(thumbnailStats.cached||0)} · max active ${Number(thumbnailStats.maxObservedActive||0)}`,
    `thumbnail disposal: stale ${Number(thumbnailStats.staleDiscarded||0)} · evicted ${Number(thumbnailStats.evicted||0)} · disposed ${Number(thumbnailStats.disposedResults||0)}`,
  ].join("\n");
}

function monitorLocalLlmReadyState() {
  return String(monitorLocalLlmControlState?.state || "off").toLowerCase();
}

function monitorLocalLlmIsUsable(control = monitorLocalLlmControlState) {
  if (!control || String(control.state || "off").toLowerCase() !== "ready") return false;
  return monitorLocalOllamaModels(control).some(monitorLocalModelIsLoaded);
}

function monitorLocalLlmSummary() {
  const control = monitorLocalLlmControlState;
  if (!control) return "상태 확인 중";
  const models = monitorLocalOllamaModels(control);
  const loaded = models.filter(monitorLocalModelIsLoaded);
  const stack = control.state === "ready" ? "Ollama · 준비됨"
    : control.state === "partial" ? "일부 서비스만 준비됨"
      : "Ollama · 꺼짐";
  return `${stack} · 모델 ${loaded.length}/${models.length} 로드`;
}

function monitorLocalLlmActivityText(control = monitorLocalLlmControlState) {
  const activity = control?.activity;
  if (!activity || typeof activity !== "object") return "대기";
  const raw = String(activity.status || "").toUpperCase();
  const labels = {
    QUEUED: "대기",
    DISCOVERING: "분석 중",
    PREPARING: "정리 중",
    RUNNING: "작업 중",
    SYNTHESIZING: "결과 정리 중",
    WAITING_APPROVAL: "승인 대기",
    APPLYING: "적용 중",
    COMPLETE: "완료",
    COMPLETED: "완료",
    SUCCEEDED: "완료",
    DONE: "완료",
    FAILED: "실패",
    REJECTED: "실패",
  };
  let label = labels[raw] || raw || "대기";
  const role = String(activity.role || "").toUpperCase();
  if (raw === "RUNNING") {
    if (role === "CODER") label = "CODER · 구현안 분석 중";
    else if (role === "CRITIC") label = "CRITIC · 오류/회귀 검토 중";
    else if (role === "JUDGE") label = "JUDGE · 대안 판정 중";
  } else if (raw === "SYNTHESIZING" && role === "JUDGE") {
    label = "JUDGE · 결과 정리 중";
  }
  const started = Number(activity.created || activity.updated || 0);
  if (!started) return label;
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - started));
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return label + " · " + mm + ":" + ss;
}

const monitorLocalLlmCommandState = {
  inFlight: false,
  generation: 0,
  pendingEnabled: null,
};

function monitorUpdateLocalLlmToggleButtons() {
  for (const button of document.querySelectorAll(".monitor-local-llm-toggle")) {
    monitorUpdateLocalLlmToggleButton(button);
  }
}

function monitorUpdateLocalLlmToggleButton(button) {
  if (!button) return;

  if (monitorLocalLlmCommandState.inFlight) {
    button.disabled = true;
    button.textContent = monitorLocalLlmCommandState.pendingEnabled === false ? "종료 중..." : "시작 중...";
    button.title = monitorLocalLlmCommandState.pendingEnabled === false
      ? "Local LLM 종료 요청 처리 중"
      : "Local LLM 시작 요청 처리 중";
    return;
  }

  const state = monitorLocalLlmReadyState();
  const powered = state === "ready";
  const partial = state === "partial";
  button.classList.toggle("is-on", powered);
  button.classList.toggle("is-partial", partial);
  button.disabled = false;
  button.textContent = powered ? "끄기" : "켜기";
  button.title = powered
    ? "끄기: Ollama를 종료합니다"
    : "켜기: Ollama를 시작하고 기본 모델을 로드합니다";
}

function monitorAdoptLocalLlmControlPayload(payload, render = true) {
  if (!payload || typeof payload !== "object") return;
  monitorLocalLlmControlState = payload;

  if (Array.isArray(payload.llm_nodes)) {
    monitorCachedLlmNodes = payload.llm_nodes;
    if (monitorLastAiState && typeof monitorLastAiState === "object") {
      monitorLastAiState = { ...monitorLastAiState, llm_nodes: payload.llm_nodes };
    }
  }

  monitorUpdateLocalLlmToggleButtons();
  if (render && monitorLastAiState) renderWorkers(monitorLastAiState);
  if (render && monitorStructurePanel?.isConnected && monitorStructurePanel.style.display !== "none") {
    renderMonitorStructure();
  }
}

async function monitorEnsureLocalLlmControlStatus(force = false, render = true) {
  if (!force && monitorLocalLlmControlState) return monitorLocalLlmControlState;
  if (monitorLocalLlmStatusPromise) return monitorLocalLlmStatusPromise;

  const requestGeneration = monitorLocalLlmCommandState.generation;
  const request = (async () => {
    const response = await actFetch(ORCHESTRATOR_LOCAL_LLM_STATUS_URL, { cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok) throw new Error(data?.error || ("HTTP " + response.status));

    if (requestGeneration !== monitorLocalLlmCommandState.generation || monitorLocalLlmCommandState.inFlight) {
      return data;
    }

    monitorAdoptLocalLlmControlPayload(data, render);
    return data;
  })().catch((error) => {
    console.warn("Local LLM status unavailable", error);
    return null;
  });

  monitorLocalLlmStatusPromise = request;
  try {
    return await request;
  } finally {
    if (monitorLocalLlmStatusPromise === request) monitorLocalLlmStatusPromise = null;
  }
}

async function monitorSetLocalLlmEnabled(enabled) {
  if (monitorLocalLlmCommandState.inFlight) return null;

  monitorLocalLlmCommandState.generation += 1;
  monitorLocalLlmCommandState.pendingEnabled = Boolean(enabled);
  monitorLocalLlmStatusPromise = null;
  monitorLocalLlmCommandState.inFlight = true;
  monitorUpdateLocalLlmToggleButtons();

  try {
    const response = await actFetch(ORCHESTRATOR_LOCAL_LLM_CONTROL_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.ok) throw new Error(data?.error || ("HTTP " + response.status));

    monitorAdoptLocalLlmControlPayload(data);
    return data;
  } catch (error) {
    console.warn("Local LLM control failed", error);
    return null;
  } finally {
    monitorLocalLlmCommandState.inFlight = false;
    monitorLocalLlmCommandState.pendingEnabled = null;
    monitorUpdateLocalLlmToggleButtons();
    void monitorEnsureLocalLlmControlStatus(true);
  }
}

function renderWorkers(state) {
  monitorRenderDiagnostics.renderRequests += 1;
  if (!MONITOR_NODE_RENDER_ENABLED) return;

  monitorWorkerRenderPendingState = state;

  if (monitorWorkerPointerInteractionActive) {
    monitorDeferredWorkerRenderState = state;
    return;
  }

  if (monitorWorkerRenderTimer || monitorWorkerRenderInFlight) return;
  const elapsed = performance.now() - monitorWorkerRenderLastAt;
  const delay = Math.max(0, MONITOR_WORKER_RENDER_MIN_INTERVAL_MS - elapsed);
  monitorWorkerRenderTimer = setTimeout(() => {
    monitorWorkerRenderTimer = 0;
    const pendingState = monitorWorkerRenderPendingState;
    monitorWorkerRenderPendingState = null;
    if (!pendingState) return;
    monitorWorkerRenderInFlight = true;
    try {
      performMonitorWorkerRender(pendingState);
    } finally {
      monitorWorkerRenderInFlight = false;
      monitorWorkerRenderLastAt = performance.now();
      if (monitorWorkerRenderPendingState) renderWorkers(monitorWorkerRenderPendingState);
    }
  }, delay);
}

function performMonitorWorkerRender(state) {
  monitorRenderDiagnostics.renderRuns += 1;

  if (monitorWorkerPointerInteractionActive) {

    monitorDeferredWorkerRenderState = state;

    return;

  }

  monitorDeferredWorkerRenderState = null;

  let workers = [];

  let visible = [];

  try {

    workers = monitorWorkersProjectionForState(state);

    visible = workers.filter((worker) => isMonitorVisibleWorker(worker, state));

  } catch (error) {

    console.warn("DesktopWindow Monitor worker projection delayed", error);

    setMonitorStatus("ACT 실행 중 · 노드 계산 지연", false);

    return;

  }

  let browserDisplaySlots = new Map();

  let chatgptListDisplaySlots = new Map();

  try { browserDisplaySlots = monitorBrowserDisplaySlots(visible, state); }

  catch (error) { console.warn("DesktopWindow Monitor display-slot fallback", error); }

  try { chatgptListDisplaySlots = monitorListDisplaySlots(visible.filter((worker)=>classifyMonitorWorker(worker)==="chatgpt"), state); }

  catch (error) { console.warn("DesktopWindow Monitor list-slot fallback", error); }

    try { syncMonitorMinimizedNodeBadges(state); }
  catch (error) { console.warn("DesktopWindow Monitor minimized snapshot delayed", error); }
  if (MONITOR_NODE_RENDER_PROJECTION_ONLY) return;
  const nextWorkerDom = document.createDocumentFragment();

  monitorRoleByHwnd.clear();

  monitorWorkingByHwnd.clear();

  monitorPausedByHwnd.clear();

  for (const group of MONITOR_AGENT_GROUPS) {

    const groupDisplaySlots = group.key === "chatgpt" ? chatgptListDisplaySlots : browserDisplaySlots;

    const rawMembers = visible.filter((worker) => classifyMonitorWorker(worker) === group.key).sort((a, b) => {
      if (group.key === "local-llm") {
        const localLoaded = (worker) => {
          const runtime = worker?.llm_runtime && typeof worker.llm_runtime === "object" ? worker.llm_runtime : {};
          const state = String(worker?.llm_runtime_state || worker?.runtime_state || runtime.state || "").toUpperCase();
          return runtime.loaded === true || runtime.busy === true || ["LOADED", "BUSY"].includes(state);
        };
        const loadedDelta = Number(localLoaded(b)) - Number(localLoaded(a));
        if (loadedDelta) return loadedDelta;
      }

      const al=groupDisplaySlots.get(a?.__display_key)||"", bl=groupDisplaySlots.get(b?.__display_key)||"";

      const ap=monitorNodeIdentityParts(al), bp=monitorNodeIdentityParts(bl);

      if(ap.desktop&&bp.desktop){if(ap.desktop!==bp.desktop)return ap.desktop-bp.desktop;if(ap.nodeNumber!==bp.nodeNumber)return ap.nodeNumber-bp.nodeNumber;}

      return compareMonitorWorkers(a,b,state);

    });

    const members = group.key === "chatgpt" ? monitorGroupChatgptMembersForDisplay(rawMembers,state) : rawMembers;

    const section = document.createElement("section");

    section.className = "monitor-worker-group";

    section.dataset.group = group.key;

    const header = document.createElement("div");

    header.className = "monitor-worker-group-title";

      const headerLabel = document.createElement("span");

    headerLabel.className = "monitor-worker-group-label";

      headerLabel.textContent = group.label;

    header.append(headerLabel);
    const groupReady = group.key === "chatgpt"
      ? members.some((worker) => worker?.__kind !== "LLM_NODE")
      : members.some((worker) => monitorWorkerReadyForUse(worker, group.key));
    header.classList.toggle("is-ready", groupReady);

    if (group.key === "chatgpt") {

      const googleLaunch = document.createElement("button");

      googleLaunch.type = "button";

      googleLaunch.className = "monitor-provider-launch monitor-google-launch";

      googleLaunch.textContent = "G+";

      googleLaunch.title = "Google ChatGPT 새 창 열기";

      configureMonitorProviderLaunchButton(googleLaunch, "GOOGLE");

      const roleModes=document.createElement("span"); roleModes.className="monitor-role-mode-buttons";

      for(const [mode,label] of [["ORCHESTRATOR","O"],["COORDINATOR_1","C1"],["COORDINATOR_2","C2"],["EXEMPT","열외"]]) {

        const b=document.createElement("button"); b.type="button"; b.className=`monitor-role-mode monitor-role-mode-${mode.toLowerCase().replaceAll("_","-")}`; b.dataset.roleMode=mode; b.textContent=label; b.classList.toggle("selected",monitorRoleAssignMode===mode); b.title=`${label} 선택 후 ChatGPT 바 클릭`; b.addEventListener("pointerdown",(event)=>{ if(event.button!==0)return; event.preventDefault(); monitorSetRoleAssignMode(mode); }); b.addEventListener("click",(event)=>{ if(event.detail===0) monitorSetRoleAssignMode(mode); }); roleModes.append(b);

      }

      const launch = document.createElement("button");

      launch.type = "button";

      launch.className = "monitor-provider-launch";

      launch.textContent = "N+";

      configureMonitorProviderLaunchButton(launch, "NAVER");

      const actions=document.createElement("span"); actions.className="monitor-worker-group-actions"; actions.append(roleModes,googleLaunch,launch); header.append(actions);

    }

    if (group.key === "local-llm") {
      const summary = document.createElement("small");
      summary.className = "monitor-local-llm-summary";
      summary.textContent = monitorLocalLlmSummary();
      header.append(summary);
      const activity = document.createElement("span");
      activity.className = "monitor-local-llm-activity";
      activity.textContent = monitorLocalLlmActivityText();
      activity.title = "최근 Local LLM 작업 상태";
      header.append(activity);
      const actions = document.createElement("span");
      actions.className = "monitor-worker-group-actions";
      const openUi = document.createElement("button");
      openUi.type = "button";
      openUi.className = "monitor-local-llm-open-ui";
      openUi.textContent = "UI 열기";
      openUi.title = "7865 Local Agent UI를 새 창으로 엽니다.";
      openUi.addEventListener("click", () => {
        chrome.windows.create({ url: LOCAL_LLM_UI_URL, type: "popup", width: 1200, height: 820, focused: true });
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "monitor-local-llm-toggle";
      toggle.textContent = "켜기";
      toggle.addEventListener("click", async () => {
        if (monitorLocalLlmCommandState.inFlight) return;
        await monitorSetLocalLlmEnabled(monitorLocalLlmReadyState() !== "ready");
      });
      actions.append(openUi, toggle);
      header.append(actions);
      // The header is detached while it is built, so a document-wide refresh
      // cannot see its button yet.
      monitorUpdateLocalLlmToggleButton(toggle);
      void monitorEnsureLocalLlmControlStatus(false, false);
    }

    const rows = document.createElement("div");

    rows.className = "monitor-worker-group-rows";

    if (members.length === 0) {

      const empty = document.createElement("div");

      empty.className = "monitor-worker-empty";

      empty.textContent = "−";

      rows.append(empty);

    }

    for (const worker of members) {

      const row = document.createElement("div");

      row.className = "monitor-worker-row";
      const workerReady = monitorWorkerReadyForUse(worker, group.key);
      row.classList.toggle("is-ready", workerReady);
      row.classList.toggle("is-not-ready", !workerReady);

      const windowGroupMembers = Array.isArray(worker?.__window_group_members) ? worker.__window_group_members : [worker];

      const windowGroupConversationKeys = [...new Set(windowGroupMembers.map((item)=>String(item?.conversation_key||"").trim()).filter(Boolean))];

      const conversationKey = String(worker?.conversation_key || "").trim();

      if(windowGroupConversationKeys.length>1){ row.dataset.conversationKeys=JSON.stringify(windowGroupConversationKeys); row.classList.add("monitor-window-node-group"); }

      const ageIdentity = monitorAgeIdentityForWorkerGroup(windowGroupMembers, state);

      const ageConversationKey = ageIdentity.conversationKey || conversationKey;

      const nodeLocationState = monitorCanonicalPhysicalLocation(worker, state);

      const groupConversationKey = conversationKey;

      if (conversationKey && monitorSystemNodeKeys.has(conversationKey)) row.classList.add("monitor-system-node");

      if (conversationKey) row.dataset.conversationKey = conversationKey;

      if (ageConversationKey) {

        const ageing = Math.max(0, Math.min(100, Number(ageIdentity.ageing)||0));

        row.style.setProperty("--monitor-row-age", `${ageing}%`);

      }

      const conversationGroup = applyMonitorConversationGroupVisual(row, groupConversationKey, state);

      const currentAssignMode = String(monitorRoleAssignMode || "").toUpperCase();

      const projectedActNode = monitorActBrowserNode(worker, state);

      const currentWorkerRole = String(projectedActNode?.role || "").toUpperCase();

      const managedExemption = projectedActNode?.exemption || null;

      const managedRole = (managedExemption || currentWorkerRole === "EXEMPT") ? "EXEMPT" : currentWorkerRole;

      const persistentRoleClass = monitorPersistentRoleClass(currentWorkerRole);

      if (persistentRoleClass) row.classList.add(persistentRoleClass);

      if (projectedActNode?.organization_member === true && managedRole) {

        row.classList.add("monitor-act-managed", `monitor-act-role-${managedRole.toLowerCase().replaceAll("_", "-")}`);

      }

      const isCurrentRoleOccupant = Boolean(currentAssignMode && (currentWorkerRole === currentAssignMode || (currentAssignMode === "EXEMPT" && (managedExemption || currentWorkerRole === "EXEMPT"))));

      if (isCurrentRoleOccupant) row.classList.add("monitor-role-current-occupant");

      const identity = document.createElement("div");

      identity.className = "monitor-worker-identity";

      if (nodeLocationState?.status === "CHECKING") row.classList.add("monitor-node-checking");

      if (nodeLocationState?.status === "RECOVERY_REQUIRED") row.classList.add("monitor-node-recovery-required");

      const location = groupDisplaySlots.get(worker?.__display_key) || nodeLocationState?.label || resolveStableMonitorLocation(worker, state);

      const nodeReference = worker?.__kind === "LLM_NODE" ? "" : String(location || "").replace(/_$/, "");

      const nodeEndpoint = endpointForMonitorWorker(worker, state);

      const groupedNodeLabels = windowGroupMembers.map((item)=>String(groupDisplaySlots.get(item?.__display_key) || monitorCanonicalPhysicalLocation(item,state)?.label || "").trim()).filter((label)=>/^D\d+-\d+$/.test(label));

      const groupedSuffixes = [...new Set(groupedNodeLabels.map((label)=>Number(label.split("-")[1])).filter((value)=>Number.isInteger(value)&&value>0))].sort((a,b)=>a-b);

      const nodeVisualReference = groupedSuffixes.length>1 && groupedNodeLabels.length ? `${groupedNodeLabels[0].split("-")[0]}-${groupedSuffixes.join("/")}` : nodeReference;

      if (nodeReference) row.dataset.nodeRef = nodeReference;

      if (nodeReference) {

        const locationLabel = document.createElement("span");

        locationLabel.className = "monitor-worker-location";

        locationLabel.textContent = nodeVisualReference;

        locationLabel.title = nodeVisualReference===nodeReference?nodeReference:`${nodeVisualReference} · ${nodeReference}`;

        identity.append(locationLabel);

      }

      const endpoint = nodeEndpoint;

      const minimized = monitorEndpointIsMinimized(endpoint, worker, state);

      const profileId = String(ageIdentity.profileId || worker?.profile_id || "").toUpperCase();

      if (profileId === "GOOGLE" || profileId === "NAVER") {

        row.classList.add(profileId === "GOOGLE" ? "monitor-profile-google" : "monitor-profile-naver");

      } else {

        const name = document.createElement("span");

        name.className = "monitor-worker-name";

        name.textContent = cleanMonitorWorkerName(worker);

        identity.append(name);

      }

      const endpointTitle = monitorContextTitleDisplay(worker, state, endpoint);
      row.dataset.contextTitleLive = String(endpoint?.presence_state||"").toUpperCase()==="OPEN" ? String(endpoint?.title||"").trim() : "";
      row.dataset.contextTitleFallback = monitorWorkerContextTitle(worker,state,endpoint);

      if (endpointTitle) {

        const chatTitle = document.createElement("span");

        chatTitle.className = "monitor-worker-chat-title";

        chatTitle.textContent = endpointTitle;

        identity.append(chatTitle);

      }

      if (group.key === "chatgpt" && conversationKey) {

        const ghost=monitorGhostCache.get(conversationKey)||{};

        const rec=monitorContextTitleRecord(conversationKey);

        row.title = [row.title, monitorLifecycleTooltip(conversationKey,endpoint,ghost), rec.context_summary?`맥락 ${rec.context_summary}`:""].filter(Boolean).join("\n");

        attachMonitorContextTitleMenu(row,worker,state,endpoint);

        if(monitorContextTitlesReady && !rec.manual_locked) void refreshMonitorContextTitle(worker,state,endpoint,false);

      }

      if (conversationGroup) {

        row.title = `같은 대화 중복 · ${conversationGroup.count}개 창`;

      }

      const status = document.createElement("div");

      status.className = "monitor-worker-status";

      if (worker?.__kind === "LLM_NODE") {

        row.classList.add("monitor-llm-node-row");

        const llmStatus = String(worker?.status || "unavailable").toLowerCase();

        const runtimeState = String(worker?.llm_runtime_state || llmStatus).toUpperCase();

        row.classList.add("monitor-llm-state-" + runtimeState.toLowerCase().replaceAll("_", "-"));
        // READY means callable standby only for a local model.  It is not yet
        // resident in VRAM, unlike LOADING/LOADED/BUSY.
        row.classList.toggle("monitor-llm-local-ready", group.key === "local-llm"
          && runtimeState === "READY");

        row.title = `${String(worker?.name || worker?.label || "LLM")} · ${runtimeState}`;

        const detail = document.createElement("span");
        detail.className = "monitor-llm-runtime-detail";
        const presentation = monitorLlmRuntimePresentation(worker, workerReady);
        detail.textContent = presentation.label;
        status.append(detail);
        row.title = `${String(worker?.display_name || worker?.name || worker?.label || "LLM")} · ${presentation.label}${presentation.vramText}`;

      }

      if (nodeLocationState?.status === "CHAT_CHANGED") {

        row.classList.add("monitor-node-chat-changed");

        const changeControls=document.createElement("span"); changeControls.className="monitor-node-chat-change-controls";

        const restore=document.createElement("button"); restore.type="button"; restore.className="monitor-node-action monitor-node-restore"; restore.textContent="복구"; restore.title="이 노드가 원래 사용하던 챗으로 되돌리기"; restore.addEventListener("click",event=>{event.stopPropagation();void restoreMonitorNodeChatChange(worker,nodeLocationState,restore);});

        const approve=document.createElement("button"); approve.type="button"; approve.className="monitor-node-action monitor-node-approve"; approve.textContent="승인"; approve.title="현재 브라우저의 새 챗을 이 노드에 정식 매칭"; approve.addEventListener("click",event=>{event.stopPropagation();void approveMonitorNodeChatChange(worker,nodeLocationState,approve);});

        changeControls.append(restore,approve); status.append(changeControls);

      } else if (worker?.__kind !== "LLM_NODE" && nodeLocationState?.status === "RECOVERY_REQUIRED") {

        const recovery = document.createElement("span");

        recovery.className = "monitor-node-chat-change-controls";

        const checkButton = document.createElement("button");

        checkButton.type = "button";

        checkButton.className = "monitor-node-action monitor-node-approve";

        checkButton.textContent = "승인";

        checkButton.title = "현재 탭과 채팅키 결합을 이 노드의 현재 상태로 승인";

        checkButton.addEventListener("click", async (event) => {

          event.stopPropagation();

          checkButton.disabled = true;

          try { await refreshMonitorIdentityIndex(state, true); await refreshAiMonitor(); }

          finally { checkButton.disabled = false; }

        });

        recovery.append(checkButton);

        if (nodeLocationState.status === "RECOVERY_REQUIRED") {

          const restoreButton = document.createElement("button");

          restoreButton.type = "button";

          restoreButton.className = "monitor-node-action monitor-node-restore";

          restoreButton.textContent = "복구";

          restoreButton.title = "마지막으로 확인된 이 노드의 ChatGPT 대화를 복구";

          restoreButton.addEventListener("click", (event) => { event.stopPropagation(); void restoreMonitorDetachedTask(worker, restoreButton); });

          recovery.prepend(restoreButton);

        }

        status.append(recovery);

      }

      if (group.key === "chatgpt" && conversationKey) status.append(createMonitorContextContinueButton({ ...worker, conversation_key: conversationKey }));
      if(group.key==="chatgpt"&&conversationKey&&monitorRoleAssignMode){ row.classList.add("monitor-role-targetable"); row.addEventListener("click",(event)=>{if(event.target?.closest?.(".monitor-worker-off"))return;if(event.detail>1)return;void monitorApplyRoleMode(worker,state);}); }

      const connection = resolveWorkerConnectionState(worker, state);

      row.classList.add(`connection-${connection}`);

      row.setAttribute("data-connection", connection);

      if (worker?.__kind === "WIN" && monitorEndpointIsMinimized(endpoint, worker, state)) row.classList.add("monitor-worker-minimized");

      if (worker?.__kind === "TAB" && monitorEndpointIsMinimized(endpoint, worker, state)) row.classList.add("monitor-worker-parent-minimized");

      const resolvedLocation = monitorEndpointLocation(worker, state);

      rememberMonitorWorkerPlacement(worker, state, resolvedLocation);

      const hwnd = monitorResolvedWorkerHwnd(worker, state, resolvedLocation);
      if (monitorIsActionableCodexResource(worker)) {
        const codexProfileId = monitorCodexResourceProfile(worker);
        const runtimeState = String(worker?.llm_runtime_state || worker?.status || "OFFLINE").toUpperCase();
        row.classList.add("monitor-worker-resource-actionable");
        row.dataset.resourceAction = "codex";
        row.dataset.codexProfileId = codexProfileId;
        row.title = `${String(worker?.name || worker?.display_name || "CODEX")} · ${runtimeState} · 더블클릭: 열기`;
        row.addEventListener("dblclick", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          await activateMonitorCodexResource(worker, row);
        });
      }

      if (hwnd) {

        row.dataset.hwnd = hwnd;

        if (monitorHoveredHwnd === hwnd && !monitorSelectedHwnds.has(hwnd)) row.classList.add("monitor-worker-row-hovered");

        const rowDesktopId = String(resolvedLocation?.desktopId || "");

        if (rowDesktopId) row.dataset.desktopId = rowDesktopId;

        row.addEventListener("pointerdown", (event) => { if (monitorStructureOpen) return; beginMonitorWorkerRowPointerDrag(event); });

        if (group.key === "chatgpt" && conversationKey && conversationGroup?.count === 1) {

          const structureNode = monitorStructureNodeFromWorker(worker, state);

          row.draggable = Boolean(monitorStructureOpen && structureNode);

          if (row.draggable) row.classList.add("monitor-structure-draggable");

          row.addEventListener("dragstart", (event) => {
            if (!monitorStructureOpen || !structureNode) { event.preventDefault(); return; }
            monitorStructureUseNodeDragGhost(event);
            const text=JSON.stringify(structureNode); event.dataTransfer.effectAllowed="copy";
            event.dataTransfer.setData("application/x-dwm-structure-node",text); event.dataTransfer.setData("text/plain",text);
          });

        }

        row.addEventListener("click", (event) => { if (Date.now() < monitorWorkerRowSuppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);

        // Role styling is derived only from the current ACT authoritative role binding.

        row.classList.add("monitor-worker-locatable");

        row.removeAttribute("title");

        row.addEventListener("click", (event) => applyMonitorWindowHighlight(hwnd, (monitorSelectedHwnds.has(hwnd) || event.ctrlKey) ? { toggle: true } : {}));

        row.addEventListener("dblclick", async (event) => {

          event.preventDefault();

          event.stopPropagation();

          applyMonitorWindowHighlight(hwnd);

          row.classList.add("monitor-worker-switch-pending");

          try {

            const freshState = await monitorNative({ type: "getVirtualDesktops" });

            if (!freshState?.ok) throw new Error(freshState?.error || "데스크톱 상태 확인 실패");

            const desktopIds = Array.isArray(freshState.desktopIds) ? freshState.desktopIds : [];

            let index = -1;

            for (let i = 0; i < desktopIds.length; i += 1) {

              const scan = await monitorNative({ type: "getDesktopWindowHandles", desktopId: desktopIds[i], includeMonitorWindows: "true" });

              if (scan?.ok && Array.isArray(scan.hwnds) && scan.hwnds.map(String).includes(String(hwnd))) { index = i; break; }

            }

            if (index < 0) throw new Error("이 창의 실제 데스크톱 위치를 확인하지 못함");

            renderVirtualDesktops(freshState);

            const result = await monitorNative({ type: "switchVirtualDesktop", index });

            if (!result?.ok) throw new Error(result?.error || "데스크톱 전환 실패");

            renderVirtualDesktops(result);

            selectVirtualDesktopPreview(index);

            applyMonitorWindowHighlight(hwnd);

          } catch (error) { setMonitorStatus(`데스크톱 전환 실패 · ${error?.message || error}`, false); }

          finally { setTimeout(() => row.classList.remove("monitor-worker-switch-pending"), 350); }

        });

      }

      if (monitorHighlightedHwnd && hwnd === monitorHighlightedHwnd) row.classList.add("monitor-worker-selected");

      const workState = document.createElement("span");

      const work = resolveWorkerWorkState(worker, state);

      const liveEndpoint = Boolean(hwnd) && worker?.__kind === "WIN" && connection === "connected" ? monitorOpenEndpointForHwnd(hwnd, state) : null;
      const visualConversationKey = String(liveEndpoint?.conversation_key || conversationKey || ((hwnd && monitorWindowDesktopLocations.get(String(hwnd))?.conversationKey) || "")).trim();

      const liveWorking = Boolean(hwnd) && worker?.__kind === "WIN" && connection === "connected" && monitorHwndIsGenerating(hwnd, state);
      if (liveWorking) monitorWorkingByHwnd.add(hwnd);
      row.classList.toggle("monitor-worker-working", liveWorking);

      if (visualConversationKey && liveWorking) { monitorWorkedConversationKeys.add(visualConversationKey); monitorAcknowledgedPostWork.delete(visualConversationKey); }

      const postWorkWaiting = Boolean(visualConversationKey) && monitorIsPostWorkWaiting(work, visualConversationKey) && !liveWorking;

      const alertDetail = postWorkWaiting ? monitorChatAlertDetail(visualConversationKey) : null;

      if (hwnd && postWorkWaiting && connection === "connected") monitorPausedByHwnd.add(hwnd);

      const visualWork = liveWorking ? "running" : (monitorIsActivelyWorking(work) ? "" : work); const attentionEndpoint = endpointForMonitorWorker(worker, state); const directAttention = monitorDirectEndpointUserAttention(attentionEndpoint); const attentionRaw = directAttention || attentionEndpoint?.telemetry?.user_attention || attentionEndpoint?.metadata?.user_attention || attentionEndpoint?.metadata?.telemetry?.user_attention || null; const userAttentionDetail = monitorUserAttentionVisualDetail(attentionRaw); const visual = monitorWorkIconState(visualWork, connection, userAttentionDetail || alertDetail);

      workState.className = "monitor-work-state";

      if (visual.tone) workState.classList.add(`monitor-alert-tone-${visual.tone}`);

      globalThis.MonitorStatusIcon?.render?.(workState, visual);

      workState.title = userAttentionDetail ? userAttentionDetail.label : `${visual.label} · ${work}`;

      workState.setAttribute("aria-label", workState.title);

      if (alertDetail && visualConversationKey) workState.addEventListener("click", (event) => {

        event.preventDefault();

        event.stopPropagation();

        monitorAcknowledgePostWork(visualConversationKey, hwnd || "");

        if (hwnd) monitorPausedByHwnd.delete(String(hwnd));

        if (monitorLastAiState) renderWorkers(monitorLastAiState);

      });

      const currentActRole=String(projectedActNode?.role||"").toUpperCase();

      const currentActExemption=projectedActNode?.exemption||null;
      row.classList.toggle("monitor-worker-exempt",Boolean(currentActExemption||currentActRole==="EXEMPT"));

      if(conversationKey&&projectedActNode&&(currentActExemption||currentActRole==="EXEMPT"||MONITOR_ROLE_ADMIN_ROLES.includes(currentActRole))){

        const off=document.createElement("button"); off.type="button"; off.className=`monitor-worker-off monitor-worker-off-${currentActExemption||currentActRole==="EXEMPT"?"exempt":currentActRole.toLowerCase().replaceAll("_","-")}`; off.textContent="OFF"; off.title=currentActExemption||currentActRole==="EXEMPT"?"열외 해제 → 일반 WORKER":`${monitorRoleAdminShort(currentActRole)} 해제 → 일반 WORKER`; off.addEventListener("click",(event)=>{event.preventDefault();event.stopPropagation();void monitorTurnWorkerOff(worker,state);}); status.append(off);

      }

      status.append(workState);

      row.append(identity, status);

      rows.append(row);

    }

    section.append(header, rows);

    nextWorkerDom.append(section);

  }

  for (const preview of document.querySelectorAll(".monitor-desktop-thumb-window, .monitor-window-preview")) {

    const hwnd = preview.dataset.hwnd || "";

    applyPersistentMonitorRoleClass(preview, hwnd);

    syncMonitorPauseOverlay(preview, hwnd);

  }

  monitorWorkers.replaceChildren(nextWorkerDom);

  if(monitorClosedRecoveryMenu){monitorClosedRecoveryMenu.hidden=!monitorClosedConversationPickerOpen;if(monitorClosedConversationPickerOpen)monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(state));}

}

function positionMonitorTrashRecoveryMenu(){

  if(!monitorClosedRecoveryMenu||!monitorNodeTrash)return; const r=monitorNodeTrash.getBoundingClientRect();

  const width=Math.min(760,Math.max(420,window.innerWidth-24)); const left=Math.max(12,Math.min(window.innerWidth-width-12,r.right-width));

  const bottom=Math.max(12,window.innerHeight-r.top+8); const available=Math.max(180,r.top-18);

  monitorClosedRecoveryMenu.style.width=`${width}px`; monitorClosedRecoveryMenu.style.left=`${left}px`; monitorClosedRecoveryMenu.style.right="auto"; monitorClosedRecoveryMenu.style.top="auto"; monitorClosedRecoveryMenu.style.bottom=`${bottom}px`; monitorClosedRecoveryMenu.style.height=`${available}px`; monitorClosedRecoveryMenu.style.setProperty("max-height",`${available}px`,"important");

}

if (monitorNodeTrash && monitorClosedRecoveryMenu) {

  monitorNodeTrash.style.cursor="pointer";

  monitorNodeTrash.addEventListener("click",(event)=>{if(monitorNodeTrash.classList.contains("monitor-node-trash-drop-target")||monitorNodeTrash.classList.contains("monitor-node-trash-drop-success"))return;event.stopPropagation();monitorClosedConversationPickerOpen=!monitorClosedConversationPickerOpen;monitorClosedRecoveryMenu.hidden=!monitorClosedConversationPickerOpen;if(monitorClosedConversationPickerOpen){positionMonitorTrashRecoveryMenu();if(monitorLastAiState)monitorClosedRecoveryMenu.replaceChildren(renderMonitorClosedConversationRecoveryPanel(monitorLastAiState));}});

  monitorClosedRecoveryMenu.addEventListener("pointerdown",()=>{clearTimeout(monitorWorkerPointerReleaseTimer);monitorWorkerPointerInteractionActive=true;},true);

  monitorClosedRecoveryMenu.addEventListener("click",()=>settleMonitorWorkerPointerInteraction(),true);

  window.addEventListener("resize",()=>{if(monitorClosedConversationPickerOpen)positionMonitorTrashRecoveryMenu();});

  document.addEventListener("pointerdown",(event)=>{if(!monitorClosedConversationPickerOpen)return;if(event.target.closest?.("#monitorNodeTrash,#monitorClosedRecoveryMenu"))return;monitorClosedConversationPickerOpen=false;monitorClosedRecoveryMenu.hidden=true;},true);

}

initializeMonitorWorkerOrderStorage();

const monitorExtensionReload = document.getElementById("monitorExtensionReload");
const monitorRccReload = document.getElementById("monitorRccReload");
const monitorBctRecover = document.getElementById("monitorBctRecover");
const monitorMcpTunnelRecover = document.getElementById("monitorMcpTunnelRecover");
const monitorBctControlRefresh = document.getElementById("monitorBctControlRefresh");

const monitorActRestart = document.getElementById("monitorActRestart");

const monitorNodeSync = document.getElementById("monitorNodeSync");

const monitorBctNodeSummary = document.getElementById("monitorBctNodeSummary");
const monitorBctNodesRefresh = document.getElementById("monitorBctNodesRefresh");
const monitorBctShell = globalThis.MonitorBctShell?.create?.();
const monitorWindowHwndContract = globalThis.MonitorWindowHwndContract?.create?.();
const monitorMinimizedNodeBadgeContract = globalThis.MonitorMinimizedNodeBadgeContract;
// Null means BCT not yet observed; [] means BCT observed an empty node list.
let monitorBctWindowNodesCache = null;
let monitorBctDraggedNodeKey = "";
let monitorBctDragGhost = null;
let monitorBctPointerDrag = null;
let monitorBctNativePreviewToken = "";
let monitorBctNativePreviewSequence = 0;

function stopMonitorBctNativePreview() {
  const token = monitorBctNativePreviewToken;
  monitorBctNativePreviewToken = "";
  if (token) void monitorNative({ type:"monitorDragPreviewStop", token }).catch(() => {});
}

let monitorBctNodeReorderPending = false;
let monitorBctCurrentSessionWindowHwnd = new Map();
let monitorBctDisplayWindowHwnd = new Map();
let monitorBctBrowserWindows = new Map();
let monitorBctWindowNodeRefreshBusy = false;
let monitorMinimizedBadgeConvergenceTimer = 0;
let monitorBctProjectionGeneration = 0;
let monitorBctProjectionConvergenceTimer = 0;
let monitorBctProjectionConvergenceKey = "";
let monitorBctProjectionConvergenceAttempt = 0;
let monitorBctProjectionConvergenceInflight = false;
let monitorBctThumbnailProjectionAttemptKeys = new Set();
const MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS = Object.freeze([0, 450, 1400]);

function scheduleMonitorMinimizedBadgeConvergence(hwnd) {
  const key = String(hwnd || "").trim();
  if (!key || !Array.isArray(monitorBctWindowNodesCache)) return;
  if (monitorMinimizedBadgeConvergenceTimer) return;
  monitorMinimizedBadgeConvergenceTimer = setTimeout(async () => {
    monitorMinimizedBadgeConvergenceTimer = 0;
    // A BCT-initiated minimize can arrive before the Native identity snapshot.
    // Reconcile once; this is deliberately bounded, not a background poll.
    await refreshMonitorBctBrowserWindowGeometry();
    await refreshMonitorIdentityIndex(monitorLastAiState, true).catch(() => false);
    refreshMonitorBctCurrentSessionWindowHwnd();
    refreshMonitorBctDisplayWindowHwnd();
    syncMonitorMinimizedNodeBadges(monitorLastAiState);
  }, 250);
}
if (monitorWorkers) monitorWorkers.dataset.columns = "3";

function resetMonitorBctProjectionConvergence() {
  monitorBctProjectionGeneration += 1;
  monitorBctThumbnailProjectionAttemptKeys = new Set();
  monitorBctProjectionConvergenceKey = "";
  monitorBctProjectionConvergenceAttempt = 0;
  if (monitorBctProjectionConvergenceTimer) {
    clearTimeout(monitorBctProjectionConvergenceTimer);
    monitorBctProjectionConvergenceTimer = 0;
  }
}

async function refreshMonitorBctThumbnailProjectionForDesktop(desktopId) {
  if (!Array.isArray(monitorBctWindowNodesCache) || !monitorBctWindowNodesCache.length) return false;

  // Native thumbnail capture and the RCC/Chrome snapshot arrive independently.
  // Resolve once while this desktop's HWND geometry is fresh so the semantic
  // N-label is attached to the real browser rectangle rather than to a node card.
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  if (!monitorBctProjectionHasUnresolvedLineage()) return true;

  const chromeLocations = [...monitorWindowDesktopLocations.values()].filter((location) =>
    String(location?.desktopId || "") === String(desktopId || "") &&
    String(location?.className || "") === "Chrome_WidgetWin_1" &&
    Number(location?.width) > 0 && Number(location?.height) > 0
  );
  if (!chromeLocations.length) return false;

  const locationKey = chromeLocations.map((location) =>
    `${location.hwnd}:${location.left}:${location.top}:${location.width}:${location.height}:${location.iconic ? 1 : 0}`
  ).sort().join(",");
  const attemptKey = `${monitorBctProjectionGeneration}:${desktopId}:${locationKey}`;
  if (monitorBctThumbnailProjectionAttemptKeys.has(attemptKey)) return false;
  monitorBctThumbnailProjectionAttemptKeys.add(attemptKey);
  if (monitorBctThumbnailProjectionAttemptKeys.size > 24) {
    monitorBctThumbnailProjectionAttemptKeys = new Set([attemptKey]);
  }

  await refreshMonitorBctBrowserWindowGeometry();
  refreshMonitorBctCurrentSessionWindowHwnd();
  refreshMonitorBctDisplayWindowHwnd();
  return !monitorBctProjectionHasUnresolvedLineage();
}

function monitorBctProjectionHasUnresolvedLineage() {
  return Array.isArray(monitorBctWindowNodesCache) && monitorBctWindowNodesCache.some((node) =>
    !monitorDisplayHwndForBrowserWindowId(node.windowId, monitorLastAiState, node.instanceId, node.sessionId)
  );
}

function scheduleMonitorBctProjectionConvergence(reason = "state-ready") {
  if (!Array.isArray(monitorBctWindowNodesCache) || !monitorBctWindowNodesCache.length ||
      !Array.isArray(monitorDesktopState?.desktopIds) || !monitorDesktopState.desktopIds.length ||
      !monitorBctProjectionHasUnresolvedLineage()) return;
  const key = [
    monitorBctProjectionGeneration,
    monitorDesktopState.desktopIds.join(","),
    ...monitorBctWindowNodesCache.map((node) =>
      `${node.instanceId}:${node.sessionId}:${node.windowId}:${node.conversationKey}:${node.active ? 1 : 0}:${node.instanceState}`
    ),
  ].join("|");
  if (key !== monitorBctProjectionConvergenceKey) {
    monitorBctProjectionConvergenceKey = key;
    monitorBctProjectionConvergenceAttempt = 0;
  }
  if (monitorBctProjectionConvergenceTimer || monitorBctProjectionConvergenceInflight ||
      monitorBctProjectionConvergenceAttempt >= MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS.length) return;
  const delay = MONITOR_BCT_PROJECTION_CONVERGENCE_DELAYS_MS[monitorBctProjectionConvergenceAttempt];
  monitorBctProjectionConvergenceTimer = setTimeout(async () => {
    monitorBctProjectionConvergenceTimer = 0;
    monitorBctProjectionConvergenceAttempt += 1;
    monitorBctProjectionConvergenceInflight = true;
    try {
      await refreshMonitorBctBrowserWindowGeometry();
      await refreshMonitorIdentityIndex(monitorLastAiState, true).catch(() => false);
      refreshMonitorBctCurrentSessionWindowHwnd();
      refreshMonitorBctDisplayWindowHwnd();
      renderMonitorBctWindowNodes(monitorBctWindowNodesCache);
      syncMonitorAllDesktopThumbnailNodeBadges();
    } finally {
      monitorBctProjectionConvergenceInflight = false;
    }
    if (monitorBctProjectionHasUnresolvedLineage()) scheduleMonitorBctProjectionConvergence(reason);
  }, delay);
}

function monitorBctRenameErrorText(error) {
  const raw = String(error?.message || error || "").trim();
  if (/RESOURCE_ALREADY_CLAIMED|UNKNOWN|OUTCOME_UNVERIFIED/i.test(raw)) {
    return "이 대화의 이전 이름 변경 결과가 아직 미확정이라 안전상 다시 바꾸지 않았습니다.";
  }
  return raw ? `변경되지 않았습니다 · ${raw}` : "이름을 변경하지 못했습니다.";
}
let monitorBctRenameEditor = null;

function closeMonitorBctRenameEditor() {
  if (!monitorBctRenameEditor || monitorBctRenameEditor.busy) return;
  monitorBctRenameEditor.overlay.remove();
  monitorBctRenameEditor = null;
}

function openMonitorTrashRecovery() {
  if (!monitorNodeTrash || !monitorClosedRecoveryMenu) return;
  if (!monitorClosedConversationPickerOpen) monitorNodeTrash.click();
}

function monitorBctRoleTagsFromText(value) {
  return [...new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean))].slice(0, 24);
}

function monitorBctNodeRoleSummary(node) {
  const tags = Array.isArray(node?.roleTags)
    ? node.roleTags.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  if (!tags.length) return "";
  const shown = tags.slice(0, 3);
  return `${shown.join(" · ")}${tags.length > shown.length ? ` · +${tags.length - shown.length}` : ""}`;
}

function monitorBctNodeLocationText(node, desktopPosition) {
  const location = desktopPosition >= 0 ? `D${desktopPosition + 1}` : "위치 확인 중";
  const roles = monitorBctNodeRoleSummary(node);
  const reasoning = String(node?.reasoningLevel || "").trim();
  return [location, roles, reasoning].filter(Boolean).join(" · ");
}

