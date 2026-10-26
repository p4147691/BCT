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
assert.match(body, /if \(createdDesktopIds\.length && monitorInitialThumbBatchDone\) requestAnimationFrame\(\(\) => \{/);
assert.match(body, /for \(const desktopId of createdDesktopIds\)/);
assert.match(body, /refreshDesktopThumb\(visual, desktopId\)/);
assert.doesNotMatch(body, /pixels stay lazy until an explicit selection\/layout operation/);

const thumbnails = fs.readFileSync(path.join(__dirname, "../domains/thumbnail-wallpaper.js"), "utf8");
const refreshStart = thumbnails.indexOf("async function refreshDesktopThumb(visual, desktopId)");
const refreshEnd = thumbnails.indexOf("//@@FN_END:refreshDesktopThumb", refreshStart);
const refreshBody = thumbnails.slice(refreshStart, refreshEnd);
assert.match(refreshBody, /renderer\.refresh\(visual,desktopId\)/);
assert.doesNotMatch(refreshBody, /captureDesktopFrame|refreshWallpaper|windowFrame|frameFailure/,
  "the compatibility bundle must not reimplement thumbnail orchestration");
const compositor = fs.readFileSync(path.join(__dirname, "../extension/monitor-desktop-thumbnail-v2.js"), "utf8");
assert.match(compositor, /ok:backgroundReady/,
  "initial thumbnail acceptance must follow the independent background-layer result");
assert.match(compositor, /compositeReady/,
  "window-frame readiness must remain observable without blocking wallpaper acceptance");
const initialStart = thumbnails.indexOf("async function refreshInitialSelectedThumb()");
const initialEnd = thumbnails.indexOf("//@@FN_END:refreshInitialSelectedThumb", initialStart);
const initialBody = thumbnails.slice(initialStart, initialEnd);
assert.match(initialBody, /selectedReady === true && backgroundReady === true/,
  "initial completion requires selected and background desktop acceptance");

console.log("PASS: startup has one thumbnail owner, later desktop creation is explicit, and all initial tiles gate completion");
