//@@FN_START:monitorAcknowledgePostWork
function monitorAcknowledgePostWork(conversationKey, hwnd="") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const reportId=String(monitorAuthoritativeReportByConversation.get(key)||"").trim();

  if(reportId)monitorAcknowledgedReportIds.add(reportId);

  monitorAcknowledgedPostWork.add(key); monitorPostWorkAlerts.delete(key); monitorChatAlertDetails.delete(key);

  if(hwnd)monitorPausedByHwnd.delete(String(hwnd));

  monitorPostWorkPersist();

  const at=Date.now(); monitorSharedRuntimeAckAt.set(key,at); void monitorPublishSharedRuntime("ack",key,{},at);

}
//@@FN_END:monitorAcknowledgePostWork

//@@FN_START:monitorAcknowledgePostWorkForHwnd
function monitorAcknowledgePostWorkForHwnd(hwnd) {

  const target=String(hwnd||"").trim(); if(!target)return false;

  const location=monitorWindowDesktopLocations.get(target);

  const key=String(location?.conversationKey||"").trim(); if(!key)return false;

  monitorAcknowledgePostWork(key,target);

  for(const node of document.querySelectorAll(`[data-hwnd="${target}"]`))node.classList.remove("monitor-window-paused");

  for(const overlay of document.querySelectorAll(`.monitor-window-pause-overlay[data-hwnd="${target}"]`))overlay.remove();
  return true;

  if(monitorObservedState.snapshot())renderWorkers(monitorObservedState.snapshot());

  return true;

}
//@@FN_END:monitorAcknowledgePostWorkForHwnd

//@@FN_START:monitorAuthoritativeAlertDetail
function monitorAuthoritativeAlertDetail(report, task = null) {

  const verdict=String(report?.final_verdict||report?.status||"").toUpperCase();

  const reportText=[report?.summary,report?.result,report?.detail,report?.message,report?.completion_report?.summary,report?.completion_report?.result,report?.completion_report?.detail].filter(Boolean).map(String).join(" ").toUpperCase();

  if (/\b(FAIL|FAILED|BLOCKED|ERROR|FATAL|BROKEN|UNRECOVERABLE)\b|실패|오류|중단|차단/.test(reportText)) return {warning:true,tone:"failure",label:"중요 오류 / 실패 / BLOCKED"};

  if (/\b(NEEDS_REVIEW|WARNING|WARN|CAUTION|PARTIAL|DEGRADED|ATTENTION)\b|검토 필요|주의|경고|부분 성공|확인 필요/.test(reportText)) return {warning:true,tone:"review",label:"주의 / 검토 필요"};

  const taskStatus=String(task?.status||"").toUpperCase();
  if (["SUCCEEDED","COMPLETED","COMPLETE","DONE"].includes(taskStatus) && /\b(PASS|PASSED|SUCCESS|SUCCEEDED|COMPLETED|COMPLETE|DONE|VERIFIED|OK)\b|성공|완료|검증 통과|정상/.test(reportText)) return {activity:"complete",tone:"success",label:"작업 완료 · 창을 닫아도 됨"};

  if (["FAIL","FAILED","BLOCKED"].includes(verdict)) return {symbol:"!",tone:"failure",label:"실패 / 오류 / BLOCKED"};

  if (verdict==="NEEDS_REVIEW") return {symbol:"!",tone:"review",label:"검토 필요"};

  if (["PASS","COMPLETED","COMPLETE","DONE","SUCCEEDED"].includes(verdict)) return {symbol:"!",tone:"success",label:"성공 / PASS"};

  return {activity:"pause",tone:"general",label:"완료 보고 대기"};

}
//@@FN_END:monitorAuthoritativeAlertDetail

//@@FN_START:monitorCancelScheduledCompletionAlert
function monitorCancelScheduledCompletionAlert(conversationKey) {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const timer=monitorCompletionAlertTimers.get(key); if(timer)clearTimeout(timer);

  monitorCompletionAlertTimers.delete(key);

}
//@@FN_END:monitorCancelScheduledCompletionAlert

//@@FN_START:monitorChatAlertDetail
function monitorChatAlertDetail(conversationKey) {

  const key=String(conversationKey||"").trim(); return key&&monitorPostWorkAlerts.has(key)?(monitorChatAlertDetails.get(key)||{activity:"pause",tone:"general",label:"채팅 작업 완료"}):null;

}
//@@FN_END:monitorChatAlertDetail

