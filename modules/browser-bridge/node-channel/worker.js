"use strict";
importScripts("protocol.js","page_reader.js");
const P=self.BctIndependentNodeProtocol;
const KEY="bctNodeBindingsLabV1";
const error=(e)=>({ok:false,error:String(e?.message||e||"NODE_READ_UNKNOWN").slice(0,150)});
async function tabs(){ return chrome.tabs.query({}); }
async function readExactNode(m,currentTabs,stored) {
  const {nodeId,conversationKey}=P.validateBinding(m.nodeId,m.conversationKey);
  if(stored[nodeId]!==conversationKey)throw Error("NODE_BINDING_NOT_REGISTERED");
  P.matchExact(currentTabs,conversationKey,m.tabId);
  const response=await chrome.scripting.executeScript({
    target:{tabId:m.tabId},func:bctIndependentReadNode,args:[conversationKey]});
  if(response.length!==1)throw Error("NODE_READ_NOT_UNIQUE");
  return {ok:true,nodeId,tabId:m.tabId,
    ...P.sanitizeSnapshot(response[0].result,conversationKey),
    transport:"BRIDGE_EXTENSION_READ_ONLY"};
}
async function handle(m) {
  if(m?.type==="BRIDGE_NODE_LIST") {
    const result=P.nodes(await tabs());
    const stored=(await chrome.storage.local.get(KEY))[KEY]||{};
    return {ok:true,nodes:result.distinct.map(n=>({...n,
      nodeId:Object.keys(stored).find(label=>stored[label]===n.conversationKey)||null})),
      duplicates:result.duplicates, transport:"BRIDGE_EXTENSION_READ_ONLY"};
  }
  if(m?.type==="BRIDGE_NODE_BIND") {
    const {nodeId,conversationKey}=P.validateBinding(m.nodeId,m.conversationKey);
    const found=P.nodes(await tabs());
    if(found.duplicates.some(x=>x.conversationKey===conversationKey)||
       !found.distinct.some(x=>x.conversationKey===conversationKey)) throw Error("NODE_BIND_TARGET_NOT_UNIQUE");
    const stored=(await chrome.storage.local.get(KEY))[KEY]||{};
    if(stored[nodeId]&&stored[nodeId]!==conversationKey)throw Error("NODE_REBIND_REQUIRES_EXPLICIT_RESET");
    if(Object.entries(stored).some(([k,v])=>k!==nodeId&&v===conversationKey))
      throw Error("NODE_ALREADY_ASSIGNED");
    await chrome.storage.local.set({[KEY]:{...stored,[nodeId]:conversationKey}});
    return {ok:true,nodeId,conversationKey,readOnly:true};
  }
  if(m?.type==="BRIDGE_NODE_READ") {
    const stored=(await chrome.storage.local.get(KEY))[KEY]||{};
    return readExactNode(m,await tabs(),stored);
  }
  if(m?.type==="BRIDGE_NODE_READ_GROUP") {
    if(!Array.isArray(m.targets)||m.targets.length<2||m.targets.length>6)
      throw Error("NODE_GROUP_SIZE_INVALID");
    const ids=m.targets.map(t=>t?.nodeId);
    if(new Set(ids).size!==ids.length)throw Error("NODE_GROUP_DUPLICATE");
    const liveTabs=await tabs();
    const stored=(await chrome.storage.local.get(KEY))[KEY]||{};
    // Prevalidate *all* exact identities before reading any page.
    for(const target of m.targets){
      const {nodeId,conversationKey}=P.validateBinding(target.nodeId,target.conversationKey);
      if(stored[nodeId]!==conversationKey)throw Error("NODE_BINDING_NOT_REGISTERED");
      P.matchExact(liveTabs,conversationKey,target.tabId);
    }
    const replies=await Promise.all(
      m.targets.map(t=>readExactNode(t,liveTabs,stored))
    );
    return {ok:true,readOnly:true,transport:"BRIDGE_EXTENSION_READ_ONLY",
      resultCount:replies.length,replies};
  }
  throw Error("NODE_COMMAND_NOT_SUPPORTED");
}
chrome.runtime.onMessage.addListener((m,sender,sendResponse)=>{
  if(sender?.id!==chrome.runtime.id||
     !["BRIDGE_NODE_LIST","BRIDGE_NODE_BIND","BRIDGE_NODE_READ","BRIDGE_NODE_READ_GROUP"].includes(m?.type))
    return false;
  Promise.resolve().then(()=>handle(m)).then(sendResponse)
    .catch(e=>sendResponse(error(e)));
  return true;
});
