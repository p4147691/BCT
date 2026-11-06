"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "chat_tools.js"), "utf8");
let listener;
let clicks = 0;
const input = {
  innerText: "",
  textContent: "",
  focus() {},
};
const button = {disabled: false, click() { clicks += 1; }};
const document = {
  body: {},
  querySelector(selector) {
    if (selector.includes("stop-button")) return null;
    if (selector.includes("prompt-textarea")) return input;
    if (selector.includes("send-button")) return input.innerText ? button : null;
    if (selector === "main") return null;
    return null;
  },
  querySelectorAll() { return []; },
  execCommand(command, _showUi, value) {
    if (command === "insertText") {
      input.innerText = value;
      input.textContent = value;
      return true;
    }
    if (command === "selectAll") return true;
    if (command === "delete") {
      input.innerText = "";
      input.textContent = "";
      return true;
    }
    return false;
  },
};

const context = {
  chrome: {
    runtime: {
      onMessage: {addListener(value) { listener = value; }},
      sendMessage: async () => ({enabled: false}),
    },
    storage: {local: {get: async () => ({}), set: async () => {}, remove: async () => {}}},
  },
  crypto: webcrypto,
  document,
  location: {pathname: "/c/11111111-2222-3333-4444-555555555555"},
  MutationObserver: class { observe() {} },
  HTMLTextAreaElement: class {},
  HTMLInputElement: class {},
  InputEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
  TextEncoder,
  setTimeout,
  clearTimeout,
};
context.globalThis = context;
vm.runInNewContext(source, context, {filename: "chat_tools.js"});
assert.equal(typeof listener, "function");

new Promise((resolve, reject) => {
  const keepChannel = listener({type: "BCT_BRIDGE_BOOTSTRAP"}, {}, reply => {
    try {
      assert.equal(reply?.sent, true);
      assert.equal(clicks, 1);
      assert.match(input.innerText, /BCT Browser Bridge/);
      resolve();
    } catch (error) { reject(error); }
  });
  assert.equal(keepChannel, true);
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
