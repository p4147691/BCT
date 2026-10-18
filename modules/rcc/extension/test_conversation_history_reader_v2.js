"use strict";
const assert = require("node:assert/strict");
const { scan, loadOlder } = require("./conversation_history_reader_v2.js");
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
  console.log("Conversation V2 isolated DOM fixtures: PASS");
}
main().catch(e => { console.error(e); process.exitCode = 1; });
