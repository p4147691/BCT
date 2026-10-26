const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const lifecycle = fs.readFileSync(path.join(root, "domains", "desktop-lifecycle.js"), "utf8");
const shared = fs.readFileSync(path.join(root, "domains", "shared-ui.js"), "utf8");
const native = fs.readFileSync(path.join(root, "native", "src", "MonitorDesktopHost.cs"), "utf8");

function marked(source, name) {
  const start = source.indexOf(`//@@FN_START:${name}`);
  const end = source.indexOf(`//@@FN_END:${name}`);
  assert.ok(start >= 0 && end > start, `missing function boundary: ${name}`);
  return source.slice(start, end);
}

const select = marked(lifecycle, "selectVirtualDesktopPreview");
const applyShared = marked(lifecycle, "monitorApplySharedDesktopSelection");
const publishShared = marked(shared, "publishMonitorSharedSelection");
for (const [name, source] of Object.entries({ select, applyShared, publishShared })) {
  assert.doesNotMatch(source, /switchVirtualDesktop/, `${name} must never switch the real Windows desktop`);
  assert.doesNotMatch(source, /SetDesktopWallpaperPath|setWallpaper/i, `${name} must never write wallpaper state`);
}

const compact = lifecycle.replace(/\r/g, "").replace(/^\s*$/gm, "");
const singleClick = compact.match(/button\.addEventListener\("click",[\s\S]{0,420}?selectVirtualDesktopPreview/g) || [];
const doubleClick = compact.match(/button\.addEventListener\("dblclick",[\s\S]{0,700}?type\s*:\s*"switchVirtualDesktop"/g) || [];
assert.equal(singleClick.length, 2, "both thumbnail renderers must keep single click preview-only");
assert.equal(doubleClick.length, 2, "both thumbnail renderers must require double click for a real desktop switch");

const switchStart = native.indexOf("private static object SwitchVirtualDesktop");
const switchEnd = native.indexOf("private static object LaunchNaverChatGpt", switchStart);
assert.ok(switchStart >= 0 && switchEnd > switchStart, "native switch method boundary missing");
const nativeSwitch = native.slice(switchStart, switchEnd);
assert.doesNotMatch(nativeSwitch, /SetDesktopWallpaperPath|SetValue\("Wallpaper"|SetBackgroundColor|SetWallpaper\(/,
  "virtual desktop switch must never mutate wallpaper state");

console.log("PASS: thumbnail single click is preview-only, double click owns switching, and switching never writes wallpaper");
