"use strict";

// Lifecycle owns the first background read; V2 owns the pixels thereafter.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../domains/desktop-lifecycle.js"), "utf8");
const begin = source.indexOf("function syncDesktopSwitcher() {");
const end = source.indexOf("//@@FN_END:syncDesktopSwitcher", begin);
assert(begin >= 0 && end > begin, "syncDesktopSwitcher source boundary is required");
const body = source.slice(begin, end);

assert.match(body, /const createdDesktopIds = \[\];/);
assert.match(body, /createdDesktopIds\.push\(desktopId\);/);
assert.match(body, /if \(createdDesktopIds\.length\) requestAnimationFrame\(\(\) => \{/);
assert.match(body, /for \(const desktopId of createdDesktopIds\)/);
assert.match(body, /refreshDesktopThumb\(visual, desktopId\)/);
assert.doesNotMatch(body, /pixels stay lazy until an explicit selection\/layout operation/);

console.log("PASS: every newly created desktop tile schedules its initial V2 wallpaper refresh");
