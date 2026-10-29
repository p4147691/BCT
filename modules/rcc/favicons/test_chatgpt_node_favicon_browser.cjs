'use strict';
// Isolated Chrome profile; not the logged-in operating Chrome or RCC extension.
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const puppeteer=require('D:/TOOLS/BrowserAutomationSDK/node_modules/puppeteer');
const script=fs.readFileSync(path.join(__dirname,'chatgpt-node-favicon.user.js'),'utf8');
const A='6ae269f6-130c-83ee-9384-dffa2d2a946d';
const B='6ae295f6-8090-83e8-b444-02d46f637c20';
const profile=fs.mkdtempSync(path.join(__dirname,'.favicon-chrome-isolated-'));
let browser=null,server=null;
async function waitFor(page,fn){
  await page.waitForFunction(fn,{timeout:4000});
}
(async()=>{
 try{
  server=http.createServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
    res.end('<!doctype html><html><head><title>Existing ChatGPT title</title><link rel="icon" href="data:image/png;base64,abc" id="original"></head><body>Fixture</body></html>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await puppeteer.launch({
    executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless:true,userDataDir:profile,
    args:['--disable-extensions','--no-first-run','--no-default-browser-check','--disable-background-networking']
  });
  const page=await browser.newPage();
  await page.goto('http://127.0.0.1:'+server.address().port+'/c/'+A);
  await page.evaluate((A,B)=>{
    window.__mockRows=[{
      conversation_key:A,node_label:'N70',tab_id:71,window_id:22,presence:'OPEN',
      url:'https://chatgpt.com/c/'+A
    }];
    window.__mockRequests=0;
    window.GM_xmlhttpRequest=({onload})=>{
      window.__mockRequests++;
      onload({status:200,responseText:JSON.stringify({rcc:{instances:[{tabs:window.__mockRows}],payload:{state:'MATCH'}}})});
    };
  },A,B);
  await page.addScriptTag({content:script});
  await waitFor(page,()=>!!document.querySelector('link[data-bct-node-favicon-v1]'));
  const first=await page.evaluate(async()=>{
    const link=document.querySelector('link[data-bct-node-favicon-v1]');
    const bitmap=new Image(); bitmap.src=link.href;
    await bitmap.decode();
    return {format:link.href.startsWith('data:image/png;base64,'),width:bitmap.naturalWidth,
      height:bitmap.naturalHeight,title:document.title,
      original:!!document.querySelector('#original'),requestCount:window.__mockRequests};
  });
  assert.deepEqual({...first},{format:true,width:64,height:64,title:'Existing ChatGPT title',original:true,requestCount:1});
  await page.evaluate(B=>{
    window.__mockRows=[{conversation_key:B,node_label:'N71',tab_id:72,window_id:22,presence:'OPEN',url:'https://chatgpt.com/c/'+B}];
    history.pushState({},'', '/c/'+B);
  },B);
  await waitFor(page,()=>window.__mockRequests>=2&&!!document.querySelector('link[data-bct-node-favicon-v1]'));
  const after=await page.evaluate(async()=>{
    const img=new Image();img.src=document.querySelector('link[data-bct-node-favicon-v1]').href;
    await img.decode(); return {w:img.naturalWidth,title:document.title,original:!!document.querySelector('#original')};
  });
  assert.equal(after.w,64);assert.equal(after.title,'Existing ChatGPT title');assert.equal(after.original,true);
  await page.evaluate(()=>{window.__mockRows=[];window.dispatchEvent(new Event('focus'));});
  await waitFor(page,()=>!document.querySelector('link[data-bct-node-favicon-v1]'));
  assert.equal(await page.$eval('#original',el=>el.isConnected),true);
  console.log('CHROMIUM_ISOLATED_PASS: data PNG 64x64 decoded, SPA switch, unassigned restore, title unchanged, no real tabs/extensions used');
 }finally{
  if(browser)await browser.close();
  if(server)await new Promise(resolve=>server.close(resolve));
  fs.rmSync(profile,{recursive:true,force:true});
 }
})().catch(e=>{console.error('CHROMIUM_ISOLATED_FAIL',e.stack||String(e));process.exitCode=1});
