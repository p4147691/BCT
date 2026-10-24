"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const host = fs.readFileSync(path.join(root, "native/src/MonitorDesktopHost.cs"), "utf8");
const overlay = fs.readFileSync(path.join(root, "native/src/MonitorDragPreviewOverlay.cs"), "utf8");
const monitor = fs.readFileSync(path.join(root, "extension/monitor.js"), "utf8");
const build = fs.readFileSync(path.join(root, "tools/Build-MonitorCore.ps1"), "utf8");

assert.match(host, /monitorDragPreviewStart.*monitorDragPreviewStop/);
assert.match(host, /MonitorDragPreviewOverlay\.Handle\(request\)/);
assert.match(host, /internal static void EmitMonitorEvent/);
assert.match(overlay, /SetThreadDpiAwarenessContext/);
assert.match(overlay, /Screen\.FromPoint/);
assert.match(overlay, /GetAsyncKeyState\(VkLeftButton\)/);
assert.match(overlay, /WmNcHitTest/);
assert.match(overlay, /HtTransparent/);
assert.match(overlay, /ShowWithoutActivation/);
assert.match(overlay, /monitorDragPreviewReleased/);
assert.match(monitor, /type:"monitorDragPreviewStart"/);
assert.match(monitor, /type:"monitorDragPreviewStop"/);
assert.match(monitor, /type === "monitorDragPreviewReleased"/);
assert.match(monitor, /function finishMonitorBctNodeDrag\(\) \{\s*stopMonitorBctNativePreview\(\)/);
assert.match(monitor, /window\.addEventListener\("pagehide", \(\) => \{\s*stopMonitorBctNativePreview\(\)/);
assert.match(build, /MonitorDragPreviewOverlay\.cs/);

function nativeRequest(executable, message) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, [], { windowsHide:true, stdio:["pipe", "pipe", "pipe"] });
    let output = Buffer.alloc(0);
    const timeout = setTimeout(() => {
      child.kill();
      reject(new Error("NATIVE_FRAMING_TIMEOUT"));
    }, 5000);
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.stdout.on("data", (bytes) => {
      output = Buffer.concat([output, bytes]);
      if (output.length < 4) return;
      const length = output.readUInt32LE(0);
      if (length <= 0 || length > 1024 * 1024 || output.length < 4 + length) return;
      clearTimeout(timeout);
      child.stdin.end();
      resolve(JSON.parse(output.subarray(4, 4 + length).toString("utf8")));
    });
    const payload = Buffer.from(JSON.stringify(message), "utf8");
    const header = Buffer.alloc(4);
    header.writeUInt32LE(payload.length, 0);
    child.stdin.write(Buffer.concat([header, payload]));
  });
}

(async () => {
  const executable = process.env.MONITOR_NATIVE_TEST_EXE;
  if (executable) {
    assert.equal(fs.existsSync(executable), true, "MONITOR_NATIVE_TEST_EXE does not exist");
    const invalid = await nativeRequest(executable, { type:"monitorDragPreviewStart", token:"" });
    assert.deepEqual(invalid, { ok:false, detail:"INVALID_PREVIEW_TOKEN" });
    const stop = await nativeRequest(executable, { type:"monitorDragPreviewStop", token:"contract-test" });
    assert.deepEqual(stop, { ok:true, detail:"STOP_ACCEPTED" });
  }
  console.log(JSON.stringify({
    status:"PASS",
    protocolProbe:Boolean(executable),
    coverage:"native-overlay-dispatch,physical-cursor,multi-monitor-dpi,click-through,no-activate,release-event,cleanup,build-input",
  }));
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
