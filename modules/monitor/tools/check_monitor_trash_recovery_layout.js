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
assert.match(css, /TRASH_RECOVERY_THREE_PANE_V7[\s\S]*monitor-trash-recovery-panel\{[^}]*display:grid!important;[^}]*grid-template-columns:minmax\(0,\.9fr\) minmax\(0,1\.35fr\)/,
  "memo and node panes must share the top row of a three-pane grid");
assert.match(css, /monitor-trash-thumbnail-pane\{[^}]*grid-column:1\/-1;grid-row:2/,
  "desktop thumbnails must span the full bottom row");
assert.match(panel, /monitor-trash-note-detail/,
  "memo rows must include an expandable full-body detail");
assert.match(panel, /row\.setAttribute\("aria-expanded","false"\)/,
  "memo expansion must expose accessible state");
assert.match(panel, /recoveryCurrentNodeByKey/,
  "deleted node display must prefer current node metadata");
assert.match(css, /monitor-trash-desktop-grid\{[^}]*minmax\(132px,1fr\)/,
  "deleted desktop cards must stay compact in the bottom strip");

console.log(JSON.stringify({ok: true, contract: "trash-recovery-layout-v7"}));
