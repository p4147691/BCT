"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
require(path.join(__dirname, "..", "extension", "monitor-ui-layout.js"));
const layout = globalThis.MonitorUiLayout;

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.parentNode = null;
    this.hidden = false;
    this.dataset = {};
    this.styleValues = {};
    this.style = { setProperty: (name, val) => { this.styleValues[name] = val; } };
    this.classes = new Set();
    this.classList = { toggle: (name, value) => {
      if (value) this.classes.add(name);
      else this.classes.delete(name);
    } };
    this.listeners = new Map();
    this.value = "";
    this._html = "";
  }
  set innerHTML(v) {
    this._html = v;
    if (this.id === "bwmUiLayoutEditor") {
      for (const id of ["bwmUiLayoutJson", "bwmUiLayoutApply", "bwmUiLayoutReset",
                        "bwmUiLayoutClose", "bwmUiLayoutError"]) {
        this.appendChild(new FakeElement(id));
      }
    }
  }
  get innerHTML() { return this._html; }
  setAttribute() {}
  appendChild(child) {
    if (child.parentNode) child.parentNode.children =
      child.parentNode.children.filter((entry) => entry !== child);
    this.children.push(child);
    child.parentNode = this;
    return child;
  }
  remove() {
    if (this.parentNode) this.parentNode.children =
      this.parentNode.children.filter((entry) => entry !== this);
    this.parentNode = null;
  }
  addEventListener(name, cb) {
    const list = this.listeners.get(name) || [];
    list.push(cb);
    this.listeners.set(name, list);
  }
  click() {
    for (const cb of this.listeners.get("click") || []) cb();
  }
  querySelector(selector) {
    const name = selector.startsWith("#") ? selector.slice(1) : selector.slice(1);
    if ((selector[0] === "#" && this.id === name)) return this;
    for (const child of this.children) {
      if ((selector[0] === "#" && child.id === name)) return child;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    if (selector === ".monitor-title-line" && this.classes.has("monitor-title-line")) return this;
    if (selector === ".monitor-title-block" && this.classes.has("monitor-title-block")) return this;
    if (selector === ".monitor-utility-actions" && this.classes.has("monitor-utility-actions")) return this;
    return null;
  }
}
function makeRoot() {
  const root = new FakeElement("root");
  const block = new FakeElement("block");
  block.classes.add("monitor-title-block");
  const line = new FakeElement("line");
  line.classes.add("monitor-title-line");
  const toolbar = new FakeElement("toolbar");
  toolbar.classes.add("monitor-utility-actions");
  block.appendChild(line);
  block.appendChild(toolbar);
  root.appendChild(block);
  const buttons = new Map();
  for (const id of layout.BUTTONS) {
    const button = new FakeElement(id);
    toolbar.appendChild(button);
    buttons.set(id, button);
  }
  return { root, block, line, toolbar, buttons };
}
function makeStorage() {
  const data = new Map([["existingWorkerColumnsPreference", 3]]);
  const listeners = new Set();
  let mutationCount = 0;
  return {
    data,
    get mutations() { return mutationCount; },
    local: {
      async get(key) {
        return data.has(key) ? { [key]: data.get(key) } : {};
      },
      async set(values) {
        mutationCount++;
        for (const [key, newValue] of Object.entries(values)) {
          const oldValue = data.get(key);
          data.set(key, newValue);
          for (const listener of listeners) listener({[key]: {oldValue, newValue}}, "local");
        }
      },
      async remove(key) {
        mutationCount++;
        const oldValue = data.get(key);
        data.delete(key);
        for (const listener of listeners) listener({[key]: {oldValue}}, "local");
      }
    },
    onChanged: {
      addListener(listener) { listeners.add(listener); },
      removeListener(listener) { listeners.delete(listener); }
    }
  };
}

async function main() {
  globalThis.document = { visibilityState: "visible", createElement: () => new FakeElement() };
  const css = require("node:fs").readFileSync(path.join(__dirname, "..", "extension", "monitor-ui-layout.css"), "utf8");
  assert.match(css, /flex-wrap:\s*nowrap\s*!important/, "toolbar must not wrap over node list");
  assert.match(css, /overflow-x:\s*auto/, "narrow header must clip/scroll, not overlay nodes");
  assert.match(css, /#bwmUiLayoutEditor/, "stale editor must be hidden");
  const storage = makeStorage();
  const first = makeRoot();
  let nextRemote = { status: "READY", config: {
    version: 1, toolbar: { placement: "inline", density: "compact", gap: 2,
      order: [...layout.BUTTONS], hidden: [] }
  }};
  const fetcher = async () => ({ ok: true, json: async () => nextRemote });
  const controller = layout.create(first.root, storage, null, { fetcher, pollMs: 0 });
  await controller.ready;
  assert.equal(first.toolbar.parentNode, first.line);
  assert.equal(first.root.querySelector("#bwmUiLayoutOpen"), null, "no user editor");
  assert.equal(first.root.querySelector("#bwmUiLayoutEditor"), null, "no overlay");
  assert.equal(storage.data.get("existingWorkerColumnsPreference"), 3);
  assert.equal(storage.mutations, 0, "configuration read does not mutate existing storage");
  assert.deepEqual(first.toolbar.children.map(x => x.id), layout.BUTTONS);
  assert.equal(first.toolbar.styleValues["--bwm-ui-toolbar-gap"], "2px");
  let clicks = 0;
  const rccButton = first.buttons.get("monitorRccReload");
  rccButton.addEventListener("click", () => { ++clicks; });
  rccButton.click();
  assert.equal(clicks, 1);
  const reverse = [...layout.BUTTONS].reverse();
  nextRemote = { status: "READY", config: { version: 1, toolbar: {
    placement: "inline", density: "normal", gap: 4,
    order: reverse, hidden: ["monitorMcpTunnelRecover"]
  }}};
  await controller.refreshRemote();
  assert.equal(first.buttons.get("monitorRccReload"), rccButton);
  rccButton.click();
  assert.equal(clicks, 2, "real button handlers retained");
  assert.deepEqual(first.toolbar.children.map(x => x.id), reverse);
  assert.equal(first.buttons.get("monitorMcpTunnelRecover").hidden, true);
  assert.equal(storage.data.get("existingWorkerColumnsPreference"), 3);
  nextRemote = { status: "READY", config: { version: 1, toolbar: { placement: "javascript:bad" } } };
  await controller.refreshRemote();
  assert.deepEqual(first.toolbar.children.map(x => x.id), reverse, "bad remote config ignored");
  assert.equal(first.toolbar.parentNode, first.line);
  await assert.rejects(async () => layout.normalize({
    version:1,toolbar:{order:["random"],hidden:[]}
  }), /NOT_ALLOWED/);
  await assert.rejects(async () => layout.normalize({
    version:1,toolbar:{density:"normal",gap:-1}
  }), /NOT_ALLOWED/);
  const second = makeRoot();
  const other = layout.create(second.root, storage, null, { fetcher, pollMs: 0 });
  await other.ready;
  assert.equal(second.toolbar.parentNode, second.line, "safe default when Core remote invalid");
  assert.equal(second.root.querySelector("#bwmUiLayoutOpen"), null);
  controller.dispose();
  other.dispose();
  console.log("BWM_UI_LAYOUT_ENGINE_PASS: inline/default, no editor, no overlay, guarded remote, genuine button identity/listeners, 3-column preserved");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
