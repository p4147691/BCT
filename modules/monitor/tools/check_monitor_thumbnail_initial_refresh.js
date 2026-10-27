"use strict";

// Lifecycle owns the first background read; V2 owns the pixels thereafter.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../domains/desktop-lifecycle.js"), "utf8");
const sharedUi = fs.readFileSync(path.join(__dirname, "../domains/shared-ui.js"), "utf8");
const begin = source.indexOf("function syncDesktopSwitcher() {");
const end = source.indexOf("//@@FN_END:syncDesktopSwitcher", begin);
assert(begin >= 0 && end > begin, "syncDesktopSwitcher source boundary is required");
const body = source.slice(begin, end);

assert.match(body, /const createdDesktopIds = \[\];/);
assert.match(body, /createdDesktopIds\.push\(desktopId\);/);
assert.match(body, /if \(createdDesktopIds\.length\) requestAnimationFrame\(\(\) => \{/);
assert.match(body, /for \(const desktopId of createdDesktopIds\)/);
assert.match(body, /renderer\?\.refreshBackground\?\.\(visual, desktopId\)/);
assert.doesNotMatch(body, /monitorInitialThumbBatchDone/,
  "new canonical cards must not wait on the batch they help complete");
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
assert.match(initialBody, /monitorInitialThumbBatchDone = backgroundReady === true/,
  "initial completion must depend only on the independent background layer");
assert.match(initialBody, /await refreshInitialWindowThumbs\(\)/,
  "background acceptance must be followed by a bounded all-desktop window pass");
const windowsStart = thumbnails.indexOf("async function refreshInitialWindowThumbs()");
const windowsEnd = thumbnails.indexOf("//@@FN_END:refreshInitialWindowThumbs", windowsStart);
const windowsBody = thumbnails.slice(windowsStart, windowsEnd);
assert(windowsStart >= 0 && windowsEnd > windowsStart, "initial window refresh owner is required");
assert.match(windowsBody, /\.\.\.monitorDesktopState\.desktopIds\.filter/,
  "startup window pass must include every canonical desktop, not only the selection");
assert.match(windowsBody, /renderer\.refresh\(visual, desktopId\)/,
  "every desktop must enter the V2 background-plus-window compositor");
assert.match(windowsBody, /result\?\.frameReady !== true/,
  "window readiness must be reported independently for every desktop");
const backgroundsStart = thumbnails.indexOf("async function refreshInitialBackgroundThumbs()");
const backgroundsEnd = thumbnails.indexOf("//@@FN_END:refreshInitialBackgroundThumbs", backgroundsStart);
const backgroundsBody = thumbnails.slice(backgroundsStart, backgroundsEnd);
assert.match(backgroundsBody, /renderer\.refreshBackground\(visual, desktopId\)/,
  "startup must explicitly refresh the exact-GUID background layer");
assert.doesNotMatch(backgroundsBody, /refreshDesktopThumb\(/,
  "startup background acceptance must not depend on the HWND frame layer");
assert.doesNotMatch(backgroundsBody, /monitorIsActiveDesktopRenderer/,
  "exact-GUID backgrounds must not inherit the Monitor HWND ownership gate");

const eventStart = thumbnails.indexOf("async function refreshBackgroundThumbs(...desktopIds)");
const eventEnd = thumbnails.indexOf("//@@FN_END:refreshBackgroundThumbs", eventStart);
const eventBody = thumbnails.slice(eventStart, eventEnd);
assert.match(eventBody, /renderer\.refreshBackground\(visual, desktopId\)/,
  "wallpaper events must enter the background-only port");
assert.doesNotMatch(eventBody, /monitorIsActiveDesktopRenderer|monitorCapturePaused|refreshDesktopThumb\(/,
  "background events must stay independent from active HWND capture state");

const observedStart = sharedUi.indexOf("async function refreshObservedWindows()");
const observedEnd = sharedUi.indexOf("//@@FN_END:refreshObservedWindows", observedStart);
assert(observedStart >= 0 && observedEnd > observedStart,
  "refreshObservedWindows must remain discoverable in shared-ui");
assert.match(sharedUi.slice(observedStart, observedEnd), /monitorIsActiveDesktopRenderer\(\)/,
  "the active-desktop ownership gate must remain on HWND capture");

const lifecycleStart = source.indexOf("async function refreshVirtualDesktops()");
const lifecycleEnd = source.indexOf("//@@FN_END:refreshVirtualDesktops", lifecycleStart);
const lifecycleBody = source.slice(lifecycleStart, lifecycleEnd);
const initialRefresh = lifecycleBody.indexOf("if (!monitorInitialThumbBatchDone) await refreshInitialSelectedThumb()");
const identityResolve = lifecycleBody.indexOf("MonitorHostWindowIdentity.resolve(topology");
const hwndGate = lifecycleBody.indexOf("const resolved = /^\\d+$/");
assert(initialRefresh >= 0 && identityResolve > initialRefresh && hwndGate > identityResolve,
  "exact-GUID backgrounds must start before Monitor HWND identity resolution and window capture");
assert.match(lifecycleBody, /try \{\s*renderVirtualDesktops\(topology\);\s*\} catch \(error\)/,
  "optional card rendering failures must not skip the independent background startup");
assert.match(body, /allowsLayer\?\.\("summary"\) !== false/,
  "summary decoration must remain optional after background scheduling");

console.log("PASS: exact-GUID backgrounds start independently, canonical cards use the background port, and HWND capture keeps its active-desktop gate");
