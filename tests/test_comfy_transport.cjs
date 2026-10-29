"use strict";
const assert=require("node:assert/strict");
const {makeComfyReadRequest,sendComfyRead}=require("../modules/browser-bridge/comfy-canvas/comfy-transport.js");
const id="a".repeat(32), url="http://127.0.0.1:8188/";
(async()=>{
 const req={requestId:id,tabId:123,url,sessionId:"session-1"};
 const chromeApi={tabs:{get:async()=>({url}),sendMessage:async(_,m)=>({requestId:m.requestId,tab_id:m.tabId,url:m.url,session_id:m.sessionId,ok:true})}};
 assert.equal((await sendComfyRead(chromeApi,req)).ok,true);
 await assert.rejects(sendComfyRead({tabs:{get:async()=>({url:"http://evil.test/"})}},req),/URL_MISMATCH/);
 await assert.rejects(sendComfyRead({tabs:{get:async()=>({url}),sendMessage:async()=>new Promise(()=>{})}},req,5),/TIMEOUT/);
 await assert.rejects(sendComfyRead({tabs:{get:async()=>({url}),sendMessage:async()=>({requestId:id,tab_id:999,url,session_id:"session-1"})}},req),/IDENTITY_MISMATCH/);
 assert.throws(()=>makeComfyReadRequest({...req,url:"http://localhost:8188/"}),/IDENTITY_INVALID/);
 console.log("COMFY_TRANSPORT_5_PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
