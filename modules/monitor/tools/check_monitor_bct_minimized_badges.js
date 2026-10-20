// Isolated minimized badge integration: actual Monitor functions, mock DOM only.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const src=fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const contractSrc=fs.readFileSync(path.join(__dirname,"../extension/monitor-minimized-node-badge-contract.js"),"utf8");
function extract(name,until){
  const a=src.indexOf("function "+name+"(");
  const b=src.indexOf("\nfunction "+until+"(",a+1);
  assert(a>0 && b>a,name);
  return src.slice(a,b);
}
const aggregate=extract("monitorMinimizedNodeSlotsByDesktop","profileForMonitorWorker");
const render=extract("syncMonitorMinimizedNodeBadges","syncDesktopSwitcher");
const locationMap=new Map([
  ["100",{desktopId:"deskA",iconic:true}],
  ["200",{desktopId:"deskA",iconic:true}],
  ["300",{desktopId:"deskB",iconic:false}],
  ["400",{desktopId:"deskB",iconic:true}]
]);
const labels={
  "100":[2,3,5,6],
  "200":[3,7],
  "300":[8],
  "400":[8]
};
const visual={
  className:"monitor-desktop-thumb-visual",
  badges:null,
  querySelector(query){return query===".monitor-desktop-minimized-nodes"?this.badges:null;},
  append(child){this.badges=child;}
};
const visual2={
  ...visual,badges:null,
  querySelector(query){return query===".monitor-desktop-minimized-nodes"?this.badges:null;},
  append(child){this.badges=child;}
};
const label={
  badges:null,
  querySelector(query){return query===".monitor-desktop-minimized-nodes"?this.badges:null;},
  append(child){this.badges=child;}
};
const label2={
  badges:null,
  querySelector(query){return query===".monitor-desktop-minimized-nodes"?this.badges:null;},
  append(child){this.badges=child;}
};
const buttons=[
  {dataset:{desktopId:"deskA"},querySelector(q){return q===".monitor-desktop-thumb-visual"?visual:q===".monitor-desktop-thumb-label"?label:null;}},
  {dataset:{desktopId:"deskB"},querySelector(q){return q===".monitor-desktop-thumb-visual"?visual2:q===".monitor-desktop-thumb-label"?label2:null;}}
];
const document={createElement(tag){
  assert.equal(tag,"span");
  return {className:"",textContent:"",title:"",hidden:false,replaceChildren(...children){this.children=children;}};
}};
const ctx={
  monitorWindowDesktopLocations:locationMap,
  monitorLastAiState:{},
  monitorBadgeNodeNumbersForHwnd:(hwnd)=>labels[hwnd]||[],
  monitorDesktopThumbs:{children:buttons},
  document,Map,Set,Boolean,String,Number,Array
};
vm.createContext(ctx);
vm.runInContext(contractSrc,ctx);
ctx.monitorMinimizedNodeBadgeContract=ctx.MonitorMinimizedNodeBadgeContract;
vm.runInContext(aggregate+"\n"+render,ctx);
const arr=ctx.monitorMinimizedNodeSlotsByDesktop({});
assert.deepEqual(Array.from(arr.get("deskA")),[2,3,5,6,7]);
assert.deepEqual(Array.from(arr.get("deskB")),[8]);
ctx.syncMonitorMinimizedNodeBadges({});
assert.deepEqual(label.badges.children.map(x=>x.textContent),["2","3","..."]);
assert.deepEqual(label2.badges.children.map(x=>x.textContent),["8"]);
locationMap.set("100",{desktopId:"deskA",iconic:false});
locationMap.set("200",{desktopId:"deskA",iconic:false});
ctx.syncMonitorMinimizedNodeBadges({});
assert.equal(label.badges.hidden,true);
assert.equal(ctx.MonitorMinimizedNodeBadgeContract.minimizedEvent({reason:"minimized",iconic:false}),true);
assert.equal(ctx.MonitorMinimizedNodeBadgeContract.minimizedEvent({reason:"restored",iconic:false}),false);
const css=fs.readFileSync(path.join(__dirname,"../extension/monitor.css"),"utf8");
assert.match(css,/\.monitor-desktop-thumb-label\s*>\s*\.monitor-desktop-minimized-nodes/);
assert.match(css,/grid-column:3 \/ 5/);
assert.match(css,/\.monitor-desktop-thumb-label\s*>\s*\.monitor-desktop-label-text\s*\{ display:none!important; \}/);
assert.match(src,/label\.append\(desktopBadge,\s*labelText,\s*minimizedNodes\)/);
assert.match(src,/label\.append\(badge,\s*text,\s*minimizedNodes\)/);
assert.match(src,/numbersForHwnd: \(hwnd\) => monitorBadgeNodeNumbersForHwnd\(hwnd, state\)/);
assert.match(src,/iconic:minimized/);
assert.match(src,/scheduleMonitorMinimizedBadgeConvergence\(hwnd\)/);
console.log("PASS: minimized display uses BCT labels, lifecycle reason and iconic state agree, 2+ellipsis bottom-right, Native desktop filter, no invented nodes");
