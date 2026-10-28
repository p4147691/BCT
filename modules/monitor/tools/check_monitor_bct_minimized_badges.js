// Isolated minimized badge integration: actual Monitor functions, mock DOM only.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const src=fs.readFileSync(path.join(__dirname,"../extension/monitor.js"),"utf8");
const thumbnailV2Src=fs.readFileSync(path.join(__dirname,"../extension/monitor-desktop-thumbnail-v2.js"),"utf8");
const contractSrc=fs.readFileSync(path.join(__dirname,"../extension/monitor-minimized-node-badge-contract.js"),"utf8");
const projectionSrc=fs.readFileSync(path.join(__dirname,"../extension/monitor-bct-thumbnail-projection.js"),"utf8");
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
const unknownTokens = ctx.MonitorMinimizedNodeBadgeContract.tokensByDesktop({
  locations:new Map([["500",{desktopId:"deskC",iconic:true}]]),
  tokensForHwnd:()=>[{token:"?",tabId:701},{token:"?",tabId:702}]
});
assert.deepEqual(Array.from(unknownTokens.get("deskC")).map((item)=>[item.token,item.tabId]),[["?",701],["?",702]], "each unknown tab stays independently represented");
ctx.syncMonitorMinimizedNodeBadges({});
assert.equal(label.badges.children.map(x=>x.textContent).join(""),"2/3/5/6/7");
assert.equal(label2.badges.children.map(x=>x.textContent).join(""),"8");
// A UUID-less minimized Chrome tab is individually selected by exact tabId.
labels["100"]=[{token:"?",tabId:701},{token:"?",tabId:702},{token:"61",tabId:703}];
locationMap.set("200",{desktopId:"deskA",iconic:false});
ctx.monitorBctWindowNodesCache=[{key:"selected-unknown",nodeLabel:"N?",tabId:702}];
ctx.monitorBctSelectedNodeKey="selected-unknown";
ctx.monitorBctNodeSelectionKey=(node)=>node.key;
ctx.syncMonitorMinimizedNodeBadges({});
const selectedUnknown=label.badges.children.filter(x=>String(x.className).includes("monitor-desktop-minimized-node"));
assert.deepEqual(selectedUnknown.map(x=>x.textContent),["?","?","61"]);
assert.deepEqual(selectedUnknown.map(x=>String(x.className).includes("monitor-desktop-minimized-node-selected")),[false,true,false],
  "exact Chrome tabId selects only its own unknown minimized node");
ctx.monitorBctSelectedNodeKey="";
ctx.monitorBctWindowNodesCache=[];

locationMap.set("100",{desktopId:"deskA",iconic:false});
locationMap.set("200",{desktopId:"deskA",iconic:false});
ctx.syncMonitorMinimizedNodeBadges({});
assert.deepEqual(label.badges.children.map(x=>x.textContent),[]);
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
assert.match(contractSrc,/if \(!Boolean\(location\?\.iconic\)\) continue;/);
assert.match(thumbnailV2Src,/windowLayer\.windowFrame\(visual,desktopId,frame/,
  "V2 owns the window-frame render instead of the compatibility bundle");
assert.match(src,/afterWindowRender:\s*visual\s*=>\s*syncMonitorThumbnailTabBadges\(visual,\s*"monitor-desktop-thumb-window"\)/,
  "the V2 boundary injects only the node-label projection");
assert.match(src,/syncMonitorThumbnailTabBadges\(tile,"monitor-desktop-thumb-window"\)/);
assert.match(src,/MonitorBctThumbnailProjection/);
assert.match(projectionSrc,/windowLayer\.append\(badge\)/);
assert.match(projectionSrc,/layer\.append\(windowLayer\)/);
assert.match(css,/\.monitor-thumbnail-node-overlay\s*\{[^}]*position:absolute[^}]*pointer-events:none/s,
  "node overlay keeps a distinct click-through visual layer");
assert.match(css,/\.monitor-desktop-minimized-nodes\.monitor-bct-minimized-selection/,
  "the selected minimized node must highlight its own desktop summary");
assert.match(src,/monitor-bct-minimized-selection/,
  "node selection must re-project into minimized summaries");
assert.match(render,/monitorBctNodeSelectionKey\(node\) === selectedKey/,
  "minimized selection uses the same identity key as the BCT node list");
assert.match(render,/monitorMinimizedNodeTokensByDesktop\(state\)/,
  "minimized summary retains tab identity instead of only numeric slots");
assert.doesNotMatch(css,/\.monitor-thumbnail-z-rail\s*\{/);
console.log("PASS: minimized nodes use the bottom summary while open nodes keep natural HWND stacking");
