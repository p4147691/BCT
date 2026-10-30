"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const source=fs.readFileSync(path.join(root,"extension/monitor-node-panel-view.js"),"utf8");
const stateSource=fs.readFileSync(path.join(root,"extension/monitor-node-panel-interaction-state.js"),"utf8");
assert(html.indexOf('src="monitor-node-panel-interaction-state.js"')<html.indexOf('src="monitor.js"'));
assert(html.indexOf('src="monitor-node-panel-view.js"')<html.indexOf('src="monitor.js"'));
assert.doesNotMatch(source,/\b(?:chrome|monitorNative|monitorBctShell|actFetch|monitorWorkers|monitorLastAiState)\b/);
const ctx={globalThis:null,Map,Set,Array,Math,Number,String,Object,Date,Promise};
ctx.globalThis=ctx;vm.createContext(ctx);vm.runInContext(stateSource,ctx);vm.runInContext(source,ctx);
function element(tag){
 const el={tag,children:[],dataset:{},listeners:new Map(),className:"",hidden:false,attributes:{},
   classSet:new Set(),
   append(...elements){this.children.push(...elements)},
   replaceChildren(...elements){this.children=elements.flatMap(x=>x.tag==="fragment"?x.children:[x])},
   setAttribute(key,value){this.attributes[key]=String(value)},
   addEventListener(kind,fn){this.listeners.set(kind,fn)},
   click(){return this.listeners.get("click")?.({preventDefault(){},stopPropagation(){}})}
 };
 el.classList={add:x=>el.classSet.add(x),remove:x=>el.classSet.delete(x),
   toggle:(x,on)=>on?el.classSet.add(x):el.classSet.delete(x),contains:x=>el.classSet.has(x)};
 return el;
}
const document={createDocumentFragment:()=>element("fragment"),createElement:element};
const panel=element("main"),summary=element("output"),interactions=ctx.MonitorNodePanelInteractionState.create();
const effects={selected:[],activated:[],renamed:[],drag:[],status:[],manager:0,highlight:0};
const ports={
 enabled:()=>true,pointerDrag:()=>null,cancelDrag:()=>{},
 uniqueNodes:nodes=>[...nodes],hwndForWindow:id=>"H"+id,
 lastAiState:()=>({}),locations:()=>new Map([["H10",{desktopId:"desk-a",top:50,left:30,z:1}]]),
 desktopState:()=>({desktopIds:["desk-a","desk-b"]}),
 selectionKey:node=>[node.instanceId,node.sessionId,node.windowId,node.tabId].join(":"),
 compareNodeOrder:()=>0,managerHold:()=>effects.manager++,
 beginNodeDrag:(ev,row,node)=>effects.drag.push(node.tabId),
 nodeLocationText:(node,index)=>index>=0?"D"+(index+1):"위치 확인 중",
 resolveDisplayHwnd:async node=>"H"+node.windowId,resolveHwnd:async node=>"H"+node.windowId,
 selectHwnd:hwnd=>effects.selected.push(hwnd),
 activateHwnd:(hwnd,target)=>{effects.activated.push({hwnd,target});return Promise.resolve({index:0})},
 setStatus:(...args)=>effects.status.push(args),
 renderStatusIcon:(node,detail)=>{node.activity=detail.activity},
 setSelected:key=>effects.selected.push("KEY:"+key),
 after:(fn)=>fn(),openRename:node=>effects.renamed.push(node.tabId),
 syncHighlight:()=>effects.highlight++
};
const controller=ctx.MonitorNodePanelView.create({root:panel,summary,document,interactionState:interactions,ports});
function node(id,scope){return {windowId:10,tabId:id,instanceId:"i",sessionId:"s",scopeId:scope,scopeName:scope?"Team":"",nodeLabel:"N"+id,conversationKey:"uuid-"+id,title:"Chat "+id,instanceState:"OPEN",roleTags:id===1?["Manager"]:[],active:false}}
const data=[node(1,"scope-a"),node(2,"scope-a")];
function sections(){return panel.children.filter(x=>x.tag==="section")}
function group(){return sections().find(x=>x.dataset.scopeId==="scope-a")}
(async()=>{
 controller.render(data);
 assert.equal(sections().length,2);
 assert.equal(group().children[1].children.length,2);
 assert.equal(group().children[1].className,"monitor-bct-node-list");
 const rows=group().children[1].children;
 assert.equal(rows[0].dataset.conversationKey,"uuid-1");
 assert.equal(rows[0].children[0].textContent,"N1");
 assert.equal(rows[0].children[2].activity,"pause");
 assert.equal(rows[0].classSet.has("is-manager"),true);
 assert.equal(summary.textContent,"2개 · BCT/RCC 실시간 상태");
 rows[0].listeners.get("pointerdown")({});
 assert.deepEqual(effects.drag,[1]);
 rows[0].listeners.get("contextmenu")({preventDefault(){}});
 assert.deepEqual(effects.renamed,[1]);
 rows[0].listeners.get("click")({preventDefault(){},stopPropagation(){}});
 await Promise.resolve();await Promise.resolve();
 assert(effects.selected.includes("H10"));
 assert(effects.selected.includes("KEY:i:s:10:1"));
 rows[1].listeners.get("dblclick")({preventDefault(){},stopPropagation(){}});
 await Promise.resolve();await Promise.resolve();await Promise.resolve();
 assert.equal(effects.activated.length,1);
 assert.equal(effects.activated[0].target.tabId,2);
 const header=group().children[0];
 header.listeners.get("click")({preventDefault(){},stopPropagation(){}});
 assert.equal(interactions.isCollapsed("scope-a"),true);
 assert.equal(group().children[1].hidden,true);
 controller.render(data);
 assert.equal(group().children[1].hidden,true);
 group().children[0].listeners.get("click")({preventDefault(){},stopPropagation(){}});
 assert.equal(interactions.isCollapsed("scope-a"),false);
 interactions.setSuppressedKey("i:s:10:1");
 const before=effects.selected.length;
 group().children[1].children[0].listeners.get("click")({preventDefault(){},stopPropagation(){}});
 assert.equal(effects.selected.length,before);
 assert.equal(interactions.getSuppressedKey(),"");
 assert(effects.highlight>=3);
 assert.throws(()=>ctx.MonitorNodePanelView.create({}),/PORTS_REQUIRED/);
 console.log("PASS: NodePanel DOM owner, RCC identity, group/row, drag/Manager, exact focus, rename, collapse, suppression");
})().catch(e=>{console.error(e);process.exitCode=1});
