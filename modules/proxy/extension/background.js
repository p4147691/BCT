importScripts("local-token.js");

const DEFAULT_ROUTES = ["f95zone.to"];
const PROTECTED = [
  "chatgpt.com","openai.com","auth.openai.com","accounts.google.com","google.com",
  "proton.me","protonvpn.com","account.protonvpn.com","localhost","127.0.0.1"
];
const PROXY_RESULT = "SOCKS5 127.0.0.1:25344; DIRECT";
const HELPER = "http://127.0.0.1:25346";
const JOB_TTL_MS = 15 * 60 * 1000;
const RELOAD_GUARD_MS = 15000;

function normalizeHost(host) {
  return String(host || "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
}
function hostMatches(host, domain) {
  host = normalizeHost(host); domain = normalizeHost(domain);
  return host === domain || host.endsWith("." + domain);
}
function isProtected(host) {
  return PROTECTED.some((domain) => hostMatches(host, domain));
}
async function getRoutes() {
  const data = await chrome.storage.local.get("routedDomains");
  const routes = Array.isArray(data.routedDomains) ? data.routedDomains : DEFAULT_ROUTES;
  return [...new Set(routes.map(normalizeHost).filter(Boolean))];
}
function buildPac(routes) {
  const encoded = JSON.stringify(routes);
  return "function FindProxyForURL(url, host) {" +
    " host=String(host||'').toLowerCase(); var routes=" + encoded + ";" +
    " if (isPlainHostName(host)||host==='localhost'||host==='127.0.0.1') return 'DIRECT';" +
    " for(var i=0;i<routes.length;i++){var d=routes[i];if(host===d||dnsDomainIs(host,'.'+d)) return '" + PROXY_RESULT + "';}" +
    " return 'DIRECT';}";
}
async function helper(path, options={}) {
  const headers = Object.assign({}, options.headers || {}, {"X-CAP-Token": LOCAL_HELPER_TOKEN});
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const r = await fetch(HELPER + path, Object.assign({}, options, {headers}));
  let body = {};
  try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error(body.detail || body.error || ("HELPER_HTTP_" + r.status));
  return body;
}
async function helperStatus() {
  try { return await helper("/status"); }
  catch (e) { return {ok:false,state:"offline",detail:String(e)}; }
}
async function updateBadge() {
  try {
    const results = await Promise.all([chrome.proxy.settings.get({incognito:false}), helperStatus()]);
    const proxy = results[0], h = results[1];
    const controlled = proxy.levelOfControl === "controlled_by_this_extension";
    const good = controlled && h.ok && h.proxy_alive;
    await chrome.action.setBadgeText({text:good ? "A" : "!"});
    await chrome.action.setTitle({title: good ? "Chrome Auto Proxy: active" : "Chrome Auto Proxy: attention needed"});
  } catch (_) {}
}
async function applyProxy() {
  const routes = await getRoutes();
  await chrome.proxy.settings.set({value:{mode:"pac_script",pacScript:{data:buildPac(routes)}},scope:"regular"});
  await updateBadge();
}
async function getJob() {
  const data = await chrome.storage.local.get("protonJob");
  return data.protonJob || null;
}
async function setJob(patch) {
  const old = await getJob() || {};
  const next = Object.assign({}, old, patch, {updatedAt:Date.now()});
  await chrome.storage.local.set({protonJob:next});
  return next;
}
async function startProtonJob() {
  const startedAt = Date.now();
  const tab = await chrome.tabs.create({url:"https://account.protonvpn.com/",active:true});
  return await setJob({active:true,state:"opening",detail:"Proton 계정 페이지 여는 중",startedAt:startedAt,tabId:tab.id});
}
async function learnRoute(host) {
  host = normalizeHost(host);
  if (!host || isProtected(host)) return false;
  const routes = await getRoutes();
  if (routes.some((domain) => hostMatches(host, domain) || hostMatches(domain, host))) return false;
  routes.push(host);
  await chrome.storage.local.set({routedDomains:routes});
  await applyProxy();
  return true;
}
async function canReload(host) {
  const now = Date.now();
  const data = await chrome.storage.session.get("reloadGuards");
  const guards = data.reloadGuards || {};
  const last = Number(guards[host] || 0);
  if (now - last < RELOAD_GUARD_MS) return false;
  guards[host] = now;
  await chrome.storage.session.set({reloadGuards:guards});
  return true;
}

chrome.runtime.onInstalled.addListener(() => { applyProxy().catch(()=>{}); updateBadge().catch(()=>{}); });
chrome.runtime.onStartup.addListener(() => { applyProxy().catch(()=>{}); updateBadge().catch(()=>{}); });
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.routedDomains) applyProxy().catch(()=>{});
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg && msg.type === "status") {
      const results = await Promise.all([
        helperStatus(), getRoutes(), getJob(), chrome.proxy.settings.get({incognito:false})
      ]);
      return {ok:true,helper:results[0],routes:results[1],job:results[2],proxyControl:results[3].levelOfControl};
    }
    if (msg && msg.type === "startProtonDownload") return await startProtonJob();
    if (msg && msg.type === "getProtonJob") {
      const job = await getJob();
      return {active:!!(job && job.active) && Date.now()-Number(job.startedAt||0)<JOB_TTL_MS && (!job.tabId || job.tabId===sender.tab?.id),job:job};
    }
    if (msg && msg.type === "protonProgress") {
      const job = await getJob();
      if (job && job.active && (!job.tabId || job.tabId===sender.tab?.id)) {
        return await setJob({state:String(msg.state||"working"),detail:String(msg.detail||"")});
      }
      return job;
    }
    return {ok:false};
  })().then(sendResponse).catch((e)=>sendResponse({ok:false,error:String(e)}));
  return true;
});

chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state || delta.state.current !== "complete") return;
  (async () => {
    const job = await getJob();
    if (!job || !job.active || Date.now()-Number(job.startedAt||0) >= JOB_TTL_MS) return;
    const items = await chrome.downloads.search({id:delta.id});
    const item = items[0];
    if (!item || !String(item.filename||"").toLowerCase().endsWith(".conf")) return;
    await setJob({state:"importing",detail:"다운로드한 Proton 설정을 적용하는 중"});
    try {
      const result = await helper("/import",{method:"POST",body:JSON.stringify({path:item.filename})});
      await setJob({active:false,state:"ready",detail:"새 Proton 설정 적용 완료",result:result});
      await updateBadge();
      if (job.tabId) chrome.tabs.remove(job.tabId).catch(()=>{});
    } catch (e) {
      await setJob({active:false,state:"error",detail:String(e)});
    }
  })().catch(()=>{});
});

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.type !== "main_frame" || details.statusCode !== 451 || details.method !== "GET") return;
    (async () => {
      const host = normalizeHost(new URL(details.url).hostname);
      if (!host || isProtected(host)) return;
      await learnRoute(host);
      if (details.tabId >= 0 && await canReload(host)) await chrome.tabs.reload(details.tabId,{bypassCache:true});
    })().catch(()=>{});
  },
  {urls:["<all_urls>"],types:["main_frame"]},
  ["responseHeaders"]
);
chrome.proxy.onProxyError.addListener(()=>{ updateBadge().catch(()=>{}); });

applyProxy().catch(()=>{});
updateBadge().catch(()=>{});
