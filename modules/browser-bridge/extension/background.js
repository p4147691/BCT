"use strict";
// No content scripts or external web-page command channel.
const HOST = "com.bct.browser_bridge.prototype";
let port = null;
const pending = new Map();
const identifier = () => crypto.randomUUID().replace(/-/g, "");
const unknown = code => ({ok: false, outcome: "UNKNOWN", error: code});
function connect() {
  if (port) return port;
  const current = chrome.runtime.connectNative(HOST);
  port = current;
  current.onMessage.addListener(reply => {
    const id = reply?.request_id;
    if (typeof id !== "string" || !pending.has(id)) return;
    const callback = pending.get(id); pending.delete(id); callback(reply);
  });
  current.onDisconnect.addListener(() => {
    if (port === current) port = null;
    for (const [id, callback] of pending) { pending.delete(id); callback(unknown("NATIVE_DISCONNECTED_NO_RETRY")); }
  });
  return current;
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !["READ_FIXTURE", "RECEIPT_LOOKUP"].includes(message?.type)) return false;
  const lookup = message.type === "RECEIPT_LOOKUP";
  if (!lookup && (typeof message.path !== "string" || !message.path || message.path.length > 1024)) {
    sendResponse({ok: false, error: "INVALID_PATH"}); return false;
  }
  if (lookup && (typeof message.operationId !== "string" || !/^[a-f0-9]{32}$/.test(message.operationId))) {
    sendResponse({ok: false, error: "INVALID_OPERATION_ID"}); return false;
  }
  const id = lookup ? message.operationId : identifier();
  if (pending.has(id)) { sendResponse(unknown("OPERATION_ALREADY_IN_FLIGHT")); return false; }
  pending.set(id, sendResponse);
  try {
    connect().postMessage({schema_version: 1, type: lookup ? "receipt_lookup" : "bridge_read", request_id: id,
      operation_id: id, capability: "read", arguments: lookup ? {} : {path: message.path}});
  } catch (_) {
    const callback = pending.get(id); pending.delete(id); if (callback) callback(unknown("POST_UNKNOWN_NO_RETRY"));
  }
  return true;
});


// Independent native mailbox channel. Same pinned Bridge host origin,
// separate Native Messaging port and request/receipt namespace from BCT read.
(() => {
  const commands = Object.freeze({
    "BRIDGE_NODE_ENQUEUE": ["node_relay_enqueue",
      ["delivery_id","sender_node","sender_key","receiver_node","receiver_key","original_sha","text"]],
    "BRIDGE_NODE_CLAIM": ["node_relay_claim",
      ["delivery_id","receiver_node","receiver_key"]],
    "BRIDGE_NODE_ACK": ["node_relay_ack",
      ["delivery_id","receiver_node","receiver_key","ack_id"]],
    "BRIDGE_NODE_REPLY": ["node_relay_reply",
      ["delivery_id","receiver_node","receiver_key","ack_id","text","response_sha"]],
    "BRIDGE_NODE_INSPECT": ["node_relay_inspect",
      ["delivery_id","sender_node","sender_key"]]
  });
  let nativePort = null;
  const inflight = new Map();
  const idRx = /^[a-f0-9]{32}$/;
  const nodeRx = /^N(?:[1-9]|[1-9][0-9]{1,2})$/;
  const uuidRx = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  const hashRx = /^[a-f0-9]{64}$/;
  const replyUnknown = (rid, code) => ({
    ok:false,request_id:rid,outcome:"UNKNOWN",error:code,
    chatgpt_submitted:false
  });
  function nativeSession() {
    if(nativePort) return nativePort;
    const current = chrome.runtime.connectNative(HOST);
    nativePort = current;
    current.onMessage.addListener(response => {
      const rid=response?.request_id;
      if(typeof rid!=="string"||!inflight.has(rid))return;
      const callback=inflight.get(rid);inflight.delete(rid);
      callback(response);
    });
    current.onDisconnect.addListener(()=>{
      if(nativePort===current)nativePort=null;
      for(const [rid,callback] of inflight) {
        inflight.delete(rid);
        callback(replyUnknown(rid,"BRIDGE_NODE_NATIVE_DISCONNECTED_NO_RETRY"));
      }
    });
    return current;
  }
  function validated(type, message) {
    const schema=commands[type];
    if(!schema||typeof message?.requestId!=="string"
        ||!idRx.test(message.requestId))throw Error("NODE_REQUEST_ID_INVALID");
    const args=message.arguments;
    if(!args||Array.isArray(args)||typeof args!=="object"
        ||JSON.stringify(Object.keys(args).sort())!==JSON.stringify([...schema[1]].sort()))
      throw Error("NODE_ARGUMENTS_INVALID");
    for(const [name,value] of Object.entries(args)) {
      if(typeof value!=="string")throw Error("NODE_ARGUMENT_TYPE_INVALID");
      if(name.endsWith("_node")&&!nodeRx.test(value))throw Error("NODE_LABEL_INVALID");
      if(name.endsWith("_key")&&!uuidRx.test(value))throw Error("NODE_CONVERSATION_INVALID");
      if(name.endsWith("_sha")&&!hashRx.test(value))throw Error("NODE_SHA_INVALID");
      if((name==="delivery_id"||name==="ack_id")&&!idRx.test(value))
        throw Error("NODE_EFFECT_ID_INVALID");
      if(name==="text"&&(!value||value.length>2000||new TextEncoder().encode(value).length>8192))
        throw Error("NODE_TEXT_BOUNDS_INVALID");
    }
    return {schema_version:1,type:schema[0],request_id:message.requestId,arguments:args};
  }
  chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
    if(sender?.id!==chrome.runtime.id||!commands[message?.type])return false;
    let payload;
    try {payload=validated(message.type,message)}
    catch(error) {
      sendResponse({ok:false,outcome:"INPUT_DENIED",
        error:String(error?.message||"NODE_INPUT_DENIED").slice(0,90)});
      return false;
    }
    const id=payload.request_id;
    if(inflight.has(id)) {
      sendResponse(replyUnknown(id,"NODE_REQUEST_ALREADY_PENDING_NO_RETRY"));
      return false;
    }
    inflight.set(id,sendResponse);
    try {nativeSession().postMessage(payload)}
    catch(_) {
      const callback=inflight.get(id);inflight.delete(id);
      callback?.(replyUnknown(id,"NODE_NATIVE_POST_UNKNOWN_NO_RETRY"));
    }
    return true;
  });
})();
