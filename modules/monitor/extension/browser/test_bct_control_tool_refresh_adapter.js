"use strict";

const assert = require("node:assert/strict");
const { BCT_CONTROL_SETTINGS_URL, create } = require("./bct-control-tool-refresh-adapter.js");

(async () => {
  const executions = [];
  const creates = [];
  let tabs = [{ id:17, windowId:9, status:"complete", url:BCT_CONTROL_SETTINGS_URL }];
  let injectedResult = {
    schema:"monitor.bct-control.tool-refresh.receipt.v1",
    ok:true,
    status:"APPLIED",
    accepted:true,
    completed:true,
  };
  const adapter = create({
    tabs: {
      async query() { return tabs; },
      async create(options) {
        creates.push(options);
        return { id:21, windowId:11, status:"complete", url:options.url };
      },
      async get(id) { return { id, windowId:11, status:"complete", url:BCT_CONTROL_SETTINGS_URL }; },
    },
    scripting: {
      async executeScript(options) {
        executions.push(options);
        return [{ frameId:0, result:injectedResult }];
      },
    },
  });

  const existing = await adapter.refreshTools();
  assert.equal(existing.status, "APPLIED");
  assert.equal(existing.tabId, 17);
  assert.equal(existing.opened, false);
  assert.equal(executions[0].target.tabId, 17);

  tabs = [];
  const opened = await adapter.refreshTools();
  assert.equal(opened.tabId, 21);
  assert.equal(opened.opened, true);
  assert.deepEqual(creates, [{ url:BCT_CONTROL_SETTINGS_URL, active:false }]);

  injectedResult = {
    schema:"monitor.bct-control.tool-refresh.receipt.v1",
    ok:false,
    status:"UNKNOWN",
    accepted:true,
    error:"BCT_CONTROL_REFRESH_COMPLETION_UNVERIFIED",
  };
  tabs = [{ id:17, windowId:9, status:"complete", url:BCT_CONTROL_SETTINGS_URL }];
  const unknown = await adapter.refreshTools();
  assert.equal(unknown.status, "UNKNOWN");
  assert.equal(unknown.accepted, true);

  tabs = [
    { id:17, windowId:9, status:"complete", url:BCT_CONTROL_SETTINGS_URL },
    { id:18, windowId:9, status:"complete", url:`${BCT_CONTROL_SETTINGS_URL}/` },
  ];
  await assert.rejects(adapter.refreshTools(), /BCT_CONTROL_REFRESH_AMBIGUOUS_SETTINGS_TABS/);

  console.log("bct control tool refresh adapter: PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
