"use strict";
const fs=require("fs"),path=require("path");
const TM="dhdgffkkebhmkfjojejmpbldmpobfkfo", P="!extdb.@source#";
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let effect=false,owned=null,session=null,browser=null;
function fail(s){throw Error(s)}
async function connect(a){
 if(a.extension_id!==TM)fail("UNSUPPORTED_EXTENSION");
 if(!["list","read","create","update","remove"].includes(a.operation))fail("UNSUPPORTED_ACTION");
 const port=fs.readFileSync(path.join(a.profile_root,"DevToolsActivePort"),"utf8").trim().split(/\r?\n/);
 if(!/^\d+$/.test(port[0])||!port[1].startsWith("/devtools/browser/"))fail("INVALID_CDP_PORT");
 const pp=require(a.puppeteer_module);
 browser=await pp.connect({browserWSEndpoint:"ws://127.0.0.1:"+port[0]+port[1],defaultViewport:null});
 session=await browser.target().createCDPSession();
 const t=browser.targets().find(x=>x.type()==="page"&&x.url().startsWith("chrome-extension://"+TM+"/options.html"));
 if(!t)fail("TAMPERMONKEY_OPTIONS_PAGE_REQUIRED");
 const page=await t.page();
 const ver=await page.evaluate(()=>({id:chrome.runtime.id,ver:chrome.runtime.getManifest().version}));
 if(ver.id!==TM||ver.ver!=="5.5.1")fail("VERSION_OR_ID_MISMATCH");
 return page;
}
async function status(p){
 return p.evaluate(async()=>{
  const d=await chrome.storage.local.get(null),keys=Object.keys(d).filter(k=>k.startsWith("!extdb.@source#"));
  const out=[];for(const k of keys){const raw=JSON.stringify(d[k]),bytes=new TextEncoder().encode(raw),digest=await crypto.subtle.digest("SHA-256",bytes);out.push({uuid:k.slice("!extdb.@source#".length),sha256:[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("")})}
  return out.sort((a,b)=>a.uuid.localeCompare(b.uuid));
 });
}
async function newpage(route){
 const target=await session.send("Target.createTarget",{url:"chrome-extension://"+TM+"/options.html#nav="+route,background:true});
 owned=target.targetId;
 const t=await browser.waitForTarget(x=>x._targetId===owned,{timeout:17000});
 const page=await t.page();
 if(!page)fail("CREATED_TARGET_UNAVAILABLE");
 await page.waitForFunction(id=>location.href.startsWith("chrome-extension://"+id+"/options.html"),{timeout:17000,polling:200},TM);
 return page;
}
async function ready(p,tag){
 await p.waitForFunction(s=>[...document.querySelectorAll(".CodeMirror")].some(e=>e.CodeMirror?.getValue()?.includes(s)),{timeout:17000,polling:220},tag);
}
async function codeFrom(p,uuid){
 await p.goto("chrome-extension://"+TM+"/options.html#nav="+uuid+"+editor",{waitUntil:"domcontentloaded",timeout:16000});
 await ready(p,"// ==UserScript==");await wait(250);
 const codes=await p.evaluate(()=>[...document.querySelectorAll(".CodeMirror")].filter(e=>e.CodeMirror&&e.getClientRects().length>0).map(e=>e.CodeMirror.getValue()));
 if(codes.length!==1)fail("ACTIVE_EDITOR_NOT_UNIQUE");
 return codes[0];
}
function preserve(before,after,except){
 const a=new Map(before.map(x=>[x.uuid,x.sha256])),b=new Map(after.map(x=>[x.uuid,x.sha256]));
 for(const [k,v] of a)if(k!==except&&b.get(k)!==v)fail("OTHER_SCRIPT_CHANGED");
 for(const [k] of b)if(k!==except&&!a.has(k))fail("UNEXPECTED_SCRIPT_ADDED");
}
function backup(a,uuid,old,sha){
 if(typeof a.backup_root!=="string"||!path.isAbsolute(a.backup_root))fail("BACKUP_ROOT_REQUIRED");
 fs.mkdirSync(a.backup_root,{recursive:true});
 const dest=path.join(a.backup_root,"tampermonkey-"+uuid+"-"+sha+".user.js");
 try{fs.writeFileSync(dest,old,{flag:"wx",encoding:"utf8"})}
 catch(e){if(e.code!=="EEXIST"||fs.readFileSync(dest,"utf8")!==old)throw e}
 return dest;
}
async function action(a){
 const p=await connect(a),before=await status(p);
 if(a.operation==="list")return {operation:"list",scripts:before};
 const uuid=a.script_uuid,stored=before.find(x=>x.uuid===uuid);
 if(a.operation!=="create"){
  if(typeof uuid!=="string"||!/^[0-9a-f-]{36}$/i.test(uuid)||!stored)fail("SCRIPT_UUID_NOT_FOUND");
  if(a.operation!=="read"&&(typeof a.expected_sha256!=="string"||a.expected_sha256!==stored.sha256))fail("EXPECTED_SHA_MISMATCH");
 }
 if(["create","update"].includes(a.operation)&&(typeof a.source!=="string"||a.source.length<75||a.source.length>200000||!a.source.startsWith("// ==UserScript==")))fail("SOURCE_INVALID");
 if(a.operation==="create"&&a.expected_count!==before.length)fail("EXPECTED_COUNT_MISMATCH");
 const page=await newpage(a.operation==="create"?"new-user-script+editor":uuid+"+editor");
 if(a.operation==="read")return {operation:"read",script_uuid:uuid,sha256:stored.sha256,source:await codeFrom(page,uuid)};
 if(a.operation==="create"){
  await ready(page,"New Userscript");
  effect=true;
  const res=await page.evaluate(src=>{const c=[...document.querySelectorAll(".CodeMirror")].filter(e=>e.CodeMirror?.getValue()?.includes("New Userscript"));const b=[...document.querySelectorAll('button[title="저장"]')].filter(e=>e.querySelector(".fa-save"));if(c.length!==1||b.length!==1)return {ok:false};c[0].CodeMirror.setValue(src);b[0].click();return {ok:true}},a.source);
  if(!res.ok)fail("CREATE_CONTROL_AMBIGUOUS");
  effect=true;await wait(1500);
  const after=await status(page),added=after.filter(x=>!before.some(y=>y.uuid===x.uuid));
  if(added.length!==1)fail("CREATE_RESULT_UNCERTAIN");
  preserve(before,after,added[0].uuid);
  return {operation:"create",script_uuid:added[0].uuid,sha256:added[0].sha256,verified:true};
 }
 const old=await codeFrom(page,uuid),backupFile=backup(a,uuid,old,stored.sha256);
 if(a.operation==="update"){
  if(old===a.source)fail("CODE_NOT_CHANGED");
  effect=true;
  const res=await page.evaluate(q=>{
   const c=[...document.querySelectorAll(".CodeMirror")].filter(e=>e.CodeMirror?.getValue()?.includes("// ==UserScript==")&&e.getClientRects().length>0);
   const key=btoa(q.uuid+"_save").replace(/=+$/,"");
   const b=[...document.querySelectorAll('button[title="저장"]')].filter(e=>e.querySelector(".fa-save")&&e.id.includes(key));
   if(c.length!==1||b.length!==1)return {ok:false,codeCount:c.length,buttonCount:b.length};
   c[0].CodeMirror.setValue(q.code);b[0].click();return {ok:true}
  },{uuid,code:a.source});
  if(!res.ok)fail("UPDATE_CONTROL_AMBIGUOUS");
  effect=true;await wait(1500);
  const after=await status(page);preserve(before,after,uuid);
  const changed=after.find(x=>x.uuid===uuid);if(!changed||changed.sha256===stored.sha256)fail("UPDATE_NOT_PERSISTED");
  if((await codeFrom(page,uuid))!==a.source)fail("UPDATE_READBACK_MISMATCH");
  return {operation:"update",script_uuid:uuid,sha256:changed.sha256,backup_path:backupFile,verified:true};
 }
 await page.goto("chrome-extension://"+TM+"/options.html#nav=dashboard",{waitUntil:"domcontentloaded",timeout:16000});
 await page.waitForFunction(()=>document.querySelectorAll("tr.scripttr").length>0,{timeout:15000,polling:250});
 effect=true;
 const removed=await page.evaluate(uid=>{const token=btoa("_"+uid).replace(/=+$/,"");const btn=[...document.querySelectorAll('tr.scripttr i[title="삭제"]')].filter(e=>e.id.includes(token));if(btn.length!==1)return {ok:false,count:btn.length};btn[0].click();return {ok:true}},uuid);
 if(!removed.ok)fail("DELETE_TARGET_AMBIGUOUS");
 effect=true;await wait(1250);await page.reload({waitUntil:"domcontentloaded",timeout:17000});await wait(850);
 const exists=await page.evaluate(uid=>[...document.querySelectorAll("tr.scripttr")].some(x=>x.innerHTML.includes(uid)),uuid);
 if(exists)fail("DELETE_STILL_INSTALLED");
 const after=await status(page);preserve(before,after,uuid);
 return {operation:"remove",script_uuid:uuid,verified:true,permanent:false,backup_path:backupFile};
}
(async()=>{
 try{const a=JSON.parse(fs.readFileSync(0,"utf8"));const result=await action(a);console.log(JSON.stringify({status:"PASS",...result}))}
 catch(e){console.log(JSON.stringify({status:"ERROR",code:String(e.message||e).slice(0,220),effect_started:effect}))}
 finally{if(session&&owned)try{await session.send("Target.closeTarget",{targetId:owned})}catch{}if(session)try{await session.detach()}catch{}if(browser)try{await browser.disconnect()}catch{}}
})();