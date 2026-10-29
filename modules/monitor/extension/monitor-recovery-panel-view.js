// Recovery trash panel DOM owner: all mutating effects and persistence are injected.
// Renders exact conversation UUID rows and status, without Native/BCT/Chrome access.
(() => {
  "use strict";
  function create({document,ports}) {
    if (!document || !ports) throw new TypeError("RECOVERY_PANEL_PORTS_REQUIRED");
function render(state) {

  const panel=document.createElement("div"); panel.className="monitor-closed-conversation-panel monitor-trash-recovery-panel";

  const items=ports.recoveryItems(state);

  const makeHeader=(label,count,onClear,extras=[])=>{const head=document.createElement("div");head.className="monitor-trash-pane-header";const title=document.createElement("strong");title.textContent=`${label} (${count})`;const actions=document.createElement("span");actions.className="monitor-trash-pane-actions";for(const button of extras)if(button)actions.append(button);const clear=document.createElement("button");clear.type="button";clear.className="monitor-trash-clear-all";clear.textContent="다 비움";clear.disabled=!count;clear.addEventListener("click",(e)=>{e.stopPropagation();if(ports.confirm(`${label} 항목을 모두 비울까요?`))onClear();});actions.append(clear);head.append(title,actions);return head;};

  const recoveryWorkers=ports.workersForState(state||{});

  const recoveryWorkerByKey=new Map(recoveryWorkers.map((worker)=>[String(worker?.conversation_key||worker?.__endpoint?.conversation_key||"").trim(),worker]).filter(([key])=>key));

  const recoveryEndpoints=Array.isArray(state?.endpoints)?state.endpoints:[];

  const recoveryNodeStatus=(key,record=null)=>{

    key=String(key||"").trim();

    const endpoint=recoveryEndpoints.find((ep)=>String(ep?.conversation_key||"").trim()===key)||null;

    const open=String(endpoint?.presence_state||"").toUpperCase()==="OPEN";

    const worker=recoveryWorkerByKey.get(key)||null;

    const work=String(worker?ports.workerWorkState(worker,state):(record?.work_status||record?.task_status||"")).trim().toLowerCase();

    if(["running","working","busy","executing","in_progress"].includes(work))return {label:"처리 중",tone:"processing"};

    if(["waiting_resource","waiting","paused","queued","pending"].includes(work))return {label:"대기 중",tone:"waiting"};

    if(work==="unknown"||String(record?.outcome||record?.receipt_outcome||"").toUpperCase()==="UNKNOWN")
      return {label:"결과 미확정",tone:"attention"};
    if(["needs_review","failed","failure","blocked","recovery","recovery_pending","degraded"].includes(work))return {label:"확인 필요",tone:"attention"};

    if(["succeeded","completed","complete","done"].includes(work))return {label:"완료",tone:"complete"};

    if(open)return {label:"활동 중",tone:"active"};

    return {label:"닫힘",tone:"closed"};

  };

  const appendRecoveryStatus=(row,key,record=null)=>{const status=recoveryNodeStatus(key,record);const badge=document.createElement("span");badge.className=`monitor-trash-node-status monitor-trash-node-status-${status.tone}`;badge.textContent=status.label;badge.title=`현재 상태: ${status.label}`;row.append(badge);};

  const noteRecords=[...ports.trashedNotes().values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const notePane=document.createElement("section");notePane.className="monitor-trash-pane monitor-trash-note-pane";notePane.append(makeHeader("삭제된 메모",noteRecords.length,ports.clearNotes));const noteScroll=document.createElement("div");noteScroll.className="monitor-trash-pane-scroll";

  if(!noteRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";noteScroll.append(empty);}else for(const note of noteRecords){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-note-row";const info=document.createElement("div");info.className="monitor-closed-conversation-info monitor-trash-note-info";const noteTitle=document.createElement("strong");noteTitle.textContent=note.title||ports.noteTitle(note.body)||"메모";const lines=String(note.body||"").split(/\r?\n/);const firstLineIndex=lines.findIndex((line)=>line.trim());const notePreview=document.createElement("span");notePreview.textContent=(firstLineIndex>=0?lines.slice(firstLineIndex+1).join(" "):"").replace(/\s+/g," ").trim()||"내용 없음";info.append(noteTitle,notePreview);const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();ports.restoreNote(note.id);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();ports.deleteNote(note.id);});row.append(info,restore,del);noteScroll.append(row);}notePane.append(noteScroll);panel.append(notePane);

  const renderTrashRows=(source,container)=>{const records=[...ports.trashRecords().values()].filter((x)=>String(x?.trash_source||"list")===source).sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));if(!records.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";container.append(empty);return;}for(const ghost of records){const row=document.createElement("div");row.className="monitor-closed-conversation-row monitor-trash-record-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=ports.previousLocation(ghost),context=ports.contextTitle(ghost),at=Number(ghost?.trashed_at_ms||0),scope=String(ghost?.network_name||"미소속"),roles=Array.isArray(ghost?.role_tags)&&ghost.role_tags.length?` · ${ghost.role_tags.join(", ")}`:"";info.textContent=`${String(ghost?.node_label||"")} ${context} · ${scope}${roles} · ${location} · ${at?new Date(at).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):"?"}`.trim();const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();ports.restoreTrash(ghost.conversation_key);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();row.classList.add("monitor-trash-removing");ports.after(()=>ports.deleteTrash(ghost.conversation_key),140);});row.append(info);if(source==="list")appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);container.append(row);}};

  const thumbRecords=[...ports.trashRecords().values()].filter((x)=>String(x?.trash_source||"list")==="thumbnail");

  const desktopRecords=[...ports.trashedDesktops().values()].sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const thumbPane=document.createElement("section");thumbPane.className="monitor-trash-pane monitor-trash-thumbnail-pane";thumbPane.append(makeHeader("삭제된 데스크",thumbRecords.length+desktopRecords.length,ports.clearThumbnail));const thumbScroll=document.createElement("div");thumbScroll.className="monitor-trash-pane-scroll";

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

      const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";restore.textContent="복구";restore.addEventListener("click",(e)=>{e.stopPropagation();void ports.restoreDesktop(item.id,restore);});

      const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(e)=>{e.stopPropagation();ports.deleteDesktop(item.id);});

      actions.append(restore,del);card.append(visual,actions);desktopGrid.append(card);

    }

    thumbScroll.append(desktopGrid);

  }

  renderTrashRows("thumbnail",thumbScroll);thumbPane.append(thumbScroll);

  let listRecords=[...ports.trashRecords().values()].filter((x)=>String(x?.trash_source||"list")!=="thumbnail").sort((a,b)=>Number(b?.trashed_at_ms||0)-Number(a?.trashed_at_ms||0));

  const combined=[...listRecords.map((x)=>({kind:"trash",item:x,at:Number(x?.trashed_at_ms||0)})),...items.map((x)=>({kind:"closed",item:x,at:Number(x?.closed_at_ms||x?.captured_at_ms||0)}))].sort((a,b)=>b.at-a.at);

  const kept=combined.slice(0,20), dropped=combined.slice(20), keptKeys=new Set(kept.map((x)=>String(x.item?.conversation_key||"")));

  if(dropped.length){const dropKeys=new Set(dropped.map((x)=>String(x.item?.conversation_key||"")).filter(Boolean));ports.pruneDropped(dropKeys);}

  listRecords=listRecords.filter((x)=>keptKeys.has(String(x?.conversation_key||"")));

  const visibleItems=kept.filter((x)=>x.kind==="closed").map((x)=>x.item);

  const convoCount=listRecords.length+visibleItems.length;

  const snapItems=(Array.isArray(ports.rebootSnapshot()?.items)?ports.rebootSnapshot().items:[]).filter((x)=>!ports.trashedKeys().has(String(x?.conversation_key||"")));

  const full=document.createElement("button");full.type="button";full.className="monitor-detached-restore monitor-recovery-full";full.textContent=`전체 복원${convoCount?` (${convoCount})`:""}`;full.disabled=!convoCount||ports.rebootRestoring();full.title="삭제된 노드 복구 목록 전체 복원";full.addEventListener("click",(e)=>{e.stopPropagation();void ports.restoreAll(full,listRecords,visibleItems);});

  const reboot=document.createElement("button");reboot.type="button";reboot.className="monitor-detached-restore monitor-recovery-full";reboot.textContent=`재부팅 복원${snapItems.length?` (${snapItems.length})`:""}`;reboot.disabled=!snapItems.length||ports.rebootRestoring();reboot.title="재부팅 전 저장된 대화만 복원";reboot.addEventListener("click",(e)=>{e.stopPropagation();void ports.restoreReboot(reboot);});

  const convoPane=document.createElement("section");convoPane.className="monitor-trash-pane monitor-trash-conversation-pane";convoPane.append(makeHeader("삭제된 노드",convoCount,ports.clearConversations,[full,reboot]));const convoScroll=document.createElement("div");convoScroll.className="monitor-trash-pane-scroll";

  if(listRecords.length)renderTrashRows("list",convoScroll);

  if(!visibleItems.length&&!listRecords.length){const empty=document.createElement("div");empty.className="monitor-trash-empty";empty.textContent="비어 있음";convoScroll.append(empty);}

  for(const ghost of visibleItems){const row=document.createElement("div");row.className="monitor-closed-conversation-row";row.dataset.recoveryKey=String(ghost?.conversation_key||"");const info=document.createElement("span");info.className="monitor-closed-conversation-info";const location=ports.previousLocation(ghost),context=ports.contextTitle(ghost);const created=Number(ghost?.first_seen_ms||0),closed=Number(ghost?.closed_at_ms||ghost?.captured_at_ms||0),rec=ports.contextRecord(String(ghost?.conversation_key||""));const displayContext=(rec.manual_locked&&rec.manual_title)||rec.context_title||ghost.meaningful_title||context;const source=ghost.recovery_source||"일반 종료";const fmtDateTime=(ms)=>ms?new Date(ms).toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).replace(/\. /g,".").replace(/\.$/,""):"?";const fmtTime=(ms)=>ms?new Date(ms).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",hour12:false}):"?";const sameDay=created&&closed&&new Date(created).toDateString()===new Date(closed).toDateString();info.textContent=`${location} · ${displayContext} · ${fmtDateTime(created)} - ${sameDay?fmtTime(closed):fmtDateTime(closed)}`;info.title=`이전 위치 ${location} · ${source}`;const restore=document.createElement("button");restore.type="button";restore.className="monitor-detached-restore";const restoring=ports.pendingRestores().has(String(ghost?.conversation_key||""));restore.textContent=restoring?"복구 중…":"복구";restore.disabled=restoring;restore.addEventListener("click",(event)=>{event.stopPropagation();void ports.restoreDetached(ghost,restore);});row.addEventListener("contextmenu",(event)=>{event.preventDefault();event.stopPropagation();const existing=row.querySelector(".monitor-recovery-details");if(existing){existing.remove();return;}panel.querySelectorAll(".monitor-recovery-details").forEach((node)=>node.remove());const detail=document.createElement("div");detail.className="monitor-recovery-details";const key=String(ghost?.conversation_key||"");for(const [label,value] of [["이전 위치",location],["제목",displayContext],["복구 출처",source],["생성",created?new Date(created).toLocaleString("ko-KR"):"알 수 없음"],["소멸",closed?new Date(closed).toLocaleString("ko-KR"):"알 수 없음"],["프로필",ghost.profile_id||"-"],["conversationKey",key||"-"]]){const line=document.createElement("div");line.className="monitor-recovery-detail-line";const k=document.createElement("b");k.textContent=label;const v=document.createElement("span");v.textContent=String(value);line.append(k,v);detail.append(line);}row.append(detail);});const del=document.createElement("button");del.type="button";del.className="monitor-trash-delete";del.textContent="삭제";del.addEventListener("click",(event)=>{event.stopPropagation();row.classList.add("monitor-trash-removing");ports.after(()=>ports.deleteRecovery(ghost.conversation_key),140);});row.append(info);appendRecoveryStatus(row,ghost.conversation_key,ghost);row.append(restore,del);convoScroll.append(row);}

  const contextRows = new Map([...convoScroll.querySelectorAll('.monitor-closed-conversation-row[data-recovery-key]')]
    .map(row => [row.dataset.recoveryKey, row]));
  for (const ghost of visibleItems) {
    const row = contextRows.get(String(ghost?.conversation_key || ''));
    if (row) row.append(ports.contextContinueButton(ghost));
  }
  const recoveryRowsByKey=new Map([...convoScroll.querySelectorAll(".monitor-closed-conversation-row[data-recovery-key]")].map((row)=>[String(row.dataset.recoveryKey||""),row]));for(const entry of kept){const key=String(entry?.item?.conversation_key||"");const row=recoveryRowsByKey.get(key);if(row)convoScroll.append(row);}convoPane.append(convoScroll);panel.append(convoPane,thumbPane);return panel;

}

    return Object.freeze({render});
  }
  globalThis.MonitorRecoveryPanelView=Object.freeze({create});
})();
