"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
for(const name of ["extension/monitor.js","native/src/MonitorDesktopHost.cs"]){
 const source=fs.readFileSync(path.join(root,name),"utf8");
 for(const retired of ["monitorNCodexRdpConnected","getNCodexVmStatus","FitNCodexRemoteDesktopWindow","172.24.134.218"]){
  assert.equal(source.includes(retired),false,name+" must not restore removed "+retired);
 }
}
console.log("PASS: retired N-CODEX code stays absent from active Monitor and Native Host");
