"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const context = {};
vm.runInNewContext(fs.readFileSync(path.join(root, "extension/monitor-diagnostics-view-feature.js"), "utf8"), {globalThis:context});
const html = fs.readFileSync(path.join(root, "extension/desktop.html"), "utf8");
assert.ok(html.indexOf('src="monitor-diagnostics-view-feature.js"') <
  html.indexOf('src="monitor.js"'));
const domain = fs.readFileSync(path.join(root, "domains/diagnostics-shell.js"), "utf8");
assert.match(domain, /MonitorDiagnosticsViewFeature[.]create/);

async function run() {
  const events = [];
  let view = {view:"overview", label:"전체"};
  let release;
  const suspended = new Promise(resolve => release = resolve);
  const button = {
    disabled:false,
    classes:new Set(),
    classList: { add(name) {button.classes.add(name);}, remove(name) {button.classes.delete(name);} }
  };
  const ports = {
    async refreshOverview() { events.push("overview"); await suspended; },
    async refreshAct() { events.push("act"); },
    actStatus: () => "ACT: OK",
    autoStatus: () => "Jobs: OK",
    renderMonitor: () => "Report",
    show: value => events.push(value)
  };
  const c = context.MonitorDiagnosticsViewFeature.create({button, getActiveView: () => view, ports});
  assert.equal(context.MonitorDiagnosticsViewFeature.create({button, getActiveView: () => view, ports}),c);
  const pending = c.refresh();
  assert.equal(button.disabled, true);
  assert.equal(await c.refresh(), false);
  release();
  assert.equal(await pending, true);
  assert.equal(button.disabled, false);
  assert.equal(button.classes.size, 0);
  assert.match(events.pop(), /ACT: OK/);
  view = {view:"act"};
  await c.refresh();
  assert.match(events.pop(), /ACT: OK/);
  view = {view:"monitor"};
  await c.refresh();
  assert.equal(events.pop(),"Report");
  view = {view:"future",label:"New"};
  await c.refresh();
  assert.match(events.pop(),/New/);
  c.destroy();
  assert.notEqual(context.MonitorDiagnosticsViewFeature.create({button,getActiveView:()=>view,ports}),c);
  console.log("PASS: diagnostics view owner, injected ports, busy fence, status display, and destroy");
}
run().catch(e=>{console.error(e);process.exitCode=1;});
