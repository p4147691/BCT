"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const extension = path.join(root, "extension");
const featurePath = path.join(extension, "features", "sketch", "monitor-sketch-feature.js");
const featureCssPath = path.join(extension, "features", "sketch", "monitor-sketch-feature.css");
const featureSource = fs.readFileSync(featurePath, "utf8");
const featureCss = fs.readFileSync(featureCssPath, "utf8");
const monitorSource = fs.readFileSync(path.join(extension, "monitor.js"), "utf8");
const monitorCss = fs.readFileSync(path.join(extension, "monitor.css"), "utf8");
const html = fs.readFileSync(path.join(extension, "desktop.html"), "utf8");

const scriptTag = '<script src="features/sketch/monitor-sketch-feature.js"></script>';
const cssTag = '<link rel="stylesheet" href="features/sketch/monitor-sketch-feature.css">';
assert.ok(html.includes(scriptTag), "desktop must load the standalone Sketch controller");
assert.ok(html.indexOf(scriptTag) < html.indexOf('<script src="monitor.js"></script>'),
  "Sketch controller must load before the compatibility bundle");
assert.ok(html.includes(cssTag), "desktop must load the standalone Sketch stylesheet");

assert.doesNotMatch(featureSource, /\blocalStorage\b|\bchrome\.|document\.getElementById/,
  "Sketch controller must use injected ports and its own root");
assert.doesNotMatch(monitorSource, /function monitorSketch|const monitorSketchCanvas|className = "monitor-sketchpad"/,
  "compatibility bundle must not retain the old Sketch implementation");
assert.match(monitorSource, /MonitorSketchFeature\?\.create\(/,
  "compatibility bundle must only compose the standalone Sketch feature");
assert.doesNotMatch(monitorCss, /\.monitor-sketchpad|#monitorSketchCanvas/,
  "shared Monitor CSS must not retain Sketch ownership");
assert.match(featureCss, /\.monitor-sketchpad/);
assert.match(featureCss, /#monitorSketchCanvas/);

class FakeClassList {
  constructor(initial = "") { this.values = new Set(String(initial).split(/\s+/).filter(Boolean)); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    return enabled;
  }
  contains(name) { return this.values.has(name); }
}

class FakeStyle {
  setProperty(name, value) { this[name] = value; }
}

function context2d() {
  return {
    clearRect() {}, save() {}, restore() {}, drawImage() {}, beginPath() {}, moveTo() {}, lineTo() {},
    stroke() {}, closePath() {}, strokeRect() {}, fillText() {},
    measureText() { return { actualBoundingBoxLeft: 0, fontBoundingBoxAscent: 16, fontBoundingBoxDescent: 4 }; },
  };
}

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.style = new FakeStyle();
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.childrenById = new Map();
    this.parentElement = null;
    this.width = this.tagName === "CANVAS" ? 900 : 0;
    this.height = this.tagName === "CANVAS" ? 1200 : 0;
  }
  set className(value) { this._className = value; this.classList = new FakeClassList(value); }
  get className() { return this._className || ""; }
  set innerHTML(value) {
    this._innerHTML = value;
    const wrap = new FakeElement("div");
    wrap.getBoundingClientRect = () => ({ left: 0, top: 0, right: 280, bottom: 500, width: 280, height: 500 });
    const pattern = /<(button|canvas|div|input)[^>]*\bid="([^"]+)"[^>]*>/g;
    let match;
    while ((match = pattern.exec(value))) {
      const child = new FakeElement(match[1], match[2]);
      child.hidden = /\shidden(?:\s|>)/.test(match[0]);
      child.parentElement = child.tagName === "CANVAS" || child.tagName === "INPUT" ? wrap : this;
      this.childrenById.set(child.id, child);
    }
  }
  get innerHTML() { return this._innerHTML || ""; }
  querySelector(selector) { return selector.startsWith("#") ? this.childrenById.get(selector.slice(1)) || null : null; }
  setAttribute(name, value) { this[name] = String(value); }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter((item) => item !== listener));
  }
  dispatch(type, event = {}) {
    const supplied = { preventDefault() {}, button: 0, pointerId: 1, ...event, type, target: event.target || this };
    for (const listener of this.listeners.get(type) || []) listener(supplied);
  }
  contains(target) { return target === this; }
  getBoundingClientRect() { return { left: 0, top: 0, right: 280, bottom: 500, width: 280, height: 500 }; }
  getContext() { return context2d(); }
  toDataURL() { return "data:image/png;base64,TEST"; }
  setPointerCapture() {}
  releasePointerCapture() {}
  focus() {}
  remove() { this.removed = true; }
}

class FakeDocument {
  constructor() { this.listeners = new Map(); }
  createElement(tagName) { return new FakeElement(tagName); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  removeEventListener(type, listener) { if (this.listeners.get(type) === listener) this.listeners.delete(type); }
}

const sandbox = { globalThis: null, Object, String, Number, Math, Array, Boolean, Error, TypeError, Set };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(featureSource, sandbox, { filename: featurePath });
assert.equal(typeof sandbox.MonitorSketchFeature?.create, "function");

const events = [];
const storage = {
  get(key) { events.push(["get", key]); return null; },
  set(key, value) { events.push(["set", key, value]); return true; },
  remove(key) { events.push(["remove", key]); return true; },
};
class FakeImage { set src(value) { this._src = value; if (this.onload) this.onload(); } }
let layoutRequests = 0;
const feature = sandbox.MonitorSketchFeature.create({
  document: new FakeDocument(), storage, ImageCtor: FakeImage,
  requestFrame: (callback) => callback(), setTimer: () => 1, clearTimer() {},
  onLayoutChange: () => { layoutRequests += 1; },
});

assert.equal(feature.element.classList.contains("monitor-sketchpad"), true);
assert.deepEqual(JSON.parse(JSON.stringify(feature.snapshot())),
  { tool: "pen", textSize: "medium", collapsed: false, undoDepth: 0, redoDepth: 0 });
feature.layout({ rootRect: { top: 20, height: 400 }, noteLeft: 300 });
assert.equal(feature.element.style.top, "20px");
assert.equal(feature.element.style.left, "12px");
feature.element.querySelector("#monitorSketchCollapse").dispatch("click");
assert.equal(feature.snapshot().collapsed, true);
assert.equal(layoutRequests, 1);
feature.layout({ rootRect: { top: 20, height: 400 }, noteLeft: 300 });
assert.equal(feature.element.style.height, "40px");
feature.layout({ boardCollapsed: true });
assert.equal(feature.element.hidden, true);
feature.element.querySelector("#monitorSketchClear").dispatch("click");
assert.ok(events.some(([operation, key]) => operation === "remove" && key === "desktopWindowMonitorSketchV1"));
feature.destroy();
assert.equal(feature.element.removed, true);

console.log("PASS: Sketch is a single-owner screen feature with injected storage and a bounded layout API");
