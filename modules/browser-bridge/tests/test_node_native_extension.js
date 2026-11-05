"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const requestId="a".repeat(32);
const request={
  type:"BRIDGE_NODE_ENQUEUE",requestId,arguments:{
    delivery_id:"b".repeat(32),
    sender_node:"N23",sender_key:"33333333-3333-4333-8333-333333333333",
    receiver_node:"N14",receiver_key:"22222222-2222-4222-8222-222222222222",
    original_sha:"c".repeat(64),text:"synthetic mailbox request"}
};
const ports=[];
const posted=[];
const handlers=[];
const chrome={runtime:{
  id:"acdgnmbgpkfjkckccbhmccojgigbfcge",
  onMessage:{addListener:fn=>handlers.push(fn)},
  connectNative:name=>{
    assert.equal(name,"com.bct.browser_bridge.prototype");
    const port={onMessage:{addListener(fn){port.receive=fn}},
      onDisconnect:{addListener(fn){port.disconnected=fn}},
      postMessage(packet){posted.push(packet)}};
    ports.push(port);return port;
  }
}};
const ctx=vm.createContext({chrome,crypto:{randomUUID:()=>requestId},
  TextEncoder,Map,Set,Object,JSON,Error,Promise,console});
vm.runInContext(fs.readFileSync("extension/background.js","utf8"),ctx);
function send(message,sender=chrome.runtime.id){
 return new Promise(resolve=>{
   let allowed=false;
   for(const fn of handlers) {
     if(fn(message,{id:sender},resolve))allowed=true;
   }
   if(!allowed)resolve({ignored:true});
 });
}
(async()=>{
  const pending=send(request);
  assert.equal(ports.length,1,"new dedicated port must exist");
  assert.equal(posted.length,1);
  assert.equal(posted[0].type,"node_relay_enqueue");
  assert.equal(posted[0].request_id,requestId);
  assert.equal(posted[0].arguments.text,"synthetic mailbox request");
  ports[0].receive({ok:true,request_id:requestId,outcome:"APPLIED",
    receipt:{delivery_id:request.arguments.delivery_id,state:"QUEUED"}});
  const receipt=await pending;
  assert.equal(receipt.ok,true);
  assert.equal(receipt.receipt.state,"QUEUED");
  assert.equal((await send({...request,requestId:"INVALID"})).ok,false);
  assert.equal(posted.length,1,"invalid request must not invoke Native Host");
  const second={...request,requestId:"d".repeat(32)};
  const disconnected=send(second);
  assert.equal(posted.length,2);
  ports[0].disconnected();
  const lost=await disconnected;
  assert.equal(lost.outcome,"UNKNOWN");
  assert.match(lost.error,/NO_RETRY/);
  assert.equal(posted.length,2,"not retransmitted after disconnection");
  const receiptLookup=send({type:"BRIDGE_NODE_INSPECT",requestId:"e".repeat(32),
   arguments:{delivery_id:request.arguments.delivery_id,sender_node:"N23",
     sender_key:request.arguments.sender_key}});
  assert.equal(ports.length,2,"independent port reconnected");
  assert.equal(posted.length,3);
  ports[1].receive({ok:true,request_id:"e".repeat(32),outcome:"APPLIED",
    receipt:{delivery_id:request.arguments.delivery_id,state:"QUEUED",replayed:true}});
  assert.equal((await receiptLookup).receipt.replayed,true);
  const unauthorized=await send(request,"malicious-origin");
  assert.equal(unauthorized.ignored,true);
  assert.equal(posted.length,3);
  console.log("Browser Bridge pinned-ID Native Messaging port: PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
