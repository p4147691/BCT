"use strict";

const assert = require("node:assert/strict");
const { create } = require("./bc-tool-refresh-adapter.js");

(async () => {
  const reloads = [];
  const tabs = new Map([[17, {
    id:17,
    windowId:9,
    url:"https://chatgpt.com/c/6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
  }]]);
  const adapter = create({ tabs: {
    async get(id) { return tabs.get(id); },
    async reload(id, options) { reloads.push([id, options]); },
  }});
  const result = await adapter.refreshExactChatTab({
    tabId:17,
    windowId:9,
    conversationKey:"6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
  });
  assert.equal(result.reloaded, true);
  assert.deepEqual(reloads, [[17, { bypassCache:false }]]);

  await assert.rejects(adapter.refreshExactChatTab({
    tabId:17, windowId:10, conversationKey:"6ad7f5b6-c834-83e8-9c00-ff70bab4204d",
  }), /BC_REFRESH_CHAT_IDENTITY_CHANGED/);
  await assert.rejects(adapter.refreshExactChatTab({
    tabId:17, windowId:9, conversationKey:"short",
  }), /BC_REFRESH_EXACT_CHAT_IDENTITY_REQUIRED/);
  assert.equal(reloads.length, 1);
  console.log("bc tool refresh adapter: PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
