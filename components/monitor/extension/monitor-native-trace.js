// Event-driven, bounded metadata only: no request payloads or captured pixels.
(() => {
  const key='monitorNativeTrace.v1', events=[], pending=new Map();
  const session=Date.now().toString(36);
  let sequence=0, revision=0, writing=false, scheduled=false, ready=false, previous=null;
  const snapshot=()=>({session,events:events.slice(),pending:[...pending.values()]});
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
      record('end',{id,host,type:item.type,ms:Math.round(performance.now()-started),ok:result?.ok===true,engine:String(result?.captureEngine||'')});
      return result;
    }catch(error){
      pending.delete(id);record('error',{id,host,type:item.type,ms:Math.round(performance.now()-started)});throw error;
    }
  }
  chrome.storage.session.get(key).then(data=>{previous=data?.[key]||null;}).catch(()=>{}).finally(()=>{ready=true;persist();});
  for(const kind of ['focus','blur','pagehide'])window.addEventListener(kind,()=>record(kind));
  globalThis.MonitorNativeTrace={request,record,export:()=>JSON.stringify({current:snapshot(),previous},null,2)};
  record('loaded',{build:'20260924-orchestrator-pyramid-19'});
})();
