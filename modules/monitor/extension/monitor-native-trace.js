// Event-driven, bounded metadata only: no request payloads or captured pixels.
(() => {
  const key='monitorNativeTrace.v1', events=[], pending=new Map();
  const session=Date.now().toString(36);
  let sequence=0, revision=0, writing=false, scheduled=false, ready=false, previous=null;
  const snapshot=()=>({session,events:events.slice(),pending:[...pending.values()]});
  const bounded=value=>String(value||'').slice(0,120);
  function summary(type=''){
    const expected=String(type||'');
    const matches=item=>!expected||String(item?.type||'')===expected;
    const now=Date.now();
    return Object.freeze({
      session,
      pending:[...pending.values()].filter(matches).slice(-8).map(item=>({
        id:item.id,host:bounded(item.host),type:bounded(item.type),age_ms:Math.max(0,now-Number(item.at||now))
      })),
      recent:events.filter(item=>matches(item)&&['end','error'].includes(item.kind)).slice(-8).map(item=>({
        at:Number(item.at||0),kind:bounded(item.kind),id:item.id,host:bounded(item.host),type:bounded(item.type),
        ms:Number(item.ms||0),ok:item.ok===true,engine:bounded(item.engine),error:bounded(item.error)
      }))
    });
  }
  function persist(){
    if(!ready||writing||scheduled)return;
    scheduled=true;
    queueMicrotask(async()=>{
      scheduled=false;writing=true;
      const saved=revision;
      try{await chrome.storage.session.set({[key]:snapshot()});}catch(_){}
      writing=false;
      if(saved!==revision)persist();
    });
  }
  function record(kind,fields={}){
    events.push({at:Date.now(),kind,...fields});
    if(events.length>128)events.shift();
    revision++;persist();
  }
  async function request(host,message,invoke){
    const id=++sequence,started=performance.now();
    const item={id,host,type:String(message?.type||''),at:Date.now()};
    pending.set(id,item);
    if(pending.size>128)pending.delete(pending.keys().next().value);
    record('begin',item);
    try{
      const result=await invoke();pending.delete(id);
      record('end',{id,host,type:item.type,ms:Math.round(performance.now()-started),ok:result?.ok===true,engine:bounded(result?.captureEngine),error:result?.ok===true?'':bounded(result?.error)});
      return result;
    }catch(error){
      pending.delete(id);record('error',{id,host,type:item.type,ms:Math.round(performance.now()-started),error:bounded(error?.message||error)});throw error;
    }
  }
  chrome.storage.session.get(key).then(data=>{previous=data?.[key]||null;}).catch(()=>{}).finally(()=>{ready=true;persist();});
  for(const kind of ['focus','blur','pagehide'])window.addEventListener(kind,()=>record(kind));
  globalThis.MonitorNativeTrace={request,record,summary,export:()=>JSON.stringify({current:snapshot(),previous},null,2)};
  record('loaded',{build:'20260924-orchestrator-pyramid-19'});
})();
