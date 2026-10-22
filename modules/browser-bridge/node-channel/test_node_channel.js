"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const P=require("./protocol.js");
const ids=[
  ["N13","11111111-1111-4111-8111-111111111111",701],
  ["N14","22222222-2222-4222-8222-222222222222",702],
  ["N23","33333333-3333-4333-8333-333333333333",703]
];
const tabs=ids.map(([node,key,id])=>({id,url:"https://chatgpt.com/c/"+key,title:node+" mock tab"}));
assert.equal(P.nodes(tabs).distinct.length,3);
assert.equal(P.chatKey("https://chatgpt.com/c/"+ids[0][1]+"?utm_source=x"),ids[0][1]);
for(const bad of ["https://evil.example/c/"+ids[0][1],
  "http://chatgpt.com/c/"+ids[0][1],"https://chatgpt.com.evil.test/c/"+ids[0][1],
  "https://chatgpt.com/g/"+ids[0][1]]) assert.equal(P.chatKey(bad),null);
assert.equal(P.matchExact(tabs,ids[1][1],702).tabId,702);
assert.throws(()=>P.matchExact(tabs,ids[1][1],701),/NODE_EXACT_TAB_MISMATCH/);
assert.throws(()=>P.matchExact([...tabs,tabs[1]],ids[1][1],702),/NODE_CONVERSATION_NOT_UNIQUE/);
assert.throws(()=>P.validateBinding("OTHER",ids[1][1]),/NODE_BINDING_INVALID/);
assert.throws(()=>P.sanitizeSnapshot({ok:true,conversationKey:ids[1][1],
 generating:false,assistantCount:1,userCount:1,lastAssistant:"X".repeat(2401)},ids[1][1]),/NODE_CONTENT_EXCEEDS_BOUND/);
const fakeData={};
const calls=[];
let listener=null;
const chrome={
 runtime:{id:"independent-bridge-lab",onMessage:{addListener(fn){listener=fn}}},
 tabs:{query:async()=>tabs},
 storage:{local:{
   get:async key=>({[key]:fakeData[key]}),
   set:async dict=>{Object.assign(fakeData,dict)},
 }},
 scripting:{executeScript:async ({target,func,args})=>{
    calls.push({target,args,func:func.name});
    return [{result:{ok:true,conversationKey:args[0],generating:false,
      assistantCount:1,userCount:1,lastAssistant:"Completed local test"}}];
 }}
};
const context=vm.createContext({chrome,self:{},console,URL,
 importScripts:(...files)=>{
  for(const file of files)vm.runInContext(fs.readFileSync(file,"utf8"),context);
 }});
vm.runInContext(fs.readFileSync("worker.js","utf8"),context);
async function send(message,senderId=chrome.runtime.id){
 return new Promise(resolve=>{
   const handled=listener(message,{id:senderId},resolve);
   if(!handled)resolve({ignored:true});
 });
}
(async()=>{
 let listed=await send({type:"BRIDGE_NODE_LIST"});
 assert.equal(listed.nodes.length,3);
 assert.equal(listed.transport,"BRIDGE_EXTENSION_READ_ONLY");
 for(const [name,key,id] of ids){
   const bound=await send({type:"BRIDGE_NODE_BIND",nodeId:name,conversationKey:key});
   assert.equal(bound.ok,true);
   assert.equal((await send({type:"BRIDGE_NODE_BIND",nodeId:name,conversationKey:key})).ok,true);
   const read=await send({type:"BRIDGE_NODE_READ",nodeId:name,conversationKey:key,tabId:id});
   assert.equal(read.ok,true);
   assert.equal(read.readOnly,true);
   assert.equal(read.lastAssistant,"Completed local test");
 }
 listed=await send({type:"BRIDGE_NODE_LIST"});
 assert.equal(JSON.stringify(listed.nodes.map(n=>n.nodeId)),JSON.stringify(["N13","N14","N23"]));
 assert.equal(calls.length,3);
 const groupTargets=ids.map(([nodeId,conversationKey,tabId])=>({
   nodeId,conversationKey,tabId
 }));
 const grouped=await send({type:"BRIDGE_NODE_READ_GROUP",targets:groupTargets});
 assert.equal(grouped.ok,true);
 assert.equal(grouped.readOnly,true);
 assert.equal(grouped.resultCount,3);
 assert.equal(grouped.replies.every(r=>r.ok&&r.readOnly),true);
 assert.equal(calls.length,6);
 assert.equal((await send({type:"BRIDGE_NODE_READ_GROUP",
   targets:[groupTargets[0],groupTargets[0]]})).ok,false);
 assert.equal((await send({type:"BRIDGE_NODE_READ_GROUP",
   targets:[groupTargets[0],{...groupTargets[1],tabId:701}]})).ok,false);
 assert.equal(calls.length,6,"invalid group must never invoke any page");

 assert.equal((await send({type:"BRIDGE_NODE_READ",nodeId:"N14",conversationKey:ids[1][1],tabId:701})).ok,false);
 assert.equal((await send({type:"BRIDGE_NODE_BIND",nodeId:"N14",conversationKey:ids[0][1]})).ok,false);
 assert.equal((await send({type:"BRIDGE_NODE_SEND",text:"NEVER SEND"})).ignored,true);
 assert.equal((await send({type:"BRIDGE_NODE_READ",nodeId:"N14",conversationKey:ids[1][1],tabId:702},"wrong-extension")).ignored,true);
 tabs.push({...tabs[1],id:704});
 assert.equal((await send({type:"BRIDGE_NODE_READ",nodeId:"N14",conversationKey:ids[1][1],tabId:702})).ok,false);
 assert.equal(calls.length,6,"No injection after ambiguous tab identity");
 assert.equal(Object.values(fakeData).length,1,"Only bound UUIDs persisted");
 console.log("Independent Browser Bridge node N13/N14/N23 read transport: PASS");
})().catch(e=>{console.error(e);process.exitCode=1});
