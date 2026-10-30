"use strict";
importScripts("comfy-transport.js");
const T=self.BctComfyTransport;
const seen=new Set();
const replyError=e=>({ok:false,error:String(e?.message||e||"COMFY_READ_FAILED").slice(0,120)});
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
 if(message?.type!=="BCT_COMFY_READ_COMMAND_V1"||sender?.id!==chrome.runtime.id)return false;
 Promise.resolve().then(async()=>{
  const req=T.makeComfyReadRequest(message);
  if(seen.has(req.requestId))throw Error("COMFY_DUPLICATE_REQUEST");
  seen.add(req.requestId);
  return T.sendComfyRead(chrome,req);
 }).then(sendResponse).catch(e=>sendResponse(replyError(e)));
 return true;
});
