"use strict";
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),assert=require("node:assert/strict");
const ext=path.join(__dirname,"../extension");
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,"../domains/pure-api-manifest.json"),"utf8"));
const source=fs.readFileSync(path.join(ext,"monitor-domain-apis.js"),"utf8");
const html=fs.readFileSync(path.join(ext,"desktop.html"),"utf8");
const monitor=fs.readFileSync(path.join(ext,"monitor.js"),"utf8");
assert(html.indexOf('<script src="monitor-domain-apis.js"></script>')>0);
assert(html.indexOf('<script src="monitor-domain-apis.js"></script>')<html.indexOf('<script src="monitor.js"></script>'));
const context={Object,Array,String,Number,Boolean,Math,Date,JSON,RegExp,Map,Set,Promise,parseInt,parseFloat,isFinite,isNaN};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(source,context,{timeout:8000});
const api=context.MonitorDomainAPIs;
assert(Object.isFrozen(api));
let count=0;
for(const [domain,names] of Object.entries(manifest.namespaces)){
  assert(Object.isFrozen(api[domain]),domain);
  for(const name of names){
    assert.equal(typeof api[domain][name],"function",name);
    assert(monitor.includes('function '+name+'('),name+" compatibility bridge missing");
    assert(monitor.includes('MonitorDomainAPIs['+JSON.stringify(domain)+']['+JSON.stringify(name)+']'),name+" must route to isolated domain");
    count++;
  }
}
assert.equal(count,manifest.count);
const c=api["conversations"],n=api["node-identity"],o=api.organization,s=api["shared-ui"];
assert.deepEqual(Array.from(c.monitorBctRoleTagsFromText("Manager, Worker,Manager, Worker")),[ "Manager","Worker"]);
assert.equal(c.cleanMonitorWorkerName({role:"WORKER"}),"W");
assert.equal(c.monitorGhostTime("invalid"),0);
assert.equal(c.monitorConversationStateSignature({}),"e:||n:||w:");
assert.equal(n.monitorEndpointInstanceId({transport_instance_id:"i",session_id:"s",tab_id:0}),"i:s:0");
assert.equal(n.monitorBctNodeRoleSummary({roleTags:["manager"]})!==undefined,true);
assert.equal(o.monitorStructureBundleName("local"),"L-LLM");
assert.equal(o.monitorStructureNodeShortNumber({label:"D3-45"}),"45");
assert.equal(s.compareMonitorSharedSelectionRevision("10","2"),1);
assert.equal(s.monitorTabBindingKey({transport_instance_id:"i",tab_id:35}),"tab:i:35");
assert.equal(s.monitorTitlesEquivalent("Note - ChatGPT","Note"),true);
assert.equal(s.monitorRoleAdminShort("ORCHESTRATOR"),"O");
// Refuse undeclared document/window dependencies. No DOM is supplied to this sandbox.
console.log("PASS isolated runtime API source, immutable four namespaces, "+count+" routed stateless functions, independent VM smoke tests");
