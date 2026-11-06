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

// An explicit per-tab grant must also inspect the latest assistant turn that
// was already complete before the user enabled the bridge. Older turns remain
// behind the baseline and the observed fingerprint still prevents replay.
{
  let scanListener;
  let scanClicks = 0;
  let toolCalls = 0;
  const scanInput = {innerText: "", textContent: "", focus() {}};
  const latestAssistant = {
    innerText: "[[BCT_TOOL_REQUEST]]\n{\"tool\":\"bct_status\",\"arguments\":{\"compact\":true}}\n[[/BCT_TOOL_REQUEST]]",
  };
  const scanDocument = {
    body: {},
    querySelector(selector) {
      if (selector.includes("stop-button")) return null;
      if (selector.includes("prompt-textarea")) return scanInput;
      if (selector.includes("send-button")) {
        return scanInput.innerText ? {disabled: false, click() { scanClicks += 1; }} : null;
      }
      if (selector === "main") return null;
      return null;
    },
    querySelectorAll(selector) {
      return selector.includes('data-message-author-role="assistant"') ? [latestAssistant] : [];
    },
    execCommand(command, _showUi, value) {
      if (command === "insertText") {
        scanInput.innerText = value;
        scanInput.textContent = value;
        return true;
      }
      if (command === "selectAll") return true;
      if (command === "delete") {
        scanInput.innerText = "";
        scanInput.textContent = "";
        return true;
      }
      return false;
    },
  };
  const scanContext = {
    chrome: {
      runtime: {
        onMessage: {addListener(value) { scanListener = value; }},
        async sendMessage(message) {
          if (message.type === "BCT_CHAT_STATUS") {
            return {enabled: true, grantId: "new-grant"};
          }
          if (message.type === "BCT_CHAT_TOOL_CALL") {
            toolCalls += 1;
            return {ok: true, tool_name: message.toolName, output: {ready: true}};
          }
          throw new Error("unexpected message");
        },
      },
      storage: {local: {get: async () => ({}), set: async () => {}, remove: async () => {}}},
    },
    crypto: webcrypto,
    document: scanDocument,
    location: {pathname: "/c/11111111-2222-3333-4444-555555555555"},
    MutationObserver: class { observe() {} },
    HTMLTextAreaElement: class {},
    HTMLInputElement: class {},
    InputEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
    TextEncoder,
    setTimeout,
    clearTimeout,
  };
  scanContext.globalThis = scanContext;
  scanContext.BctToolProtocol = {
    parse(text) {
      return text === latestAssistant.innerText
        ? {tool: "bct_status", arguments: {compact: true}}
        : null;
    },
  };
  vm.runInNewContext(source, scanContext, {filename: "chat_tools.js"});
  assert.equal(typeof scanListener, "function");
  scanListener({type: "BCT_BRIDGE_SCAN_NOW"}, {}, () => {});
  setTimeout(() => {
    try {
      assert.equal(toolCalls, 1);
      assert.equal(scanClicks, 1);
      assert.match(scanInput.innerText, /\[\[BCT_TOOL_RESULT\]\]/);
    } catch (error) {
      console.error(error);
      process.exitCode = 1;
    }
  }, 900);
}
