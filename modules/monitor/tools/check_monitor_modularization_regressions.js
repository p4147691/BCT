// Contracts for runtime features that were accidentally dropped by the first source-part split.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const source = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");
const css = fs.readFileSync(path.join(root, "extension", "monitor.css"), "utf8");

assert.match(source, /function monitorBctSharedWindowGroups\(/,
  "shared Chrome-window grouping must survive bundle generation");
assert.match(source, /function monitorFocusBctSharedWindowTab\(/,
  "exact shared-window tab focus must survive bundle generation");
assert.match(css, /\.monitor-bct-window-card\{/,
  "shared Chrome-window cards must retain their layout contract");

assert.match(source, /id="monitorGithubInbox"/,
  "GitHub completion inbox mount must remain in the Monitor DOM");
assert.match(source, /const monitorGithubInbox = document\.getElementById\("monitorGithubInbox"\)/);
assert.match(source, /renderMonitorGithubInbox\(state\)/,
  "BCT refresh must project GitHub terminal results");
assert.match(source, /function renderMonitorGithubInbox\(/);

for (const selector of [
  ".monitor-thumbnail-node-chip-list",
  ".monitor-thumbnail-node-chip",
  ".monitor-thumbnail-z-rail",
  ".monitor-thumbnail-z-row",
  ".monitor-thumbnail-z-more",
]) {
  assert.ok(css.includes(selector), `${selector} styling must survive modularization`);
}

console.log("PASS: source-part generation retains shared-window rows, GitHub inbox, and thumbnail Z-rail styling");
