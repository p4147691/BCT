"use strict";
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");

const hostPath = process.argv[2];
assert(hostPath, "candidate Native Host path is required");
const host = spawn(hostPath, [], { stdio: ["pipe", "pipe", "inherit"], windowsHide: true });
let buffered = Buffer.alloc(0);
let settled = false;
let probe = null;
let timeout = null;
const recentEvents = [];
const recentReplies = [];
let hostExit = null;

function finish(error, event) {
  if (settled) return;
  settled = true;
  if (timeout) clearTimeout(timeout);
  try { host.kill(); } catch (_) {}
  try { probe?.kill(); } catch (_) {}
  if (error) {
    console.error(error.stack || error);
    process.exitCode = 1;
    return;
  }
  console.log(`PASS: Native Host emitted ${event.reason} for temporary HWND ${event.hwnd} at ${event.left},${event.top} ${event.width}x${event.height}.`);
}

host.stdout.on("data", chunk => {
  buffered = Buffer.concat([buffered, chunk]);
  while (buffered.length >= 4) {
    const size = buffered.readUInt32LE(0);
    if (buffered.length < size + 4) return;
    const event = JSON.parse(buffered.subarray(4, size + 4).toString("utf8"));
    buffered = buffered.subarray(size + 4);
    if (event?.event === true) {
      recentEvents.push({type:event.type,reason:event.reason,title:event.title,hwnd:event.hwnd,left:event.left,top:event.top,width:event.width,height:event.height});
      if (recentEvents.length > 20) recentEvents.shift();
    } else {
      recentReplies.push(event);
      if (recentReplies.length > 5) recentReplies.shift();
    }
    if (event?.event === true && event.type === "windowMoveSizeEnd" &&
        event.reason === "locationchange" && event.title === "BCT Native Event Probe") {
      if (Number(event.left) !== 170 || Number(event.top) !== 190 ||
          Number(event.width) !== 460 || Number(event.height) !== 300) continue;
      try {
        assert.equal(Number(event.left), 170);
        assert.equal(Number(event.top), 190);
        assert.equal(Number(event.width), 460);
        assert.equal(Number(event.height), 300);
        finish(null, event);
      } catch (error) { finish(error); }
    }
  }
});
host.on("error", finish);
host.on("exit", (code, signal) => { hostExit = {code, signal}; });

function sendRequest(message) {
  const body = Buffer.from(JSON.stringify(message), "utf8");
  const frame = Buffer.alloc(4 + body.length);
  frame.writeUInt32LE(body.length, 0);
  body.copy(frame, 4);
  host.stdin.write(frame);
}
sendRequest({type:"getVirtualDesktops",requestId:"event-live-ready"});

const ps = [
  "Add-Type -AssemblyName System.Windows.Forms",
  "$f=New-Object System.Windows.Forms.Form",
  "$f.Text='BCT Native Event Probe'",
  "$f.StartPosition='Manual'",
  "$f.SetBounds(40,60,320,220)",
  "Start-Sleep -Milliseconds 900",
  "$f.Show()",
  "[System.Windows.Forms.Application]::DoEvents()",
  "Start-Sleep -Milliseconds 500",
  "$f.SetBounds(170,190,460,300)",
  "[System.Windows.Forms.Application]::DoEvents()",
  "Start-Sleep -Milliseconds 900",
  "$f.Close()"
].join("; ");
probe = spawn("powershell.exe", ["-NoProfile", "-STA", "-Command", ps], {
  stdio: ["ignore", "ignore", "inherit"], windowsHide: true
});
probe.on("error", finish);
setTimeout(() => {
  if (!settled) sendRequest({type:"getWindowEventDiagnostics",requestId:"event-live-diagnostics"});
}, 3500);
timeout = setTimeout(() => finish(new Error(`temporary window LOCATIONCHANGE event was not observed; replies=${JSON.stringify(recentReplies)} events=${JSON.stringify(recentEvents)} exit=${JSON.stringify(hostExit)}`)), 7000);
