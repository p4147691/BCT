"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "chat_tools.js"), "utf8");
// Automatic attachment must inspect the latest already-complete assistant
// turn. Older turns remain behind the baseline and the observed fingerprint
// still prevents replay after extension or page reload.
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
            return {enabled: true, automatic: true};
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
