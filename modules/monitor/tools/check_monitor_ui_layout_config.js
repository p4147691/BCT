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
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function main() {
  globalThis.document = { createElement: () => new FakeElement() };
  assert.equal(layout.KEY, "bwm.monitor.ui.layout.v1");
  const storage = makeStorage();
  const first = makeRoot();
  const controller = layout.create(first.root, storage);
  await controller.ready;
  assert.equal(first.toolbar.parentNode, first.block);
  assert.equal(first.root.querySelector("#bwmUiLayoutOpen") !== null, true);
  assert.equal(storage.data.get("existingWorkerColumnsPreference"), 3);
  assert.equal(storage.mutations, 0, "startup must not write");
  let clicks = 0;
  first.buttons.get("monitorRccReload").addEventListener("click", () => { clicks++; });
  const order = [...layout.BUTTONS].reverse();
  const previous = first.buttons.get("monitorRccReload");
  await controller.patch({toolbar: {
    placement: "inline", density: "compact", gap: 2,
    order, hidden: ["monitorMcpTunnelRecover"]
  }});
  assert.equal(controller.read().toolbar.placement, "inline");
  assert.equal(first.toolbar.parentNode, first.line);
  assert.ok(first.line.children.indexOf(first.toolbar) < first.line.children.indexOf(first.root.querySelector("#bwmUiLayoutOpen")));
  assert.deepEqual(first.toolbar.children.map((c) => c.id), order);
  assert.equal(first.toolbar.styleValues["--bwm-ui-toolbar-gap"], "2px");
  assert.equal(first.buttons.get("monitorMcpTunnelRecover").hidden, true);
  assert.equal(first.buttons.get("monitorRccReload"), previous);
  previous.click();
  assert.equal(clicks, 1, "existing click listener retained");
  assert.equal(storage.data.get("existingWorkerColumnsPreference"), 3);
  const second = makeRoot();
  const secondController = layout.create(second.root, storage);
  await secondController.ready;
  assert.equal(second.toolbar.parentNode, second.line, "persistent across monitor screens");
  assert.deepEqual(secondController.read().toolbar.order, order);
  const before = storage.mutations;
  await assert.rejects(() => controller.patch({toolbar:{placement:"javascript:alert(1)"}}), /NOT_ALLOWED/);
  await assert.rejects(() => controller.patch({toolbar:{unknown: true}}), /NOT_ALLOWED/);
  await assert.rejects(() => controller.patch({toolbar:{hidden:["monitorBadAction"]}}), /NOT_ALLOWED/);
  await assert.rejects(() => controller.patch({__proto__: null, toolbar: {hidden: ["other"]}}), /NOT_ALLOWED/);
  assert.equal(storage.mutations, before, "invalid patches never persist");
  const editor = controller.showEditor();
  assert.equal(editor.hidden, false);
  const field = editor.querySelector("#bwmUiLayoutJson");
  const next = controller.read();
  next.toolbar.hidden = [];
  field.value = JSON.stringify(next);
  field.listeners.get("input")[0]();
  editor.querySelector("#bwmUiLayoutApply").click();
  await tick();
  assert.deepEqual(controller.read().toolbar.hidden, []);
  assert.deepEqual(secondController.read().toolbar.hidden, [], "storage event sync");
  await controller.reset();
  assert.equal(first.toolbar.parentNode, first.block, "reset restores original parent");
  assert.equal(second.toolbar.parentNode, second.block);
  assert.deepEqual(first.toolbar.children.map((c) => c.id), [...layout.BUTTONS]);
  assert.equal(storage.data.has(layout.KEY), false);
  assert.equal(storage.data.get("existingWorkerColumnsPreference"), 3);
  controller.dispose();
  secondController.dispose();
  assert.equal(first.root.querySelector("#bwmUiLayoutOpen"), null);
  // A stale initial storage read must not undo a newer storage change.
  const raceStorage = makeStorage();
  let resolveOldGet;
  raceStorage.local.get = () => new Promise((resolve) => { resolveOldGet = resolve; });
  const raceView = makeRoot();
  const raceController = layout.create(raceView.root, raceStorage);
  await raceStorage.local.set({[layout.KEY]: {version:1, toolbar:{placement:"inline"}}});
  resolveOldGet({});
  await raceController.ready;
  assert.equal(raceView.toolbar.parentNode, raceView.line);
  raceController.dispose();
  const broken = makeRoot();
  const errors = [];
  storage.data.set(layout.KEY, {version: 1, toolbar: {placement:"bad"}});
  const third = layout.create(broken.root, storage, (err) => errors.push(err.message));
  await third.ready;
  assert.equal(errors.includes("UI_LAYOUT_VALUE_NOT_ALLOWED"), true);
  assert.equal(broken.toolbar.parentNode, broken.block);
  third.dispose();
  console.log("BWM_UI_LAYOUT_ENGINE_PASS: persistence, real node reparenting, identity/listeners, validation, editor, rollback, storage sync, 3-column preservation");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
