"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const lifecycle = fs.readFileSync(path.join(root, "domains", "desktop-lifecycle.js"), "utf8");
const css = fs.readFileSync(path.join(root, "extension", "monitor.css"), "utf8");
const start = lifecycle.indexOf("function renderMonitorClosedConversationRecoveryPanel");
const end = lifecycle.indexOf("//@@FN_END:renderMonitorClosedConversationRecoveryPanel", start);
assert.ok(start >= 0 && end > start, "trash recovery function must exist");
const panel = lifecycle.slice(start, end);

assert.doesNotMatch(panel, /textContent\s*=\s*["']비어 있음["']/,
  "ambiguous empty labels must not be rendered");
assert.match(panel, /if\(thumbRecords\.length\)renderTrashRows\("thumbnail",thumbScroll\);\s*else if\(!desktopRecords\.length\)/,
  "desktop cards must not receive a redundant empty thumbnail row");
assert.match(panel, /삭제된 메모 없음/);
assert.match(panel, /삭제된 노드 없음/);
assert.match(panel, /삭제된 데스크 없음/);
assert.match(css, /monitor-trash-note-row\{[^}]*grid-template-columns:minmax\(96px,\.38fr\) minmax\(120px,1fr\)/,
  "memo title and compact preview need separate columns");
assert.match(css, /monitor-trash-conversation-pane\{[^}]*min-height:150px/,
  "deleted node pane must retain useful height");
assert.match(css, /monitor-trash-desktop-grid\{[^}]*minmax\(178px,1fr\)/,
  "deleted desktop cards must be large enough to inspect");

console.log(JSON.stringify({ok: true, contract: "trash-recovery-layout-v6"}));
