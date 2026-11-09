"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const ctx={};ctx.globalThis=ctx;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../extension/monitor-bct-shell.js"),"utf8"),ctx);
const ref="00000000-0000-4000-8000-000000000001",route="https://chatgpt.com/local/client-new-thread:"+ref;
const tabs=[{tab_id:1,window_id:10,url:route},{tab_id:2,window_id:20,url:route},
 {tab_id:3,window_id:10,url:"https://chatgpt.com/c/chat-one",node_label:"N31",surface:{kind:"CODEX"}},
 {tab_id:4,window_id:10,url:"https://chatgpt.com/"},{tab_id:5,window_id:10,url:"https://chatgpt.com/local/unverified:"+ref}];
const state={service:{status:"OK",ready:true,service:"bct-core"},rcc:{instances:[{instance_id:"i",session_id:"s",state:"OPEN",tabs}]}};
const directory={[ref]:{identity_kind:"CODEX_LOCAL_DRAFT",reference:ref,node_label:"C1",conversation_key:"",routable:false}};
let registrations=0;
const api=ctx.MonitorBctShell.create({fetcher:async(url,init)=>{
 if(url.endsWith("/monitor/state"))return {ok:true,json:async()=>state};
 assert.ok(url.endsWith("/monitor/codex-surface/register"));registrations++;
 assert.equal(JSON.parse(init.body).urls.length,1);
 return {ok:true,json:async()=>({status:"OK",directory})};
}});
(async()=>{
 const fresh=await api.monitorState();const nodes=api.windowNodes(fresh);
 const codex=nodes.filter(n=>n.codexLocalReference);
 assert.equal(codex.length,2);assert.ok(codex.every(n=>n.nodeLabel==="C1"&&!n.conversationKey));
 assert.notEqual(codex[0].tabId,codex[1].tabId);
 assert.equal(nodes.find(n=>n.tabId===3).nodeLabel,"N31");
 assert.equal(nodes.find(n=>n.tabId===4).identityKind,"CONVERSATION");
 assert.equal(nodes.find(n=>n.tabId===5).codexLocalReference,"");
 Object.assign(state,{codex_surface_directory:directory});await api.monitorState();assert.equal(registrations,1);
 console.log("PASS Codex exact route, explicit C registration, duplicate tabs, unknown route and N preservation");
})().catch(e=>{console.error(e);process.exitCode=1});
