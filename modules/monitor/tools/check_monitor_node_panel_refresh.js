"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,".."),ctx={globalThis:null};
ctx.globalThis=ctx;vm.createContext(ctx);
const src=fs.readFileSync(path.join(root,"extension/monitor-node-panel-refresh.js"),"utf8");
vm.runInContext(src,ctx);
const html=fs.readFileSync(path.join(root,"extension/desktop.html"),"utf8");
const body=fs.readFileSync(path.join(root,"domains/node-identity.js"),"utf8");
const part=fs.readFileSync(path.join(root,"source-parts/04-worker-list.js"),"utf8");
assert.ok(html.indexOf('src="monitor-node-panel-refresh.js"')<html.indexOf('src="monitor.js"'));
assert.match(body,/MonitorNodePanelRefresh[.]create/);
assert.doesNotMatch(part,/let monitorBctWindowNodeRefreshBusy/);
assert.doesNotMatch(part,/let monitorBctWindowNodeRefreshPending/);
async function run(){
  let releaseFirst, completed=0;
  const first=new Promise(resolve=>releaseFirst=resolve);
  const calls=[],errors=[],busyStates=[],callbacks=[];
  const refresh=ctx.MonitorNodePanelRefresh.create({
    run:async()=>{calls.push("run");if(calls.length===1)await first;completed++;},
    onBusy:busy=>busyStates.push(busy),onError:e=>errors.push(e.message),
    enqueue:callback=>callbacks.push(callback)
  });
  const inflight=refresh.refresh();
  assert.equal(refresh.snapshot().busy,true);
  assert.equal(await refresh.refresh(),false);
  assert.equal(await refresh.refresh(),false);
  assert.equal(refresh.snapshot().pending,true);
  releaseFirst();
  assert.equal(await inflight,true);
  assert.equal(callbacks.length,1);
  callbacks.pop()();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(completed,2);
  assert.equal(refresh.snapshot().busy,false);
  assert.deepEqual(busyStates,[true,false,true,false]);
  refresh.destroy();
  assert.equal(await refresh.refresh(),false);
  assert.equal(completed,2);
  const failure=ctx.MonitorNodePanelRefresh.create({
    run:async()=>{throw Error("RCC down");},onBusy:()=>{},
    onError:e=>errors.push(e.message),enqueue:()=>{}
  });
  assert.equal(await failure.refresh(),false);
  assert.equal(errors[0],"RCC down");
  assert.equal(failure.snapshot().busy,false);
  console.log("PASS: NodePanel refresh single owner, in-flight coalescing, render ports and error release");
}
run().catch(e=>{console.error(e);process.exitCode=1});
