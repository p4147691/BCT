// Contracts for runtime features that were accidentally dropped by the first source-part split.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const source = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");
const nodePanelSource = fs.readFileSync(path.join(root, "extension", "monitor-node-panel-view.js"), "utf8");
assert.match(source, /MonitorNodePanelView[.]create/);
const css = fs.readFileSync(path.join(root, "extension", "monitor.css"), "utf8");

assert.doesNotMatch(source, /function monitorBctSharedWindowGroups\(/,
  "physical Chrome windows must not return as node-list groups");
assert.doesNotMatch(source, /function monitorFocusBctSharedWindowTab\(/,
  "physical-window tab focus must not bypass the ordinary node interaction path");
assert.doesNotMatch(css, /\.monitor-bct-window-card\{/,
  "physical Chrome-window cards must not return after bundle generation");
assert.match(nodePanelSource, /const key = node\.scopeId \|\| "__unassigned__";/,
  "conversation-network scope remains the only node-list grouping key");
assert.match(nodePanelSource, /groupList\.append\(row\)/,
  "network members remain direct draggable rows after bundle generation");
assert.match(css, /\.monitor-bct-node-list\s*\{[\s\S]*?grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important/,
  "conversation networks retain their three-column layout");

assert.match(source, /id="monitorGithubInbox"/,
  "GitHub completion inbox mount must remain in the Monitor DOM");
assert.match(source, /const monitorGithubInbox = document\.getElementById\("monitorGithubInbox"\)/);
assert.match(source, /renderMonitorGithubInbox\(state\)/,
  "BCT refresh must project GitHub terminal results");
assert.match(source, /function renderMonitorGithubInbox\(/);

assert.ok(!css.includes(".monitor-thumbnail-z-rail"),
  "the obsolete collision rail must not return after bundle generation");
assert.ok(!css.includes(".monitor-thumbnail-node-chip"),
  "the obsolete per-node chip styling must not return after bundle generation");

console.log("PASS: source-part generation retains network-only rows, GitHub inbox, and simplified node styling");
