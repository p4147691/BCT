"use strict";
(function(root) {
  const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  const LABEL = /^N(?:[1-9]|[1-9][0-9]{1,2})$/;
  const chatKey = url => {
    try {
      const u = new URL(String(url||""));
      if (u.protocol !== "https:" || u.hostname !== "chatgpt.com") return null;
      const match = /^\/c\/([a-f0-9-]{36})\/?$/.exec(u.pathname);
      return match && UUID.test(match[1]) ? match[1] : null;
    } catch (_) { return null; }
  };
  function nodes(tabs) {
    const byKey = new Map();
    for(const tab of tabs||[]) {
      const key=chatKey(tab.url);
      if (!key || !Number.isSafeInteger(tab.id) || tab.id<=0) continue;
      const arr=byKey.get(key)||[];
      arr.push({tabId:tab.id,conversationKey:key,title:String(tab.title||"").slice(0,120)});
      byKey.set(key,arr);
    }
    return {distinct:[...byKey.values()].filter(v=>v.length===1).map(v=>v[0]),
            duplicates:[...byKey.entries()].filter(([,v])=>v.length>1).map(([key,v])=>({conversationKey:key,count:v.length}))};
  }
  function matchExact(tabs,conversationKey,tabId) {
    if(!UUID.test(conversationKey)||!Number.isSafeInteger(tabId)||tabId<=0)
      throw Error("NODE_EXACT_IDENTITY_REQUIRED");
    const all=nodes(tabs);
    if(all.duplicates.some(d=>d.conversationKey===conversationKey))
      throw Error("NODE_CONVERSATION_NOT_UNIQUE");
    const same=all.distinct.filter(n=>n.conversationKey===conversationKey&&n.tabId===tabId);
    if(same.length!==1)throw Error("NODE_EXACT_TAB_MISMATCH");
    return same[0];
  }
  function validateBinding(nodeId, conversationKey) {
    if(!LABEL.test(nodeId)||!UUID.test(conversationKey))throw Error("NODE_BINDING_INVALID");
    return {nodeId,conversationKey};
  }
  function sanitizeSnapshot(result, expected) {
    if(!result||result.conversationKey!==expected||result.ok!==true)
      throw Error("NODE_CONTENT_IDENTITY_UNVERIFIED");
    if(typeof result.generating!=="boolean"||!Number.isInteger(result.assistantCount)
      || result.assistantCount<0||!Number.isInteger(result.userCount)||result.userCount<0)
      throw Error("NODE_CONTENT_SHAPE_INVALID");
    if(typeof result.lastAssistant!=="string"||result.lastAssistant.length>2400)
      throw Error("NODE_CONTENT_EXCEEDS_BOUND");
    return Object.freeze({conversationKey:expected,generating:result.generating,
      userCount:result.userCount,assistantCount:result.assistantCount,
      lastAssistant:result.lastAssistant,readOnly:true});
  }
  const api=Object.freeze({chatKey,nodes,matchExact,validateBinding,sanitizeSnapshot});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.BctIndependentNodeProtocol=api;
})(typeof self!=="undefined"?self:this);
