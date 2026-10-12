// DesktopWindow Monitor ACT transport.
// Public boundary: globalThis.MonitorActTransport.actFetch only.
// Endpoint probing, port scan, TTL cache, and retry stay private here.
(() => {
const ACT_PORT_START = 18765;

const ACT_PORT_SCAN_COUNT = 50;

const ACT_PORT_PROBE_TIMEOUT_MS = 350;

const ACT_BASE_TTL_MS = 5000;

const nativeFetch = globalThis.fetch.bind(globalThis);

let actBaseUrlCache = "";

let actBaseUrlVerifiedAt = 0;

async function probeActBaseUrl(baseUrl) {

  const controller = new AbortController();

  const timer = setTimeout(() => controller.abort(), ACT_PORT_PROBE_TIMEOUT_MS);

  try {

    const r = await nativeFetch(`${baseUrl}/health`, { cache: "no-store", signal: controller.signal });

    const h = r.ok ? await r.json().catch(() => null) : null;

    return h?.ok === true && h?.service === "Agent Orchestrator";

  } catch (_) { return false; } finally { clearTimeout(timer); }

}

async function resolveActBaseUrl(force = false) {

  const now = Date.now();

  if (!force && actBaseUrlCache && now - actBaseUrlVerifiedAt < ACT_BASE_TTL_MS) return actBaseUrlCache;

  if (actBaseUrlCache && await probeActBaseUrl(actBaseUrlCache)) { actBaseUrlVerifiedAt = now; return actBaseUrlCache; }

  for (let offset = 0; offset < ACT_PORT_SCAN_COUNT; offset += 5) {

    const ports = Array.from({length: Math.min(5, ACT_PORT_SCAN_COUNT-offset)}, (_,i)=>ACT_PORT_START+offset+i);

    const checks = await Promise.all(ports.map(async p => ({p, ok: await probeActBaseUrl(`http://127.0.0.1:${p}`)})));

    const hit = checks.find(x => x.ok);

    if (hit) { actBaseUrlCache = `http://127.0.0.1:${hit.p}`; actBaseUrlVerifiedAt = Date.now(); return actBaseUrlCache; }

  }

  throw new Error("ACT_ENDPOINT_UNRESOLVED");

}

async function actFetch(input, init) {

  if (typeof input !== "string" || !input.startsWith("act:")) return nativeFetch(input, init);

  const path = input.slice(4);

  let base = await resolveActBaseUrl(false);

  try { return await nativeFetch(base + path, init); }

  catch (_) { base = await resolveActBaseUrl(true); return nativeFetch(base + path, init); }

}

  globalThis.MonitorActTransport = { actFetch };
})();
