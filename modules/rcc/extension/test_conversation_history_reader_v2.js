"use strict";
const assert = require("node:assert/strict");
const { scan, loadOlder, conversationId } = require("./conversation_history_reader_v2.js");
const message = (id, text) => ({
  getAttribute: key => key === "data-message-id" ? id : null,
  innerText: text
});
async function main() {
  const a = message("m1", "안녕하세요");
  const duplicate = message("m1", "duplicate");
  const b = message("m2", "과거 메시지");
  const container = {scrollTop: 600, scrollHeight: 1200, clientHeight: 300, parentElement: null};
  const doc = {
    body: {},
    scrollingElement: container,
    documentElement: container,
    rows: [a, duplicate],
    querySelector() { return this.rows[0] || null; },
    querySelectorAll() { return this.rows; }
  };
  assert.equal(scan(doc).duplicates, 1);
  assert.equal(scan(doc).messages[0].text, "안녕하세요");
  const r = await loadOlder(doc, {
    maxSteps: 6,
    settle: async () => { if (container.scrollTop === 0) doc.rows = [b, a, duplicate]; }
  });
  assert.equal(r.status, "PARTIAL");
  assert.equal(r.full_history_verified, false);
  assert.deepEqual(r.messages.map(x => x.id), ["m1", "m2"]);
  assert.ok(r.duplicates > 0);
  const empty = await loadOlder({...doc, rows: [], querySelector() {return null;}});
  assert.equal(empty.reason, "NO_IDENTIFIED_TURNS");
  assert.equal(empty.status, "PARTIAL");
  const expected = "https://chatgpt.com/c/6ad365ef-159c-83ee-8fe9-08742f99a24c";
  const other = "https://chatgpt.com/c/6ad4b590-dfc8-83ee-b29f-92033f07fc08";
  assert.equal(conversationId(expected), "6ad365ef-159c-83ee-8fe9-08742f99a24c");
  assert.equal(conversationId("https://invalid.example/c/6ad365ef-159c-83ee-8fe9-08742f99a24c"), null);
  const mismatchDoc = {...doc, location: {href:other}};
  const mismatch = await loadOlder(mismatchDoc, {expectedConversationUrl: expected});
  assert.equal(mismatch.reason, "CONVERSATION_ID_MISMATCH");
  assert.deepEqual(mismatch.messages, []);
  const moved = {...doc, location:{href:expected}, rows:[a], querySelector(){return this.rows[0]}, querySelectorAll(){return this.rows}};
  const navigated = await loadOlder(moved, {expectedConversationUrl:expected,
    maxSteps:4, settle:async () => {moved.location.href=other;}});
  assert.equal(navigated.reason,"CONVERSATION_ID_CHANGED");
  assert.equal(navigated.full_history_verified,false);
  console.log("Conversation V2 isolated DOM fixtures: PASS");
}
main().catch(e => { console.error(e); process.exitCode = 1; });
