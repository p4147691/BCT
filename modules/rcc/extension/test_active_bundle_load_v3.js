const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { randomUUID, webcrypto } = require('node:crypto');

const root = __dirname;
const read = (relative) => fs.readFileSync(`${root}/${relative}`, 'utf8');
const loader = read('background_loader.js');
const backgroundFiles = [...loader.matchAll(/importScripts\('([^']+)'\)/g)].map((match) => match[1]);
const contentFiles = JSON.parse(read('manifest.json')).content_scripts[0].js;

function event() {
  return { addListener() {} };
}

(async () => {
  const local = {};
  const session = {};
  const nativePosts = [];
  const port = { postMessage: (value) => nativePosts.push(value), onMessage: event(), onDisconnect: event() };
  const chrome = {
    storage: {
      local: {
        get: async (keys) => typeof keys === 'string' ? { [keys]: local[keys] } : { ...local },
        set: async (patch) => Object.assign(local, patch),
      },
      session: {
        get: async (key) => ({ [key]: session[key] }),
        set: async (patch) => Object.assign(session, patch),
      },
    },
    tabs: { query: async () => [], get: async () => { throw new Error('missing'); },
      sendMessage: async () => ({ ok: true }), onCreated: event(), onUpdated: event(), onRemoved: event() },
    windows: { get: async () => ({}) },
    scripting: { executeScript: async () => [{ result: null }] },
    runtime: { id: 'test-extension', connectNative: () => port, onMessage: event(),
      onStartup: event(), onInstalled: event(), reload() {} },
  };
  const backgroundContext = vm.createContext({
    console, chrome, crypto: { randomUUID, subtle: webcrypto.subtle }, TextEncoder, Uint8Array,
    URL, setTimeout, clearTimeout,
  });
  for (const relative of backgroundFiles) {
    vm.runInContext(read(relative), backgroundContext, { filename: relative });
  }
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert(nativePosts.some((item) => item.type === 'host:ready'));
  assert(nativePosts.some((item) => item.type === 'host:endpoints' && item.mode === 'snapshot'));

  const contentListeners = [];
  const empty = { querySelector: () => null, querySelectorAll: () => [], getClientRects: () => [] };
  const document = { ...empty, body: empty, documentElement: empty, addEventListener() {} };
  class MutationObserver { constructor(callback) { this.callback = callback; } observe() {} }
  const contentContext = vm.createContext({
    console,
    chrome: { runtime: { onMessage: { addListener: (fn) => contentListeners.push(fn) },
      sendMessage: async () => ({ ok: true }) } },
    document, window: { addEventListener() {} },
    location: { href: 'https://chatgpt.com/c/test', pathname: '/c/test' },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    MutationObserver, Element: class {}, HTMLTextAreaElement: class {}, InputEvent: class {},
    Event: class {}, KeyboardEvent: class {},
    getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }),
    navigator: {}, performance: { memory: null }, setTimeout: () => 0, clearTimeout() {},
    setInterval: () => 0, clearInterval() {},
  });
  for (const relative of contentFiles) {
    vm.runInContext(read(relative), contentContext, { filename: relative });
  }
  assert.equal(contentListeners.length, 1, 'content router must register exactly one receiver');

  console.log('rcc active bundle load v3: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