//@@FN_START:monitorConversationIsGenerating
function monitorConversationIsGenerating(conversationKey, state) {
  return monitorNodeGenerationAPI.conversationIsGenerating(conversationKey, state);
}
//@@FN_END:monitorConversationIsGenerating

//@@FN_START:monitorConversationUserAttentionDetail
function monitorConversationUserAttentionDetail(conversationKey,state=monitorObservedState.snapshot()) {
  const key=String(conversationKey||"").trim();
  if(!key)return null;
  const direct=monitorDirectGenerationByConversation.get(key)?.userAttention||null;
  const endpoints=Array.isArray(state?.endpoints)?state.endpoints:[];
  const endpoint=endpoints.find((item)=>String(item?.presence_state||"").toUpperCase()==="OPEN"&&String(item?.conversation_key||"").trim()===key)
    ||endpoints.find((item)=>String(item?.conversation_key||"").trim()===key)
    ||null;
  const raw=direct||endpoint?.telemetry?.user_attention||endpoint?.metadata?.user_attention||endpoint?.metadata?.telemetry?.user_attention||null;
  return monitorUserAttentionVisualDetail(raw);
}
//@@FN_END:monitorConversationUserAttentionDetail

//@@FN_START:monitorCreateChatCompletionAlert
function monitorCreateChatCompletionAlert(conversationKey, attentionCue="", completionCue="general") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  const attention=String(attentionCue||"").toLowerCase();

  const cue=String(completionCue||"general").toLowerCase();

  // Chat generation finishing is a pause/notice, never evidence that project
  // work is close-safe. Only an authoritative terminal report emits complete.
  const detail=attention==="action"?{warning:true,tone:"action",label:"사용자 조치 필요"}:attention==="input"?{warning:true,tone:"input",label:"추가 입력 필요"}:attention==="question"?{warning:true,tone:"question",label:"사용자 확인/선택 대기"}:cue==="failure"?{warning:true,tone:"failure",label:"실패 / 오류"}:cue==="review"?{warning:true,tone:"review",label:"검토 필요"}:{activity:"pause",tone:cue==="success"?"success":"general",label:cue==="success"?"응답 완료 · 후속 확인 대기":"채팅 작업 완료"};

  monitorPostWorkAlerts.add(key); monitorChatAlertDetails.set(key,detail); monitorAcknowledgedPostWork.delete(key); monitorPostWorkPersist();

  const at=Date.now(); monitorSharedRuntimeAlertAt.set(key,at); void monitorPublishSharedRuntime("alert",key,{activity:detail.activity||"",warning:detail.warning===true,tone:detail.tone,label:detail.label},at);

}
//@@FN_END:monitorCreateChatCompletionAlert

