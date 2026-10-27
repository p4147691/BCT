"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const css=fs.readFileSync(path.join(__dirname,"../extension/monitor.css"),"utf8");
const context={globalThis:null,Object,String,RegExp,TypeError};context.globalThis=context;vm.createContext(context);
for(const name of ["monitor-thumbnail-contract.js","monitor-preview-background.js"])
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../extension",name),"utf8"),context);
const element={style:{backgroundImage:"old",backgroundColor:""},dataset:{}};
const view=context.MonitorPreviewBackground.create({element,contract:context.MonitorThumbnailContract});
const d1="8ac6b16f-820b-4773-89e7-276ae4b84040",d2="c991b275-7933-4697-9d6e-73bf31ae4379";
assert.equal(view.apply(d1,{ok:true,desktopId:d1,kind:"photo",dataUri:"data:image/jpeg;base64,PHOTO",baseColor:"#107c10",proof:"x.jpg"}),true);
assert.match(element.style.backgroundImage,/PHOTO/);assert.equal(element.style.backgroundColor,"#107C10");
assert.equal(view.apply(d1,{ok:true,desktopId:d1,kind:"solid",color:"#D13438",proof:"windows-solid-mode"}),true);
assert.equal(element.style.backgroundImage,"");assert.equal(element.style.backgroundColor,"#D13438");
assert.equal(view.apply(d1,{ok:true,desktopId:d2,kind:"solid",color:"#10893E"}),false,"cross-desktop state is rejected");
assert.equal(element.style.backgroundColor,"#D13438");
assert.equal(view.begin(d2),true,"desktop selection clears the prior desktop immediately");
assert.equal(element.style.backgroundImage,"");assert.equal(element.style.backgroundColor,"");
assert.equal(view.failed(d2),false);assert.equal(element.dataset.captureState,"failed");
assert.match(css,/body\.desktop-window-monitor-active\s*\{[^}]*background-image:none!important;[^}]*background-color:transparent!important;/,
  "the dedicated Monitor backdrop must be the only visible wallpaper owner");
console.log("PASS: full Monitor backdrop projects the same validated photo/solid snapshot without legacy photo state");
