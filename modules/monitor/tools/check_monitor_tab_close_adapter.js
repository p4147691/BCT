"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { create } = require("../extension/browser/tab-close-adapter.js");

(async () => {
  const key = "6ad733b6-95d4-83ee-b4ba-49a671229d77";
  const target = { tabId: 17, windowId: 33, conversationKey: key };
  const tabs = new Map([[17, { id:17, windowId:33, url:`https://chatgpt.com/c/${key}` }]]);
  const removals = [];
  const adapter = create({ tabs: {
    async get(id) {
      if (!tabs.has(id)) throw new Error("No tab with id");
      return tabs.get(id);
    },
    async remove(id) { removals.push(id); tabs.delete(id); },
  }});
  const closed = await adapter.close(target);
  assert.equal(closed.status, "CLOSED");
  assert.equal(closed.verified, true);
  assert.deepEqual(removals, [17]);

  const mismatchRemovals = [];
  const mismatch = await create({ tabs: {
    async get() { return { id:17, windowId:44, url:`https://chatgpt.com/c/${key}` }; },
    async remove(id) { mismatchRemovals.push(id); },
  }}).close(target);
  assert.equal(mismatch.status, "NOT_APPLIED");
  assert.equal(mismatch.error, "MONITOR_TAB_CLOSE_IDENTITY_MISMATCH");
  assert.deepEqual(mismatchRemovals, []);

  const unknown = await create({ tabs: {
    async get() { return { id:17, windowId:33, url:`https://chatgpt.com/c/${key}` }; },
    async remove() { throw new Error("response lost"); },
  }}).close(target);
  assert.equal(unknown.status, "UNKNOWN");

  const background = fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8");
  assert.match(background, /importScripts\("browser\/tab-close-adapter\.js"\)/);
  assert.match(background, /MonitorTabCloseAdapter\.create\(chrome\)/);
  assert.match(background, /monitorTabCloseAdapter\.close\(message\)/);
  assert.doesNotMatch(background, /await chrome\.tabs\.remove\(tabId\)/);

  console.log("PASS: exact tab close is an isolated reusable primitive");
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
