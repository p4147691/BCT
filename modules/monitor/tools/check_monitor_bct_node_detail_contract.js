"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function domainFunction(name) {
  const source = fs.readFileSync(path.join(__dirname, "../domains/node-identity.js"), "utf8");
  const match = source.match(new RegExp(`//@@FN_START:${name}\\n([\\s\\S]*?)\\n//@@FN_END:${name}`));
  assert.ok(match, `${name} must remain in node-identity.js`);
  return match[1];
}

const now = 1_800_000_000_000;
const context = {
  globalThis: null,
  Map,
  Number,
  String,
  Array,
  Object,
  Date: { now: () => now },
  monitorBctNodeSelectionKey: (node) => node?.conversationKey || node?.tabId || "",
};
context.globalThis = context;
context.__monitorBctNodeDisplayState = {
  firstObservedAt: new Map([
    ["work-1", now - 120 * 60 * 1000],
    ["chat-1", now - 5 * 60 * 1000],
  ]),
  loaded: true,
  load: null,
  saveTimer: 0,
  viewMode: "manual",
};
vm.createContext(context);
vm.runInContext([
  "monitorBctNodeDisplayState",
  "monitorBctNodeObservedKey",
  "monitorBctNodeObservedAgeText",
  "monitorBctNodeLocationText",
  "monitorBctNodeSurfaceText",
  "monitorBctNodeBurden",
  "monitorBctNodeDetail",
].map(domainFunction).join("\n"), context);

assert.equal(context.monitorBctNodeSurfaceText({ conversationKey: "" }), "New");
assert.equal(context.monitorBctNodeSurfaceText({ conversationKey: "old", surfaceKind: "UNKNOWN" }), "Chat");
assert.equal(context.monitorBctNodeSurfaceText({ conversationKey: "work", surfaceKind: "WORK" }), "Work");
assert.equal(context.monitorBctNodeSurfaceText({ conversationKey: "codex", surfaceKind: "CODEX" }), "Chat");

const minimized = context.monitorBctNodeDetail({
  conversationKey: "work-1",
  surfaceKind: "WORK",
  reasoningLevel: "xhigh",
  telemetry: { js_heap_used_mb: 800, js_heap_limit_mb: 1000, rendered_chars: 900000 },
}, 0, { iconic: true });
assert.equal(minimized.text, "D1 _ Work E 120분 높음");
assert.match(minimized.title, /위치 D1 · 최소화됨 · 종류 Work · 추론 xhigh · 관측 120분 · 부담 높음/);

const prefixedObservation = context.monitorBctNodeDetail({
  conversationKey: "chat-1",
  surfaceKind: "CHAT",
  reasoningRaw: "추론 수준Instant",
  reasoningLevel: "I",
}, 1, { iconic: false });
assert.equal(prefixedObservation.text, "D2 Chat I 5분 미확인");
assert.match(prefixedObservation.title, /추론 추론 수준Instant/,
  "the detail title retains the exact observed raw value");

const ordinary = context.monitorBctNodeDetail({
  conversationKey: "chat-1",
  surfaceKind: "CHAT",
  reasoningLevel: "?",
}, 1, { iconic: false });
assert.equal(ordinary.text, "D2 Chat 미확인 5분 미확인");
assert.doesNotMatch(ordinary.text, /[_−]/);
assert.doesNotMatch(ordinary.text, /Chat\/Work/);

const blank = context.monitorBctNodeDetail({ tabId: "blank", reasoningLevel: "UNKNOWN" }, -1, null);
assert.equal(blank.text, "D? New 미확인 0분 미확인");

const conversations = fs.readFileSync(path.join(__dirname, "../domains/conversations.js"), "utf8");
const editor = conversations.match(/\/\/@@FN_START:openMonitorBctRenameEditor\n([\s\S]*?)\n\/\/@@FN_END:openMonitorBctRenameEditor/);
assert.ok(editor, "right-click node information editor must remain in conversations.js");
for (const label of ["현재 위치", "창 상태", "종류", "관측 추론 수준", "관측 경과", "탭 부담", "연결"]) {
  assert.match(editor[1], new RegExp(`fact\\(${JSON.stringify(label)}`), `right-click facts must include ${label}`);
}
assert.doesNotMatch(editor[1], /실제 추론 수준/, "observed reasoning must not be presented as an authoritative setting");
assert.doesNotMatch(editor[1], /querySelector\?\.\("\.monitor-bct-node-location"\)/,
  "right-click facts must not relabel the complete compact card line as the location");

console.log("PASS: node detail composes location, minimized state, one surface, reasoning, minutes, and burden");
