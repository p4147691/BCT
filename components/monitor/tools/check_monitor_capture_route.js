const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'extension/monitor.js'), 'utf8');
const start = source.indexOf('const monitorCaptureScheduler');
const end = source.indexOf('const monitorThumbnailService =', start);
assert(start >= 0 && end > start);
const adapters=[];
const calls = [], revoked = [];
let response = {ok:true, captureEngine:'wgc-oneshot', dataUri:'data:image/jpeg;base64,TEST'};
const context = {
  MonitorThumbnailService:{create(options){adapters.push(options);return {requestSnapshot(){},invalidate(){},dispose(){},disposeAll(){},stats(){return {};}}; }},
  monitorRenderDiagnostics:{captureRuns:0,captureFailure:0,captureSuccess:0},
  monitorNative(){throw new Error('Legacy Control transport reached');},
  async monitorCoreNative(message){calls.push(message);return response;},
  monitorCaptureDataUriToObjectUrl(value){assert.equal(value,response.dataUri);return 'blob:test';},
  monitorRevokeThumbWindowCaptureSource(value){revoked.push(value);}
};
vm.runInNewContext(`${source.slice(start,end)}; globalThis.__monitorCaptureScheduler = monitorCaptureScheduler;`,context);
(async()=>{
  assert.equal(adapters.length,3);
  const result=await adapters[0].capture({hwnd:'123',reason:'test',maxWidth:480,maxHeight:270});
  assert.equal(calls.length,1);
  assert.equal(calls[0].type,'captureWindow');
  assert.equal(calls[0].quality,52);
  assert.equal(result.value,'blob:test');
  result.dispose();
  assert.deepEqual(revoked,['blob:test']);
  response={ok:true,captureEngine:'legacy',dataUri:'data:image/jpeg;base64,OLD'};
  assert.equal(await adapters[1].capture({hwnd:'123',maxWidth:960,maxHeight:540}),null);
  assert.equal(calls.at(-1).quality,68);

  let nativeActive=0, nativeMax=0;
  response={ok:true,captureEngine:'wgc-oneshot',dataUri:'data:image/jpeg;base64,MIXED'};
  context.monitorCoreNative=async message=>{
    calls.push(message); nativeActive+=1; nativeMax=Math.max(nativeMax,nativeActive);
    await new Promise(resolve=>setTimeout(resolve,8)); nativeActive-=1;
    return response;
  };
  await Promise.all(adapters.map((adapter,index)=>adapter.capture({hwnd:String(900+index),maxWidth:960,maxHeight:540})));
  assert.ok(nativeMax<=2,`global native concurrency exceeded 2: ${nativeMax}`);
  assert.ok(context.__monitorCaptureScheduler.stats().maxObservedActive<=2);
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'native/com.pas40.desktop_window_monitor_control.json'),'utf8'));
  const binary=fs.readFileSync(manifest.path);
  assert(binary.includes(Buffer.from('wgc-oneshot','utf16le')));
  assert(fs.existsSync(path.join(path.dirname(manifest.path),'DesktopWindowMonitorWgcSnapshot.exe')));
  console.log('PASS: actual adapter uses Monitor Native, rejects legacy response, owns Blob disposal; active Monitor target contains WGC and helper exists');
})().catch(error=>{console.error(error);process.exitCode=1;});
