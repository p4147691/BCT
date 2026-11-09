"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const ctx = {}; ctx.globalThis = ctx;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../extension/monitor-bct-shell.js"),"utf8"),ctx);
const sent = [];
const api = ctx.MonitorBctShell.create({fetcher: async (url,init) => {
  sent.push({url,body:JSON.parse(init.body)});
  return {ok:true,json:async()=>({status:"OK",conversation:{revision:2}})};
}});
const dot = "opaque-ref~opaque-context";
const tabs = [
  {tab_id:1,window_id:10,url:"https://chatgpt.com/dots/"+dot},
  {tab_id:2,window_id:20,url:"https://chatgpt.com/dots/"+dot+"?view=second"},
  {tab_id:3,window_id:10,url:"https://chatgpt.com/"},
  {tab_id:4,window_id:10,url:"https://chatgpt.com/c/chat-one",node_label:"N31"},
  {tab_id:5,window_id:10,url:"https://evil.example/dots/"+dot},
];
const state = {dot_node_info:{[dot]:{dot_key:dot,revision:1,node_memo:"shared",role_tags:["Orchestrator"]}},
 rcc:{instances:[{instance_id:"instance",session_id:"session",state:"OPEN",tabs}]}};
const nodes = api.windowNodes(state);
assert.equal(nodes.length,4);
const dots = nodes.filter(n=>n.dotKey);
assert.equal(dots.length,2);
assert.equal(dots[0].dotKey,dots[1].dotKey);
assert.notEqual(dots[0].tabId,dots[1].tabId);
assert.ok(dots.every(n=>n.nodeLabel==="O" && n.conversationKey==="" && n.nodeMemo==="shared"));
assert.equal(nodes.find(n=>n.tabId===3).dotKey,"");
assert.equal(nodes.find(n=>n.tabId===4).conversationKey,"chat-one");
(async()=>{
 await api.updateConversationScope(dots[0],{nodeMemo:"updated",roleTags:["Orchestrator"]});
 assert.equal(sent.length,1);
 assert.ok(sent[0].url.endsWith("/monitor/dot-node-info"));
 assert.equal(sent[0].body.dot_key,dot);
 assert.equal(sent[0].body.expected_revision,1);
 assert.ok(!("conversation_key" in sent[0].body));
 console.log("PASS dot identity, separate tabs and metadata routing");
})().catch(e=>{console.error(e);process.exitCode=1});