//@@FN_START:monitorDecodeSharedGenerationAttention
function monitorDecodeSharedGenerationAttention(row){
  const raw=String(row?.attentionCue||"");
  const directKind=String(row?.userAttention?.kind||"").trim().toUpperCase();
  if(["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(directKind)){
    return {attentionCue:raw.startsWith(MONITOR_SHARED_USER_ATTENTION_PREFIX)?"":raw,userAttention:{kind:directKind,label:String(row?.userAttention?.label||"사용자 조치 필요")}};
  }
  if(!raw.startsWith(MONITOR_SHARED_USER_ATTENTION_PREFIX))return {attentionCue:raw,userAttention:null};
  const encoded=raw.slice(MONITOR_SHARED_USER_ATTENTION_PREFIX.length), splitAt=encoded.indexOf("|");
  const kind=String(splitAt>=0?encoded.slice(0,splitAt):encoded).trim().toUpperCase();
  if(!["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(kind))return {attentionCue:raw,userAttention:null};
  let label="사용자 조치 필요";
  if(splitAt>=0){
    const rawLabel=encoded.slice(splitAt+1);
    try{label=decodeURIComponent(rawLabel)||label;}catch(_){label=rawLabel||label;}
  }
  return {attentionCue:"",userAttention:{kind,label}};
}
//@@FN_END:monitorDecodeSharedGenerationAttention

//@@FN_START:monitorEncodeSharedUserAttention
function monitorEncodeSharedUserAttention(attentionCue,userAttention){
  const cue=String(attentionCue||"");
  const kind=String(userAttention?.kind||"").trim().toUpperCase();
  if(!["NEW_CHAT_REQUIRED","RETRY_REQUIRED","RECOVERY_REQUIRED"].includes(kind))return cue;
  const label=String(userAttention?.label||"사용자 조치 필요");
  return `${MONITOR_SHARED_USER_ATTENTION_PREFIX}${kind}|${encodeURIComponent(label)}`;
}
//@@FN_END:monitorEncodeSharedUserAttention

//@@FN_START:monitorHwndIsGenerating
function monitorHwndIsGenerating(hwnd, state) {
  return monitorNodeGenerationAPI.hwndIsGenerating(hwnd, state);
}
//@@FN_END:monitorHwndIsGenerating

//@@FN_START:monitorHwndUserAttentionDetail
function monitorHwndUserAttentionDetail(hwnd,state=monitorObservedState.snapshot()) {
  const conversationKey=monitorVisualConversationForHwnd(String(hwnd||""),state);
  return monitorConversationUserAttentionDetail(conversationKey,state);
}
//@@FN_END:monitorHwndUserAttentionDetail

//@@FN_START:monitorIsPostWorkWaiting
function monitorIsPostWorkWaiting(work, conversationKey) {

  const key = String(conversationKey || "").trim();

  return Boolean(key && monitorPostWorkAlerts.has(key));

}
//@@FN_END:monitorIsPostWorkWaiting

//@@FN_START:monitorLocalLlmActivityText
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
//@@FN_END:monitorLocalLlmActivityText

//@@FN_START:monitorPostWorkPersist
function monitorPostWorkPersist() {

  if (!monitorPostWorkStorageReady) return;

  if (monitorPostWorkPersistTimer) clearTimeout(monitorPostWorkPersistTimer);

  monitorPostWorkPersistTimer = setTimeout(() => {

    monitorPostWorkPersistTimer = 0;

    chrome.storage.local.set({ [MONITOR_POST_WORK_STORAGE_KEY]: { worked:[...monitorWorkedConversationKeys], acknowledged:[...monitorAcknowledgedPostWork], acknowledgedReports:[...monitorAcknowledgedReportIds], alerts:[...monitorPostWorkAlerts], details:Object.fromEntries(monitorChatAlertDetails), lastObservedAt:monitorPostWorkLastObservedAt } });

  }, 120);

}
//@@FN_END:monitorPostWorkPersist

//@@FN_START:monitorScheduleChatCompletionAlert
function monitorScheduleChatCompletionAlert(conversationKey, attentionCue="", completionCue="general") {

  const key=String(conversationKey||"").trim(); if(!key)return;

  monitorCancelScheduledCompletionAlert(key);

  const timer=setTimeout(()=>{

    monitorCompletionAlertTimers.delete(key);

    if(monitorDirectConversationGenerationState(key)===true)return;

    const live=(Array.isArray(monitorObservedState.snapshot()?.endpoints)?monitorObservedState.snapshot().endpoints:[]).filter((endpoint)=>String(endpoint?.conversation_key||"").trim()===key&&String(endpoint?.presence_state||"").toUpperCase()==="OPEN");

    if(live.some((endpoint)=>monitorEndpointGenerationIsActive(endpoint)))return;

    monitorGenerationSeen.set(key,false);

    monitorCreateChatCompletionAlert(key,attentionCue,completionCue);

  },MONITOR_COMPLETION_STABLE_MS);

  monitorCompletionAlertTimers.set(key,timer);

}
//@@FN_END:monitorScheduleChatCompletionAlert

//@@FN_START:monitorSyncAuthoritativeCompletionAlerts
function monitorSyncAuthoritativeCompletionAlerts(state) {
  let renderChanged = false;
  const tasks=Array.isArray(state?.tasks)?state.tasks:[];
  const terminal=new Set(["SUCCEEDED","COMPLETED","COMPLETE","DONE","FAILED","BLOCKED","NEEDS_REVIEW"]);
  const authoritative=new Map();
  const pendingIds=new Set();

  for (const report of monitorPendingDurableReports) {
    const reportId=String(report?.report_id||"").trim(); if(reportId)pendingIds.add(reportId);
    const task=tasks.find((item)=>String(item?.id||"").trim()===String(report?.task_id||"").trim());
    if (!task || !terminal.has(String(task?.status||"").toUpperCase()) || !monitorReportMatchesTask(report,task)) continue;
    const key=monitorAuthoritativeConversationForTask(task,state,report); if(!key)continue;
    const previous=authoritative.get(key);
    if(!previous || monitorGhostTime(report?.created_at)>monitorGhostTime(previous?.report?.created_at)) authoritative.set(key,{report,detail:monitorAuthoritativeAlertDetail(report,task)});
  }

  for (const reportId of [...monitorAcknowledgedReportIds]) if(!pendingIds.has(reportId)) monitorAcknowledgedReportIds.delete(reportId);
  monitorAuthoritativeReportByConversation.clear();

  for (const [key,item] of authoritative) {
    const reportId=String(item.report?.report_id||"").trim();
    if(reportId)monitorAuthoritativeReportByConversation.set(key,reportId);
    if(reportId && monitorAcknowledgedReportIds.has(reportId)) continue;
    if(monitorConversationIsGenerating(key,state)) continue;
    const direct=monitorDirectGenerationByConversation.get(key);
    if(direct?.generating===false && Date.now()-Number(direct.at||0)<MONITOR_COMPLETION_STABLE_MS) continue;

    const previousDetail=monitorChatAlertDetails.get(key);
    const nextDetail=item.detail||{};
    if (
      !monitorPostWorkAlerts.has(key)
      || monitorAcknowledgedPostWork.has(key)
      || String(previousDetail?.symbol||"")!==String(nextDetail?.symbol||"")
      || String(previousDetail?.tone||"")!==String(nextDetail?.tone||"")
      || String(previousDetail?.label||"")!==String(nextDetail?.label||"")
    ) renderChanged=true;

    monitorPostWorkAlerts.add(key);
    monitorChatAlertDetails.set(key,nextDetail);
    monitorAcknowledgedPostWork.delete(key);
  }

  // Keep local completion/attention alerts until the user acknowledges them.
  // Missing ACT durable reports must not erase a valid ! or ? alert.
  monitorPostWorkPersist();
  return renderChanged;
}
//@@FN_END:monitorSyncAuthoritativeCompletionAlerts

//@@FN_START:monitorSyncChatCompletionTransitions
function monitorSyncChatCompletionTransitions(state) {
  let renderChanged = false;
  for (const endpoint of Array.isArray(state?.endpoints)?state.endpoints:[]) {
    const key=String(endpoint?.conversation_key||"").trim(); if(!key||String(endpoint?.presence_state||"").toUpperCase()!=="OPEN")continue;
    const directState=monitorDirectConversationGenerationState(key);
    const generating=directState===true || monitorEndpointGenerationIsActive(endpoint);
    const previous=monitorGenerationSeen.get(key);

    if(generating){
      if (
        previous!==true
        || monitorPostWorkAlerts.has(key)
        || monitorChatAlertDetails.has(key)
        || monitorAcknowledgedPostWork.has(key)
      ) renderChanged=true;
      monitorCancelScheduledCompletionAlert(key);
      monitorGenerationSeen.set(key,true);
      monitorWorkedConversationKeys.add(key);
      monitorPostWorkAlerts.delete(key);
      monitorChatAlertDetails.delete(key);
      monitorAcknowledgedPostWork.delete(key);
      monitorPostWorkPersist();
      continue;
    }

    if(previous===true){
      renderChanged=true;
      monitorGenerationSeen.set(key,false);
      const direct=monitorDirectGenerationByConversation.get(key)||{};
      monitorScheduleChatCompletionAlert(key,direct.attentionCue||"",direct.completionCue||"general");
    } else if(previous===undefined) {
      // Initial idle observation is not proof of a newly completed response.
      monitorGenerationSeen.set(key,false);
    }
  }
  return renderChanged;
}
//@@FN_END:monitorSyncChatCompletionTransitions

//@@FN_START:monitorUserAttentionVisualDetail
function monitorUserAttentionVisualDetail(attentionRaw) {
  const kind=String(attentionRaw?.kind||"").trim().toUpperCase();
  if(kind==="RETRY_REQUIRED") return {warning:true,tone:"failure",label:String(attentionRaw?.label||"다시 시도 필요")};
  if(["NEW_CHAT_REQUIRED","RECOVERY_REQUIRED"].includes(kind)) return {warning:true,tone:"review",label:String(attentionRaw?.label||"사용자 조치 필요")};
  return null;
}
//@@FN_END:monitorUserAttentionVisualDetail

//@@FN_START:syncMonitorNonChatCountdown
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
//@@FN_END:syncMonitorNonChatCountdown

