"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const dir = path.resolve(__dirname, "..");
const sandbox = {};
vm.runInNewContext(
  fs.readFileSync(path.join(dir, "extension/monitor-window-lifecycle-queue.js"), "utf8"),
  { globalThis: sandbox }
);
const html = fs.readFileSync(path.join(dir, "extension/desktop.html"), "utf8");
const domain = fs.readFileSync(path.join(dir, "domains/diagnostics-shell.js"), "utf8");
const parts = fs.readFileSync(path.join(dir, "source-parts/05-native-lifecycle.js"), "utf8");
assert.ok(html.indexOf('src="monitor-window-lifecycle-queue.js"') <
  html.indexOf('src="monitor.js"'));
assert.match(domain, /monitorWindowLifecycleController[.]schedule[(]event[)]/);
assert.match(domain, /monitorWindowLifecycleController[.]drain[(][)]/);
assert.doesNotMatch(parts, /const monitorWindowLifecyclePendingEvents = new Map/);
assert.doesNotMatch(parts, /let monitorWindowLifecycleDrainBusy/);

async function tick() {
  await new Promise(resolve => setImmediate(resolve));
}
async function run() {
  const seen = [], errors = [];
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const queue = sandbox.MonitorWindowLifecycleQueue.create({
    async handle(event) {
      seen.push(event.tag);
      if (event.tag === "first") await blocked;
      if (event.tag === "error") throw Error("diagnostic");
    },
    onError(error) { errors.push(error.message); }
  });
  assert.equal(queue.schedule({ hwnd: "0" }), false);
  assert.equal(queue.schedule({ hwnd: "invalid" }), false);
  assert.equal(queue.schedule({ hwnd: "22", tag: "first" }), true);
  queue.schedule({ hwnd: "33", tag: "stale" });
  queue.schedule({ hwnd: "33", tag: "latest" });
  queue.schedule({ hwnd: "44", tag: "error" });
  queue.schedule({ hwnd: "55", tag: "last" });
  release();
  await queue.drain();
  await tick();
  assert.deepEqual(seen, ["first", "latest", "error", "last"]);
  assert.deepEqual(errors, ["diagnostic"]);
  queue.destroy();
  assert.equal(queue.schedule({ hwnd: "22", tag: "after-destroy" }), false);
  console.log("PASS: unique HWND lifecycle state, coalescing, ordering, error continuation, disposal");
}
run().catch(e => { console.error(e); process.exitCode = 1; });
