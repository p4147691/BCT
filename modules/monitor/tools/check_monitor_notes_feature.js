"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const extension = path.join(root, "extension");
const featurePath = path.join(extension, "features", "notes", "monitor-notes-feature.js");
const featureCssPath = path.join(extension, "features", "notes", "monitor-notes-feature.css");
const source = fs.readFileSync(featurePath, "utf8");
const featureCss = fs.readFileSync(featureCssPath, "utf8");
const monitor = fs.readFileSync(path.join(extension, "monitor.js"), "utf8");
const monitorCss = fs.readFileSync(path.join(extension, "monitor.css"), "utf8");
const html = fs.readFileSync(path.join(extension, "desktop.html"), "utf8");

const scriptTag = '<script src="features/notes/monitor-notes-feature.js"></script>';
const cssTag = '<link rel="stylesheet" href="features/notes/monitor-notes-feature.css">';
assert.ok(html.includes(scriptTag));
assert.ok(html.indexOf(scriptTag) < html.indexOf('<script src="monitor.js"></script>'));
assert.ok(html.includes(cssTag));
assert.doesNotMatch(source, /\bmonitorNative\b|\bactFetch\b|\bchrome\.|\blocalStorage\b|document\.getElementById/,
  "Notes must use injected ports and root-scoped DOM only");
assert.doesNotMatch(monitor, /\bmonitorSideNoteText\b|\bmonitorNotes\b|function monitorCreateNote|function monitorOpenNote|function monitorRenderNoteList/,
  "compatibility bundle must not retain Notes implementation or mutable state");
assert.match(monitor, /MonitorNotesFeature\?\.create\(/);
assert.doesNotMatch(monitorCss, /\.monitor-side-note|\.monitor-note-|#monitorSideNoteText|#monitorNote/,
  "shared Monitor CSS must not retain Notes selectors");
assert.match(featureCss, /\.monitor-side-note/);
assert.match(featureCss, /#monitorSideNoteText/);

class FakeClassList {
  constructor(value = "") { this.values = new Set(String(value).split(/\s+/).filter(Boolean)); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name); else this.values.delete(name);
    return next;
  }
  contains(name) { return this.values.has(name); }
}
class FakeStyle { setProperty(name, value) { this[name] = value; } }
class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase(); this.id = id; this.hidden = false; this.disabled = false;
    this.value = ""; this.textContent = ""; this.style = new FakeStyle(); this.classList = new FakeClassList();
    this.listeners = new Map(); this.childrenById = new Map(); this.children = []; this.dataset = {};
    this.scrollHeight = 100; this.clientHeight = 100; this.scrollTop = 0;
  }
  set className(value) { this._className = value; this.classList = new FakeClassList(value); }
  get className() { return this._className || ""; }
  set innerHTML(value) {
    this._innerHTML = value;
    if (!value) { this.children = []; return; }
    const pattern = /<(button|textarea|div|span)[^>]*\bid="([^"]+)"[^>]*>/g;
    let match;
    while ((match = pattern.exec(value))) {
      const child = new FakeElement(match[1], match[2]);
      child.hidden = /\shidden(?:\s|>)/.test(match[0]);
      this.childrenById.set(child.id, child);
    }
  }
  get innerHTML() { return this._innerHTML || ""; }
  querySelector(selector) { return selector.startsWith("#") ? this.childrenById.get(selector.slice(1)) || null : null; }
  querySelectorAll(selector) {
    if (!selector.startsWith(".")) return [];
    const className = selector.slice(1);
    return this.children.filter((child) => child.classList.contains(className));
  }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(listener); }
  dispatch(type, event = {}) {
    const supplied = { preventDefault() {}, button: 0, pointerId: 1, ctrlKey: false, altKey: false, metaKey: false, isTrusted: true, ...event, type, target: event.target || this };
    for (const listener of this.listeners.get(type) || []) listener(supplied);
  }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  closest(selector) { return selector.startsWith(".") && this.classList.contains(selector.slice(1)) ? this : null; }
  cloneNode() { const copy = new FakeElement(this.tagName); copy.className = this.className; return copy; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 300, bottom: 400, width: 300, height: 400 }; }
  scrollIntoView() {}
  focus() {}
  remove() { this.removed = true; }
}
class FakeDocument {
  constructor() { this.body = new FakeElement("body"); this.activeElement = null; this.listeners = new Map(); }
  createElement(tagName) { return new FakeElement(tagName); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  removeEventListener(type, listener) { if (this.listeners.get(type) === listener) this.listeners.delete(type); }
}

const sandbox = { globalThis: null, Object, String, Number, Math, Array, Boolean, Error, TypeError, Set, Map, Date, JSON };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: featurePath });
assert.equal(sandbox.MonitorNotesFeature.titleFromText("\n  제목\n내용"), "제목");

let sharedText = 'DWM_NOTES_V1:{"notes":[{"id":"n1","body":"첫 메모","updatedAt":1}]}';
const portCalls = [];
const sharedNotePort = {
  async getContent() { portCalls.push("getContent"); return { ok: true, text: sharedText }; },
  async setContent(text) { portCalls.push("setContent"); sharedText = text; return { ok: true }; },
  async getView() { portCalls.push("getView"); return { ok: true, revision: "r1", ratio: "0" }; },
  async setView() { portCalls.push("setView"); return { ok: true, revision: "r2" }; },
};
let layoutRequests = 0;
const feature = sandbox.MonitorNotesFeature.create({
  document: new FakeDocument(), enabled: true, sharedNotePort,
  aiPort: { async organize(payload) { return payload; } },
  onTrash() {}, onStatus() {}, errorText: String,
  onLayoutChange: () => { layoutRequests += 1; },
  requestFrame: (callback) => { callback(); return 1; }, cancelFrame() {},
  setTimer: () => 1, clearTimer() {},
});
assert.equal(feature.element.classList.contains("monitor-side-note"), true);
assert.equal(feature.snapshot().noteCount, 0);
feature.refreshContent().then(() => {
  assert.equal(feature.snapshot().noteCount, 1);
  assert.equal(feature.snapshot().ready, true);
  const placed = feature.layout({ rootRect: { left: 500, top: 20, height: 420 } });
  assert.equal(placed.left, 192);
  assert.equal(feature.element.style.top, "20px");
  feature.element.querySelector("#monitorNoteCollapse").dispatch("click");
  assert.equal(feature.snapshot().collapsed, true);
  assert.equal(layoutRequests, 2);
  assert.equal(feature.restoreNote({ id: "n2", body: "복구", title: "복구" }), true);
  assert.equal(feature.snapshot().noteCount, 2);
  assert.ok(portCalls.includes("getContent"));
  feature.destroy();
  assert.equal(feature.element.removed, true);
  console.log("PASS: Notes owns its DOM/state/history and reaches Native/ACT only through injected ports");
}).catch((error) => { console.error(error); process.exitCode = 1; });
