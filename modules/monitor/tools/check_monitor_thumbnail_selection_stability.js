"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../domains/desktop-lifecycle.js"), "utf8");
const start = source.indexOf("function selectVirtualDesktopPreview(index)");
const end = source.indexOf("//@@FN_END:selectVirtualDesktopPreview", start);
assert(start >= 0 && end > start, "selectVirtualDesktopPreview must remain discoverable");
const body = source.slice(start, end);

for (const forbidden of [
  "monitorFrameGeneration += 1",
  "monitorThumbBatchGeneration += 1",
  "monitorFrameCache.clear()",
  "monitorFrameInflight.clear()",
  "monitorThumbBatchInflight = null"
]) {
  assert(!body.includes(forbidden), `preview selection must not globally invalidate captures: ${forbidden}`);
}
assert.match(body, /void refreshObservedWindows\(\)/,
  "preview selection must refresh the large observed-window layer");
assert.match(body, /void refreshSelectedThumb\(\)/,
  "preview selection must independently refresh the selected thumbnail card");

console.log("PASS: preview navigation preserves other desktop captures and refreshes large/card layers independently.");
