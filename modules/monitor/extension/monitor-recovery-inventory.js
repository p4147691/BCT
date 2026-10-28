// Recovery inventory policy; never launches/restarts/reopens a conversation.
// Inputs are snapshots from the composition root. No Chrome/BCT/Native access.
(() => {
  "use strict";
  const keyOf=value => String(value?.conversation_key || "").trim();
  function create({toEpoch} = {}) {
    if (typeof toEpoch !== "function") throw new TypeError("RECOVERY_EPOCH_PORT_REQUIRED");
    function project({ghosts=[], snapshot={}, trashedKeys=[], endpoints=[]} = {}) {
      const byKey=new Map(), trashed=new Set(trashedKeys), eps=Array.isArray(endpoints)?endpoints:[];
      for (const ghost of ghosts) {
        const key=keyOf(ghost);
        if (ghost && !ghost.open && key && !trashed.has(key))
          byKey.set(key,{...ghost,recovery_source:"일반 종료"});
      }
      let changed=false;
      const rows=(Array.isArray(snapshot?.items)?snapshot.items:[]).map(item=>{
        const key=keyOf(item);
        if(!key) return item;
        const match=eps.find(ep=>keyOf(ep)===key)||null;
        const first=Number(toEpoch(match?.first_seen_at)||item?.first_seen_ms||0);
        const closed=Number(toEpoch(match?.closed_at)||item?.closed_at_ms||
          item?.captured_at_ms||snapshot?.captured_at_ms||0);
        if(first!==Number(item?.first_seen_ms||0)||closed!==Number(item?.closed_at_ms||0))
          changed=true;
        return {...item,first_seen_ms:first,closed_at_ms:closed};
      });
      const open=new Set(eps.filter(ep=>String(ep?.presence_state||"").toUpperCase()==="OPEN")
        .map(keyOf).filter(Boolean));
      for(const row of rows) {
        const key=keyOf(row);
        if(!key||trashed.has(key)||open.has(key)) continue;
        byKey.set(key,{...row,open:false,recovery_source:"재부팅 이전"});
      }
      const items=[...byKey.values()].sort((a,b)=>{
        const ar=a.recovery_source==="재부팅 이전",br=b.recovery_source==="재부팅 이전";
        if(ar&&br) return Number(a.desktop||999)-Number(b.desktop||999)||
          Number(a.slot||999)-Number(b.slot||999);
        if(ar!==br) return ar?-1:1;
        return Number(b.closed_at_ms||b.captured_at_ms||0)-
          Number(a.closed_at_ms||a.captured_at_ms||0);
      });
      return Object.freeze({
        items, updatedSnapshot:changed?{...snapshot,items:rows}:null,
        changed
      });
    }
    return Object.freeze({project});
  }
  globalThis.MonitorRecoveryInventory=Object.freeze({create});
})();
