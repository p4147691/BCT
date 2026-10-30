"use strict";
(()=>{if(location.origin!=="http://127.0.0.1:8188")return;
const REQUEST="BCT_COMFY_READ_REQUEST_V1",RESULT="BCT_COMFY_READ_RESULT_V1";
window.addEventListener(REQUEST,event=>{
 const nonce=event?.detail?.nonce;
 if(typeof nonce!=="string"||!/^[a-f0-9]{32}$/.test(nonce))return;
 let payload;
 try{
  const graph=window.app?.graph;
  if(!graph||typeof graph.serialize!=="function")throw Error("GRAPH_UNAVAILABLE");
  const data=structuredClone(graph.serialize());
  if(!Array.isArray(data?.nodes)||!Array.isArray(data?.links))throw Error("GRAPH_INVALID");
  payload={ok:true,graph:data};
 }catch(_){payload={ok:false,error:"COMFY_LIVE_GRAPH_UNAVAILABLE"}}
 window.dispatchEvent(new CustomEvent(RESULT,{detail:{nonce,...payload}}));
});
})();