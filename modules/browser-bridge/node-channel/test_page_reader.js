"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const raw=fs.readFileSync("page_reader.js","utf8");
const key="22222222-2222-4222-8222-222222222222";
function scan({host="chatgpt.com",path="/c/"+key,stop=false,reply="Completed reply"}={}){
 const users=[{innerText:"Original request",parentElement:{closest:()=>null}}];
 const assistants=[{innerText:reply,textContent:reply,parentElement:{closest:()=>null}}];
 const context=vm.createContext({
   location:{hostname:host,protocol:"https:",pathname:path},
   document:{querySelectorAll:q=>{
     if(q==='[data-message-author-role="user"]')return users;
     if(q==='[data-message-author-role="assistant"]')return assistants;
     return [];
   },querySelector:q=>stop?{}:null},
   module:{exports:{}}
 });
 vm.runInContext(raw,context);
 return context.module.exports(key);
}
const result=scan();
assert.equal(result.ok,true);
assert.equal(result.conversationKey,key);
assert.equal(result.lastAssistant,"Completed reply");
assert.equal(result.assistantCount,1);
assert.equal(result.userCount,1);
assert.equal(result.generating,false);
assert.equal(scan({stop:true}).generating,true);
assert.equal(scan({reply:"x".repeat(10000)}).lastAssistant.length,2400);
assert.equal(scan({path:"/c/11111111-1111-4111-8111-111111111111"}).ok,false);
assert.equal(scan({host:"evil.test"}).ok,false);
const api=require("./protocol.js");
assert.throws(()=>api.sanitizeSnapshot(scan({path:"/c/11111111-1111-4111-8111-111111111111"}),key),/NODE_CONTENT_IDENTITY_UNVERIFIED/);
console.log("Independent Browser Bridge DOM read + exact tab identity: PASS");
