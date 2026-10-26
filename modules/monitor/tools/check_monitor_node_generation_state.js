"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),vm=require("node:vm"),path=require("node:path");
const root=path.join(__dirname,"..");
const moduleText=fs.readFileSync(path.join(root,"extension/monitor-node-generation-state.js"),"utf8");
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const generated=fs.readFileSync(path.join(root,"extension/monitor.js"),"utf8");
const nodes={globalThis:null,Map,Object,Array,String,Number,Date,Error,TypeError};
nodes.globalThis=nodes;
vm.createContext(nodes);vm.runInContext(moduleText,nodes,{timeout:5000});
const impl=nodes.MonitorNodeGenerationState;
assert(Object.isFrozen(impl));
assert.equal(typeof impl.create,"function");
assert.throws(()=>impl.create({readTab:5,readConversation:()=>null,ttlMs:3500}));
const tabs=new Map(),conversations=new Map(), service=impl.create({
 readTab:key=>tabs.get(key),readConversation:key=>conversations.get(key),
 readTabEntries:()=>tabs.values(),openEndpointForHwnd:(hwnd,state)=>state?.byHwnd?.[hwnd]||null,
 ttlMs:3500
});
assert(Object.isFrozen(service));
const e={conversation_key:"c-1",tab_id:12},n={conversation_key:"c-2",tab_id:0};
assert.equal(service.directGenerationState(e,5000),null);
tabs.set("c-1:12",{at:4000,generating:true,userAttention:{status:"question"}});
conversations.set("c-1",{userAttention:{status:"action"}});
assert.equal(service.directGenerationState(e,5000),true);
assert.equal(service.directGenerationState(e,8000),null,"stale generation must expire");
assert.equal(service.directUserAttention(e).status,"question","attention must survive TTL");
tabs.set("c-1:12",{at:4000,generating:false,userAttention:null});
assert.equal(service.directGenerationState(e,5000),false);
assert.equal(service.directUserAttention(e),null,"tab precedence preserves known empty report");
tabs.delete("c-1:12");
assert.equal(service.directUserAttention(e).status,"action","fall back to conversation attention");
assert.equal(service.directUserAttention({tab_id:12}),null);
assert.equal(service.directGenerationState(n,10),null);
conversations.set("c-1",{at:8000,generating:true,userAttention:{status:"action"}});
assert.equal(service.directConversationGenerationState("c-1",9000),true);
tabs.set("c-1:12",{conversationKey:"c-1",at:9000,generating:false,userAttention:null});
assert.equal(service.directConversationGenerationState("c-1",9200),false,"fresh exact tab overrides old conversation report");
assert.equal(service.directConversationGenerationState("c-1",15000),null,"old generation expires");
assert.equal(service.conversationIsGenerating("c-1",{endpoints:[]}),false);
assert.equal(service.conversationIsGenerating("c-1",{endpoints:[{conversation_key:"c-1",presence_state:"OPEN",generating:true}]}),true);
assert.equal(service.conversationIsGenerating("missing",{}),false);
assert.equal(service.hwndIsGenerating("123",{byHwnd:{"123":{generating:true}}}),true);
assert.equal(service.hwndIsGenerating("888",{byHwnd:{}}),false);
assert.equal(service.endpointIsGenerating({metadata:{generation_state:"GENERATING"}}),true);
assert.equal(service.endpointIsGenerating({metadata:{generation_state:"IDLE"}}),false);
assert.equal(service.endpointIsGenerating({metadata:{interaction_state:"WORKING"}}),true);
assert.equal(service.endpointIsGenerating({generating:false}),false);
tabs.set("c-1:12",{at:Date.now(),generating:false,userAttention:{status:"review"}});
assert.equal(service.endpointIsGenerating({...e,metadata:{generating:true}}),false,
 "exact active per-tab observation must override guessed metadata");
const script='<script src="monitor-node-generation-state.js"></script>';
assert.equal(html.split(script).length,2);
assert(html.indexOf(script)<html.indexOf('<script src="monitor.js"></script>'));
for(const name of ["monitorDirectEndpointUserAttention","monitorEndpointGenerationIsActive",
  "monitorDirectConversationGenerationState","monitorConversationIsGenerating","monitorHwndIsGenerating"]){
 assert(generated.includes("function "+name+"("),name+" compatibility bridge");
}
assert(generated.includes("MonitorNodeGenerationState.create("));
console.log("PASS injected generation/attention state, TTL, exact tab precedence, metadata fallback and script load order");
