"use strict";

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const path = require("node:path");

const hostPath = process.argv[2] || path.join(__dirname, "..", "native", "1.9.20.156-desktop-visual", "DesktopWindowMonitorHost.exe");
const host = spawn(hostPath, [], { stdio: ["pipe", "pipe", "inherit"] });
let received = Buffer.alloc(0);
const waiters = [];

host.stdout.on("data", (chunk) => {
  received = Buffer.concat([received, chunk]);
  while (received.length >= 4) {
    const length = received.readUInt32LE(0);
    if (received.length < length + 4) return;
    const payload = JSON.parse(received.subarray(4, length + 4).toString("utf8"));
    received = received.subarray(length + 4);
    waiters.shift()?.resolve(payload);
  }
});
host.on("error", (error) => waiters.splice(0).forEach((waiter) => waiter.reject(error)));

function request(message) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify(message), "utf8");
    const header = Buffer.alloc(4);
    header.writeUInt32LE(body.length, 0);
    waiters.push({ resolve, reject });
    host.stdin.write(Buffer.concat([header, body]));
  });
}

(async () => {
  try {
    const desktops = await request({ type: "getVirtualDesktops" });
    assert.equal(desktops.ok, true, desktops.error || "getVirtualDesktops failed");
    const desktopId = desktops.desktopIds?.[desktops.currentIndex] || desktops.desktopIds?.[0];
    assert.match(String(desktopId || ""), /^[0-9a-f-]{36}$/i, "no desktop id returned");
    const visual = await request({ type: "getDesktopVisualSnapshot", desktopId, maxWidth: 960, maxHeight: 600, quality: 68 });
    assert.equal(visual.ok, true, visual.error || "getDesktopVisualSnapshot failed");
    assert.equal(String(visual.desktopId).toLowerCase(), String(desktopId).toLowerCase());
    if (visual.wallpaper) {
      assert.match(visual.wallpaper.dataUri, /^data:image\/jpeg;base64,/);
      assert.ok(visual.wallpaper.width > 0 && visual.wallpaper.height > 0);
    }
    console.log(JSON.stringify({ ok: true, desktopId, wallpaper: Boolean(visual.wallpaper), width: visual.wallpaper?.width || 0, height: visual.wallpaper?.height || 0, mode: visual.wallpaper?.mode || "" }));
  } finally {
    host.kill();
  }
})().catch((error) => {
  console.error(error.stack || error);
  host.kill();
  process.exitCode = 1;
});
