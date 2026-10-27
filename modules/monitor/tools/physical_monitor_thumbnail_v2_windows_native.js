"use strict";
// Physical Windows acceptance for the second V2 layer. It reads metadata and
// one in-memory WGC frame only; no image is saved or sent elsewhere.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path");
const {spawn}=require("node:child_process");
const configured=JSON.parse(fs.readFileSync(path.join(__dirname,"../native/com.pas40.desktop_window_monitor_control.json"),"utf8"));
const hostPath=process.argv[2]||configured.path;
const host=spawn(hostPath,[],{stdio:["pipe","pipe","inherit"],windowsHide:true});
let received=Buffer.alloc(0),sequence=0;
const pending=new Map();
host.stdout.on("data",chunk=>{
  received=Buffer.concat([received,chunk]);
  while(received.length>=4){
    const size=received.readUInt32LE(0);
    if(received.length<size+4)return;
    const reply=JSON.parse(received.subarray(4,size+4).toString("utf8"));
    received=received.subarray(size+4);
    if(reply.event===true)continue;
    const waiter=pending.get(String(reply.requestId||""));
    if(waiter){pending.delete(String(reply.requestId));waiter.resolve(reply)}
  }
});
host.on("error",error=>{for(const waiter of pending.values())waiter.reject(error);pending.clear()});
function request(message){
  const requestId="physical-window-"+(++sequence);
  const body=Buffer.from(JSON.stringify({...message,requestId}),"utf8");
  const header=Buffer.alloc(4);header.writeUInt32LE(body.length,0);
  return new Promise((resolve,reject)=>{pending.set(requestId,{resolve,reject});host.stdin.write(Buffer.concat([header,body]))});
}

(async()=>{
  try{
    const topology=await request({type:"getVirtualDesktops"});
    assert.equal(topology.ok,true,topology.error||"getVirtualDesktops failed");
    const desktopId=String(topology.desktopIds?.[topology.currentIndex]||topology.desktopIds?.[0]||"");
    assert.match(desktopId,/^[0-9a-f-]{36}$/i);
    const all=await request({type:"getDesktopWindowHandles",desktopId,includeMonitorWindows:true});
    assert.equal(all.ok,true,all.error||"getDesktopWindowHandles failed");
    const rows=all.windows||[];
    const monitor=rows.find(row=>/^(?:BCT Window Monitor|DesktopWindow Monitor|DWM(?: ·|$))/i.test(String(row.title||"")));
    const exactHostCandidate=monitor||rows[0];
    assert(exactHostCandidate,"no HWND available for exact host exclusion acceptance");
    const withoutHost=await request({type:"getDesktopWindowHandles",desktopId,hostWindowHwnd:String(exactHostCandidate.hwnd),includeMonitorWindows:true});
    assert.equal(withoutHost.ok,true);
    assert.equal((withoutHost.hwnds||[]).map(String).includes(String(exactHostCandidate.hwnd)),false,
      "exact host HWND must be excluded even when Monitor-title filtering is disabled");
    const candidate=(all.windows||[]).find(row=>row.visible!==false&&!row.iconic&&String(row.hwnd)!==String(monitor?.hwnd||"")&&String(row.title||"").trim());
    assert(candidate,"no visible non-Monitor HWND available for WGC acceptance");
    const capture=await request({type:"captureWindow",hwnd:String(candidate.hwnd),maxWidth:480,maxHeight:270,quality:52});
    assert.equal(capture.ok,true,capture.error||"captureWindow failed");
    assert.equal(capture.captureEngine,"wgc-oneshot");
    assert.match(String(capture.dataUri||""),/^data:image\/(?:jpeg|png|webp);base64,/i);
    console.log(JSON.stringify({ok:true,desktopId,exactHostFilterVerified:true,monitorTitleObserved:Boolean(monitor),capturedHwnd:String(candidate.hwnd),captureEngine:capture.captureEngine,width:Number(capture.width||0),height:Number(capture.height||0)}));
  }finally{host.kill()}
})().catch(error=>{console.error(error.stack||error);host.kill();process.exitCode=1});
