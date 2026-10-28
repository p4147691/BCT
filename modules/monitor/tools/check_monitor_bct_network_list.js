// Offline acceptance for the flat conversation-network-first node list.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../extension/monitor.css"), "utf8");

assert.doesNotMatch(source, /function monitorBctSharedWindowGroups\(/,
  "physical Chrome windows must not create node-list groups");
assert.doesNotMatch(source, /monitorBctCollapsedWindowCards|Chrome 창 ·|monitor-bct-window-card/,
  "physical Chrome-window cards must not return");
assert.match(source, /const key = node\.scopeId \|\| "__unassigned__";/,
  "only the conversation scope owns grouping");
assert.match(source, /Number\(left\.key === "__unassigned__"\) - Number\(right\.key === "__unassigned__"\)/,
  "unassigned conversations stay after named networks");
assert.match(source, /for \(const \[index, node\] of group\.nodes\.entries\(\)\)/,
  "network members render as one flat node sequence");
assert.match(source, /groupList\.append\(row\)/,
  "every node row is a direct child of its network list for drag insertion");
assert.match(source, /row\.addEventListener\("pointerdown", \(event\) => beginMonitorBctNodePointerDrag/,
  "all node rows keep the existing drag interaction");
assert.match(source, /installMonitorBctManagerLongPress\(row, node\)/,
  "the Manager long-press interaction remains installed");
assert.match(source, /row\.append\(number, body, presence\)/,
  "flat rows retain node identity, title/location and existing status icon");
assert.match(source, /monitor-bct-node-presence/,
  "existing status icon must not be removed by unrelated label work");
assert.match(source, /return desktopPosition >= 0 \? `D\$\{desktopPosition \+ 1\}` : "위치 확인 중";/,
  "the visible location is only D1, D2, and so on");
assert.match(source, /function monitorUniqueBctConversationNodes\(nodes\)/,
  "the renderer and drag persistence share one semantic-node normalization path");
assert.match(source, /conversation:\$\{conversationKey\}/,
  "duplicate observations of one conversation collapse to one node row");
assert.match(source, /const semanticSnapshot = monitorUniqueBctConversationNodes\(snapshot\)/,
  "drag persistence never submits duplicate conversation UUIDs");
assert.match(source, /const leftManual = Number\(left\.displayOrder \|\| 0\)/,
  "explicit user or Manager ordering takes precedence when present");
assert.match(source, /location \? Number\(location\.top \|\| 0\)/,
  "window position remains an internal fallback ordering key");
assert.match(source, /node\.tabIndex \?\? Number\.MAX_SAFE_INTEGER/,
  "tab order remains the final physical fallback without creating a visible group");
assert.match(css, /\.monitor-bct-node-list\s*\{[\s\S]*?grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important/,
  "each conversation network retains the approved three-column layout");
assert.match(css, /\.monitor-bct-node-row \{ grid-template-columns:29px minmax\(0,1fr\) 17px; \}/,
  "node row preserves the existing status icon column");
assert.doesNotMatch(css, /\.monitor-bct-window-card|\.monitor-bct-window-tab-rows/,
  "physical-window grouping styles are removed");

console.log("PASS: network-only flat node list, D-only location, three columns, drag and Manager hold preserved");
