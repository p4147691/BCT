"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null,Map,Set,Array,String,Number,Date,Math,Object};
ctx.globalThis=ctx;vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-recovery-panel-view.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const bundle=fs.readFileSync(path.join(root,"extension/monitor.js"),"utf8");
vm.runInContext(src,ctx);
assert(html.indexOf('src="monitor-recovery-panel-view.js"')<html.indexOf('src="monitor.js"'));
assert.match(bundle,/MonitorRecoveryPanelView[.]create/);
assert.doesNotMatch(src,/chrome[.]|monitorNative|actFetch|monitorTrashRecords|monitorRebootSnapshot/);
function el(tag){
 const x={tag,children:[],dataset:{},className:"",hidden:false,listeners:new Map(),parentElement:null,classSet:new Set(),
  append(...items){items.forEach(i=>{i.parentElement=this;this.children.push(i)})},
  replaceChildren(...items){this.children=[];this.append(...items)},
  querySelectorAll(q){let results=[];const classname=(q.match(/\.([\w-]+)/)||[])[1];const dataFilter=q.includes("[data-recovery-key]");
    const visit=node=>{for(const c of node.children){if((!classname||c.className.split(" ").includes(classname))&&(!dataFilter||c.dataset.recoveryKey!==undefined))results.push(c);visit(c)}};visit(this);return results},
  querySelector(q){return this.querySelectorAll(q)[0]||null},
  addEventListener:(kind,fn)=>x.listeners.set(kind,fn),
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(y=>y!==this)},
  setAttribute:(key,value)=>{x[key]=String(value)}
 };
 x.classList={add:name=>x.classSet.add(name),remove:name=>x.classSet.delete(name)};
 return x;
}
const document={createElement:el},effects=[];
const sample={conversation_key:"uuid-42",title:"Closed",recovery_source:"일반 종료",
  first_seen_ms:10000,closed_at_ms:20000,profile_id:"P",outcome:"UNKNOWN"};
const notes=new Map([["note1",{id:"note1",title:"Note",body:"first\nsecond"}]]);
const desktops=new Map([["d1",{id:"desktop1",desktop_number:2,thumbnail:""}]]);
const trash=new Map([["t1",{conversation_key:"uuid-trash",trash_source:"list",trashed_at_ms:100,network_name:"Team"}]]);
const ports={
 recoveryItems:()=>[sample],workersForState:()=>[],workerWorkState:()=>"",
 trashedNotes:()=>notes,noteTitle:()=>"",clearNotes:()=>effects.push("clear-notes"),
 restoreNote:id=>effects.push("note:"+id),deleteNote:id=>effects.push("delete-note:"+id),
 trashRecords:()=>trash,previousLocation:()=>"D1",contextTitle:()=> "Previous",
 restoreTrash:id=>effects.push("trash:"+id),deleteTrash:id=>effects.push("delete-trash:"+id),
 trashedDesktops:()=>desktops,clearThumbnail:()=>effects.push("clear-thumbnail"),
 restoreDesktop:id=>effects.push("desktop:"+id),deleteDesktop:id=>effects.push("delete-desktop:"+id),
 rebootSnapshot:()=>({items:[]}),trashedKeys:()=>new Set(),rebootRestoring:()=>false,
 restoreAll:()=>effects.push("restore-all"),restoreReboot:()=>effects.push("restore-reboot"),
 clearConversations:()=>effects.push("clear-convo"),contextRecord:()=>({}),
 pendingRestores:()=>new Set(),restoreDetached:item=>effects.push("detached:"+item.conversation_key),
 deleteRecovery:id=>effects.push("delete-recovery:"+id),contextContinueButton:()=>el("button"),
 after:callback=>callback(),confirm:()=>true,pruneDropped:keys=>effects.push("prune:"+keys.size)
};
const controller=ctx.MonitorRecoveryPanelView.create({document,ports});
const panel=controller.render({endpoints:[]});
assert.equal(panel.className,"monitor-closed-conversation-panel monitor-trash-recovery-panel");
const rows=panel.querySelectorAll(".monitor-closed-conversation-row");
assert(rows.length>=3,"notes, trash, closed conversations must each be visible");
const unknown=panel.querySelectorAll(".monitor-trash-node-status").find(x=>x.textContent==="결과 미확정");
assert(unknown,"UNKNOWN outcome must be shown explicitly");
const closed=rows.find(x=>x.dataset.recoveryKey==="uuid-42");
assert(closed);
const restore=closed.querySelector(".monitor-detached-restore");
assert(restore);
restore.listeners.get("click")({stopPropagation(){}});
assert(effects.includes("detached:uuid-42"));
const trashRow=rows.find(x=>x.dataset.recoveryKey==="uuid-trash");
trashRow.querySelector(".monitor-detached-restore").listeners.get("click")({stopPropagation(){}});
assert(effects.includes("trash:uuid-trash"));
closed.listeners.get("contextmenu")({preventDefault(){},stopPropagation(){}});
assert(closed.querySelector(".monitor-recovery-details"));
assert.throws(()=>ctx.MonitorRecoveryPanelView.create({}),/PORTS_REQUIRED/);
console.log("PASS: recovery full DOM owner, exact closed/trash UUID, Notes, desktop records, UNKNOWN and injected restore actions");
