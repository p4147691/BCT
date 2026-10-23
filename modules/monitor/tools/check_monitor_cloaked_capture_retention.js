"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../extension/monitor.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../extension/monitor.css"), "utf8");
const start = source.indexOf("function monitorWindowCanRefreshPixels(");
const end = source.indexOf("\nfunction monitorWindowFallbackDataUri(", start);
assert(start >= 0 && end > start, "cloaked capture policy block");

const context = { Number, String };
vm.createContext(context);
vm.runInContext(`${source.slice(start, end)}; globalThis.policy = { monitorWindowCanRefreshPixels, monitorShouldKeepExistingCapture };`, context);
const policy = context.policy;

assert.equal(policy.monitorWindowCanRefreshPixels({ cloaked: 0 }), true);
assert.equal(policy.monitorWindowCanRefreshPixels({ cloaked: 2 }), false);
assert.equal(policy.monitorWindowCanRefreshPixels({}), true);
assert.equal(policy.monitorShouldKeepExistingCapture("captured", "blob:good", "placeholder"), true);
assert.equal(policy.monitorShouldKeepExistingCapture("captured", "data:image/jpeg;base64,GOOD", "placeholder"), true);
assert.equal(policy.monitorShouldKeepExistingCapture("placeholder", "data:image/svg+xml,OLD", "placeholder"), false);
assert.equal(policy.monitorShouldKeepExistingCapture("captured", "blob:good", "captured"), false);

assert.match(source, /items\.filter\(monitorWindowCanRefreshPixels\)/, "cloaked HWNDs are excluded from WGC refresh");
assert.match(source, /MonitorUiLayout\.chooseCaptureView\(/, "bounded age-aware fallback decision is consulted");
assert.match(source, /if \(img\.src !== renderedSource\) img\.src = renderedSource;/, "validated source or compact fallback is rendered");
assert.match(source, /monitorCapturedAt/, "last successful pixels have an age fence");
assert.match(css, /\.monitor-desktop-thumb\.current\{background:rgba\(255,255,255,\.06\)!important;/, "current desktop card stays dark and transparent");
assert.doesNotMatch(css, /\.monitor-desktop-thumb\.current\{background:rgba\(208,213,219,\.96\)/, "solid grey current-desktop fill is removed");

console.log("PASS: cloaked desktop windows keep their last good pixels and skip grey WGC refreshes");
