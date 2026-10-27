"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../native/src/MonitorDesktopHost.cs"), "utf8");
const locationStart = source.indexOf("private static void OnWindowLocationChange");
const locationEnd = source.indexOf("private static void OnWindowCloakChange", locationStart);
const locationBody = source.slice(locationStart, locationEnd);
assert(locationStart >= 0 && locationEnd > locationStart, "location-change callback must remain discoverable");
assert(!/ActiveMoveSizeWindows\.Contains\([^)]*\)\)\s*return/.test(locationBody),
  "active mouse movement must not discard the location event needed by keyboard Snap");
assert.match(locationBody, /ScheduleWindowSettled\(hWnd,\s*"locationchange",\s*moveSizeActive\s*\?\s*140\s*:\s*85\)/,
  "location changes must converge with a bounded active-move fallback");

const moveStart = source.indexOf("private static void OnWindowMoveEvent");
const moveEnd = source.indexOf("private static void OnWindowLocationChange", moveStart);
const moveBody = source.slice(moveStart, moveEnd);
assert.match(moveBody, /WindowSettleTimers\.TryGetValue\(key, out pendingTimer\)/,
  "a real move-size end must cancel its pending location fallback");
assert.match(moveBody, /EmitWindowSettled\(hWnd,\s*"movesizeend",\s*GetObservedWindowDesktopId\(hWnd\)\)/,
  "a real move-size end must publish immediately with the last observed desktop mapping");

const settleStart = source.indexOf("private static void ScheduleWindowSettled");
const settleEnd = source.indexOf("private static void EmitWindowSettled", settleStart);
const settleBody = source.slice(settleStart, settleEnd);
assert.match(settleBody, /Object\.ReferenceEquals\(currentTimer, timer\)/,
  "only the newest debounce timer may publish or clear the HWND slot");
assert.match(settleBody, /if \(ownsSlot\) EmitWindowSettled\(hWnd, reason, desktopId\)/,
  "only the current timer may publish geometry with the accepted desktop GUID");
assert.match(source, /Dictionary<long, System\.Threading\.Timer> WindowSettleTimers/,
  "settlement must use a one-shot timer independent of the WinEvent message pump");
assert.match(settleBody, /GetObservedWindowDesktopId\(hWnd\)/,
  "the WinEvent callback must reuse the last authoritative HWND-to-desktop mapping");
assert.doesNotMatch(settleBody, /GetWindowDesktopId\(hWnd\)/,
  "the WinEvent callback must not depend on transient virtual-desktop COM registration");
assert.match(settleBody, /EmitWindowSettled\(hWnd, reason, desktopId\)/,
  "the delayed callback must reuse the GUID accepted on the WinEvent thread");
assert.doesNotMatch(settleBody.slice(settleBody.indexOf("new System.Threading.Timer")), /GetWindowDesktopId\(hWnd\)/,
  "the ThreadPool callback must not perform virtual-desktop COM work");

console.log("PASS: Native location events cover keyboard Snap, mouse completion stays immediate, and stale timers cannot publish.");
