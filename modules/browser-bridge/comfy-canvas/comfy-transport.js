"use strict";
// BCT-owned fixed command transport. No eval or arbitrary script payload.
function makeComfyReadRequest({requestId,tabId,url,sessionId}) {
 if(!/^[a-f0-9]{32}$/.test(requestId)||!Number.isInteger(tabId)||tabId<=0||
    url!=="http://127.0.0.1:8188/"||typeof sessionId!=="string"||!sessionId)
    throw Error("COMFY_READ_IDENTITY_INVALID");
 return Object.freeze({type:"BCT_COMFY_READ_V1",requestId,tabId,url,sessionId});
}
async function sendComfyRead(chromeApi, request, timeoutMs=3000) {
 const message=makeComfyReadRequest(request);
 const tab=await chromeApi.tabs.get(message.tabId);
 if(tab.url!==message.url)throw Error("COMFY_TAB_URL_MISMATCH");
 const result=await Promise.race([
   chromeApi.tabs.sendMessage(message.tabId,message),
   new Promise((_,reject)=>setTimeout(()=>reject(Error("COMFY_READ_TIMEOUT")),timeoutMs))
 ]);
 if(!result||result.requestId!==message.requestId||result.tab_id!==message.tabId||
    result.url!==message.url||result.session_id!==message.sessionId)
    throw Error("COMFY_RESPONSE_IDENTITY_MISMATCH");
 return result;
}
if(typeof module!=="undefined")module.exports={makeComfyReadRequest,sendComfyRead};
if(typeof self!=="undefined")self.BctComfyTransport={makeComfyReadRequest,sendComfyRead};
