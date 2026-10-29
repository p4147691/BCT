"use strict";
(()=>{if(location.origin!=="http://127.0.0.1:8188")return;
const pending=new Map(),seen=new Set(),REQUEST="BCT_COMFY_READ_REQUEST_V1",RESULT="BCT_COMFY_READ_RESULT_V1";
window.addEventListener(RESULT,event=>{
 const detail=event?.detail||{},nonce=detail.nonce,entry=pending.get(nonce);
 if(!entry)return;
 pending.delete(nonce);clearTimeout(entry.timer);
 const {nonce:ignored,...payload}=detail;
 entry.reply({...payload,requestId:entry.requestId,tab_id:entry.tabId,url:entry.url,session_id:entry.sessionId});
});
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
 if(message?.type!=="BCT_COMFY_READ_V1")return false;
 if(sender.id!==chrome.runtime.id||message.url!==location.href||
 !Number.isInteger(message.tabId)||message.tabId<=0||
 !/^[a-f0-9]{32}$/.test(message.requestId||"")||
 typeof message.sessionId!=="string"||!message.sessionId||
 seen.has(message.requestId)){
 sendResponse({ok:false,error:"COMFY_IDENTITY_INVALID"});return false;
 }
 seen.add(message.requestId);
 const nonce=crypto.randomUUID().replace(/-/g,"");
 const timer=setTimeout(()=>{const entry=pending.get(nonce);if(!entry)return;
 pending.delete(nonce);entry.reply({ok:false,error:"COMFY_READ_TIMEOUT",requestId:entry.requestId,tab_id:entry.tabId,url:entry.url,session_id:entry.sessionId});},3000);
 pending.set(nonce,{timer,reply:sendResponse,requestId:message.requestId,tabId:message.tabId,url:message.url,sessionId:message.sessionId});
 window.dispatchEvent(new CustomEvent(REQUEST,{detail:{nonce}}));
 return true;
});
})();