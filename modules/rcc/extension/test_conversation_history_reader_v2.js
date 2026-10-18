"use strict";
const assert = require("node:assert/strict");
const { scan, loadOlder, conversationId } = require("./conversation_history_reader_v2.js");

const message = (id, text) => ({
  getAttribute: key => key === "data-message-id" ? id : null,
  innerText: text
});
const anonymous = () => ({
  getAttribute: () => null, innerText: "unidentified",
  closest: () => null, querySelector: () => null
});
function documentWith(rows, anon = []) {
  const container = {scrollTop:600,scrollHeight:1200,clientHeight:300,parentElement:null};
  return {
    body: {}, scrollingElement: container, documentElement: container,
    rows, anonymousRows: anon,
    querySelector() { return this.rows[0] || null; },
    querySelectorAll(selector) {
      return selector.includes("data-message-author-role") ? this.anonymousRows : this.rows;
    }
  };
}
async function main() {
  const a = message("m1", "안녕하세요");
  const duplicate = message("m1", "duplicate");
  const b = message("m2", "과거 메시지");
  const doc = documentWith([a, duplicate], [anonymous()]);
  assert.equal(scan(doc).duplicates, 1);
  assert.equal(scan(doc).unidentified, 1);
  assert.equal(scan(doc).messages[0].text, "안녕하세요");

  // Match the real RCC selectors: prefer data-turn-key over a wrapper testid.
  const keyed = {
    getAttribute: key => key === "data-turn-key" ? "turn-key-17" : null,
    innerText: "실제 대화 메시지",
    closest: selector => selector === "[data-turn-key]" ? keyed : null
  };
  const wrapper = {
    getAttribute: key => key === "data-testid" ? "conversation-turn-17" : null,
    innerText: "wrapper text",
    closest: () => null,
    querySelectorAll: selector => selector === "[data-turn-key]" ? [keyed] : []
  };
  const keyedDom = documentWith([wrapper, keyed]);
  assert.deepEqual(scan(keyedDom).messages, [
    {id:"turn-key-17",text:"실제 대화 메시지"}
  ]);
  assert.equal(scan(keyedDom).duplicates,1);
  const contentKey = {
    getAttribute: key => key === "data-content-search-turn-key" ? "search-turn-18" : null,
    innerText:"과거 검색 메시지", closest:()=>null, querySelectorAll:()=>[]
  };
  const searchDom = documentWith([contentKey]);
  assert.equal(scan(searchDom).messages[0].id, "search-turn-18");
  // The canonical ID remains stable if wrappers are virtualized away.
  const virtualKey = documentWith([wrapper, keyed]);
  const keyResult = await loadOlder(virtualKey, {maxSteps:1,settle:async()=>{
    virtualKey.rows=[keyed];
  }});
  assert.equal(keyResult.messages.length,1);
  assert.equal(keyResult.messages[0].id,"turn-key-17");
  assert.ok(keyResult.reobserved>0);
  assert.equal(keyResult.full_history_verified,false);


  const r = await loadOlder(doc, {
    maxSteps: 6,
    settle: async () => { if (doc.scrollingElement.scrollTop === 0) doc.rows = [b, a, duplicate]; }
  });
  assert.equal(r.status, "PARTIAL");
  assert.equal(r.full_history_verified, false);
  assert.deepEqual(r.messages.map(x => x.id), ["m1", "m2"]);
  assert.ok(r.duplicatesInSamples >= 2);
  assert.ok(r.reobserved > 0);
  assert.equal(r.messages.length, 2);
  assert.ok(r.unidentified > 0);
  assert.equal(r.gaps_verifiable, false);
  assert.equal(r.reason, "NO_MORE_VISIBLE_PROGRESS");

  // The final settled scroll must be captured even with maxSteps=1.
  const last = documentWith([message("newer", "newer")]);
  const one = await loadOlder(last, {maxSteps:1,settle: async () => {
    last.rows=[message("older", "옛 메시지"), message("newer","newer")];
  }});
  assert.deepEqual(one.messages.map(x => x.id), ["newer", "older"]);
  assert.equal(one.steps, 1);
  assert.equal(one.reason, "STEP_LIMIT");

  // Virtualized turns can disappear from the DOM and must remain in the map.
  const virtualized = documentWith([message("v3","new")]);
  const v = await loadOlder(virtualized, {maxSteps:2,settle:async () => {
    virtualized.rows=[message("v2","middle")];
  }});
  assert.deepEqual(v.messages.map(x=>x.id), ["v3", "v2"]);

  // Repeated IDs with changed contents are flagged, not silently treated as new IDs.
  const conflict = documentWith([message("same","initial")]);
  const cr = await loadOlder(conflict,{maxSteps:1,settle:async () => {
    conflict.rows=[message("same","changed")];
  }});
  assert.equal(cr.messages.length,1);
  assert.equal(cr.conflictingTexts,1);
  assert.ok(cr.reobserved>0);

  const missingId = documentWith([], [anonymous()]);
  const empty = await loadOlder(missingId);
  assert.equal(empty.reason,"NO_IDENTIFIED_TURNS");
  assert.equal(empty.status,"PARTIAL");
  assert.equal(empty.unidentified,1);

  // Do not double-count an author node nested in a known turn.
  const nested = {getAttribute:()=>null, closest:()=>a, querySelector:()=>null};
  const knownNested = documentWith([a],[nested]);
  assert.equal(scan(knownNested).unidentified,0);
  const unnumbered = {
    getAttribute: key => key === "data-testid" ? "conversation-turn" : null,
    closest: () => null,
    querySelector: () => null,
    innerText: "unknown turn"
  };
  const anonymousUnnumbered = documentWith([], [unnumbered]);
  assert.equal(scan(anonymousUnnumbered).unidentified,1);
  assert.equal(scan(anonymousUnnumbered).messages.length,0);

  const expected="https://chatgpt.com/c/6ad365ef-159c-83ee-8fe9-08742f99a24c";
  const other="https://chatgpt.com/c/6ad4b590-dfc8-83ee-b29f-92033f07fc08";
  assert.equal(conversationId(expected),"6ad365ef-159c-83ee-8fe9-08742f99a24c");
  assert.equal(conversationId("https://invalid.example/c/6ad365ef-159c-83ee-8fe9-08742f99a24c"),null);
  const mismatch=documentWith([a]);
  mismatch.location={href:other};
  const m=await loadOlder(mismatch,{expectedConversationUrl:expected});
  assert.equal(m.reason,"CONVERSATION_ID_MISMATCH");
  assert.deepEqual(m.messages,[]);
  const moved=documentWith([a]);
  moved.location={href:expected};
  const movedResult=await loadOlder(moved,{expectedConversationUrl:expected,maxSteps:4,
    settle:async () => {moved.location.href=other;}});
  assert.equal(movedResult.reason,"CONVERSATION_ID_CHANGED");
  assert.equal(movedResult.full_history_verified,false);
  assert.equal(movedResult.messages.length,1);

  console.log("Conversation V2 isolated DOM fixtures: PASS");
}
main().catch(e=>{console.error(e);process.exitCode=1;});
