"use strict";
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const context = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../extension/monitor-bct-shell.js"), "utf8"), context);
(async () => {
  const calls = [];
  const shell = context.MonitorBctShell.create({randomId: () => "fixed-operation",
    fetcher: async (url, init) => {
      calls.push({url, init});
      return {ok: true, json: async () => ({outcome: "APPLIED", evidence: {
        click_dispatched: true, owned_tab_closed: true, client_catalog_verified: false,
      }})};
    }});
  const result = await shell.refreshTools();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:18790/monitor/bct-tools/refresh");
  assert.deepEqual(JSON.parse(calls[0].init.body), {operation_id: "monitor.tools-refresh.fixed-operation"});
  assert.equal(result.clientCatalogVerified, false);
  for (const outcome of ["UNKNOWN", "FAILED", "APPLIED"]) {
    let count = 0;
    const bad = context.MonitorBctShell.create({fetcher: async () => {
      count++; return {ok: true, json: async () => ({outcome})};
    }});
    await assert.rejects(bad.refreshTools("original-operation"), /UNVERIFIED:original-operation/);
    assert.equal(count, 1);
  }
  let attempts = 0;
  const lost = context.MonitorBctShell.create({randomId: () => "lost-reply",
    fetcher: async () => { attempts++; throw Error("network lost"); }});
  await assert.rejects(lost.refreshTools(), error => {
    assert.equal(error.operationId, "monitor.tools-refresh.lost-reply");
    assert.match(error.message, /monitor.tools-refresh.lost-reply/);
    return true;
  });
  assert.equal(attempts, 1);
  console.log("PASS: Monitor fixed plugin refresh, exact receipt, no tab reload or automatic retry");
})().catch(e => { console.error(e); process.exitCode = 1; });
