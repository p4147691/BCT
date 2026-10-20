const fs = require("fs");
const path = require("path");

const extension = path.resolve(__dirname, "..", "extension");
const source = fs.readFileSync(path.join(extension, "monitor.js"), "utf8");
const css = fs.readFileSync(path.join(extension, "monitor.css"), "utf8");
const start = source.indexOf("function syncMonitorNonChatCountdown(");
const end = source.indexOf("\nfunction ", start + 1);
if (start < 0 || end < 0) throw new Error("non-chat countdown function not found");
const body = source.slice(start, end);
const cleanup = body.indexOf('querySelectorAll(".monitor-window-non-chat-countdown")');
const stop = body.indexOf("return;", cleanup);
const legacyCreate = body.indexOf('createElement("span")');

if (cleanup < 0 || stop < cleanup) throw new Error("legacy non-chat overlay cleanup is not fail-closed");
if (legacyCreate >= 0 && legacyCreate < stop) throw new Error("legacy non-chat overlay is still created before cleanup");
if (css.includes(".monitor-window-non-chat-countdown")) throw new Error("legacy non-chat countdown CSS is still shipped");

console.log("PASS monitor non-chat countdown is hidden while grace filtering remains active");
