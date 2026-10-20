"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const extension=path.join(__dirname,"../extension");
const moduleSource=fs.readFileSync(path.join(extension,"monitor-status-icon.js"),"utf8");
const monitorSource=fs.readFileSync(path.join(extension,"monitor.js"),"utf8");
const css=fs.readFileSync(path.join(extension,"monitor.css"),"utf8");
const context={}; vm.createContext(context); vm.runInContext(moduleSource,context);
const icons=context.MonitorStatusIcon;
for(const kind of ["play","pause","complete","warning"]){
  const markup=icons.svg(kind,"test-icon");
  assert.match(markup,/^<svg /);
  assert.match(markup,/<(path|rect|circle) /);
  assert.doesNotMatch(markup,/[▶Ⅱ■⚠⏸✓!?]/);
}
assert.equal(JSON.stringify(icons.normalize({activity:"complete",warning:true})),JSON.stringify({activity:"complete",warning:true}));
assert.equal(JSON.stringify(icons.normalize({activity:"invented",warning:false})),JSON.stringify({activity:"",warning:false}));
assert.match(monitorSource,/function monitorWorkIconState\(/);
assert.match(monitorSource,/connection === "disconnected"[\s\S]{0,180}alertDetail\?\.warning === true/);
assert.match(monitorSource,/activity:\"complete\"[\s\S]{0,120}창을 닫아도 됨/);
assert.match(monitorSource,/globalThis\.MonitorStatusIcon\?\.render\?\.\(overlay,\{activity,warning\}\)/);
assert.match(css,/THUMBNAIL_STATUS_SVG_V1/);
assert.match(css,/\.monitor-window-pause-overlay::before\{content:none!important/);
console.log("PASS: thumbnail status uses monochrome SVG play/pause/complete/warning semantics; disconnected is warning, not close-safe complete");
