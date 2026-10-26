"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const trace = fs.readFileSync(path.join(root, "extension", "monitor-native-trace.js"), "utf8");
const thumbnails = fs.readFileSync(path.join(root, "domains", "thumbnail-wallpaper.js"), "utf8");
const shared = fs.readFileSync(path.join(root, "domains", "shared-ui.js"), "utf8");

assert.match(trace, /function summary\(type=''\)/);
assert.match(trace, /pending:\[\.\.\.pending\.values\(\)\]/);
assert.match(trace, /bounded\(result\?\.error\)/);
assert.doesNotMatch(trace, /dataUri|wallpaperPath|item=\{\s*message|payload:/,
  "runtime trace must stay metadata-only and never retain image data or request payloads");

assert.match(thumbnails, /function monitorThumbnailBackgroundRuntimeDiagnostics\(\)/);
assert.match(thumbnails, /failure_reason:String\(visual\.dataset\.wallpaperFailureReason/);
assert.match(thumbnails, /thumbnail-background-pending/);
assert.match(thumbnails, /thumbnail-background-failed/);
assert.match(thumbnails, /thumbnail-background-ready/);

assert.match(shared, /thumbnail_background:monitorThumbnailBackgroundRuntimeDiagnostics\(\)/);
assert.match(shared, /MonitorNativeTrace\?\.summary\?\.\("getDesktopVisualSnapshot"\)/);

console.log("PASS: thumbnail runtime diagnostics expose bounded layer and transport metadata only");
