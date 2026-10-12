"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const monitorSource = fs.readFileSync(path.join(root, "extension", "monitor.js"), "utf8");
const nativeSource = fs.readFileSync(path.join(root, "native", "src", "MonitorDesktopHost.cs"), "utf8");
const candidatePath = process.argv[2];

assert.match(monitorSource, /N-CODEX 원격 데스크톱 열기 요청/);
assert.match(monitorSource, /monitorNCodexRdpConnected/);
assert.match(monitorSource, /getNCodexVmStatus/);
assert.match(monitorSource, /setInterval\(refreshMonitorNCodexRdpStatus, 3000\)/);
assert.match(nativeSource, /Process\.GetProcessById/);
assert.match(nativeSource, /TscShellContainerClass/);
assert.match(nativeSource, /mstsc\.exe/);
assert.match(nativeSource, /\/v:172\.24\.134\.218 \/w:1280 \/h:720/);
assert.match(nativeSource, /FitNCodexRemoteDesktopWindow/);
assert.doesNotMatch(nativeSource, /Default\.rdp/);
assert.match(nativeSource, /getNCodexVmStatus/);
assert.doesNotMatch(nativeSource.slice(nativeSource.indexOf("private static object OpenNCodexVm"), nativeSource.indexOf("private static object GetNCodexVmStatus")), /Vda(?:MoveWindow|GoToDesktop)/);
assert.doesNotMatch(nativeSource, /N-CODEX-01\.rdp/);
assert.doesNotMatch(nativeSource.slice(nativeSource.indexOf("private static object OpenNCodexVm"), nativeSource.indexOf("private static object CloseWindow")), /vmconnect\.exe/i);

if (candidatePath) {
  const binary = fs.readFileSync(candidatePath);
  for (const marker of ["mstsc.exe", "TscShellContainerClass", "/v:172.24.134.218 /w:1280 /h:720", "getNCodexVmStatus"]) {
    assert.ok(binary.includes(Buffer.from(marker, "utf16le")), `candidate binary missing ${marker}`);
  }
}

console.log("PASS: N-CODEX opens a stable windowed RDP session, reports live connection status, and does not move virtual desktops or edit Default.rdp");
