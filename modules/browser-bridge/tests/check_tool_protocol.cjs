"use strict";
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(require("path").join(__dirname, "../extension/tool_protocol.js"), "utf8");
const context = {globalThis: {}};
vm.runInNewContext(source, context);
const parse = context.globalThis.BctToolProtocol.parse;
const good = '[[BCT_TOOL_REQUEST]]\n{"tool":"bct_status","arguments":{"compact":true}}\n[[/BCT_TOOL_REQUEST]]';
if (parse(good)?.tool !== "bct_status") throw new Error("valid request rejected");
for (const bad of [
  'prefix ' + good,
  '[[BCT_TOOL_REQUEST]]\n{"tool":"bct_status","arguments":{},"extra":1}\n[[/BCT_TOOL_REQUEST]]',
  '[[BCT_TOOL_REQUEST]]\n{"tool":"bad tool","arguments":{}}\n[[/BCT_TOOL_REQUEST]]',
  '[[BCT_TOOL_REQUEST]]\n{"tool":"bct_status","arguments":[]}\n[[/BCT_TOOL_REQUEST]]'
]) if (parse(bad) !== null) throw new Error("invalid request accepted");
console.log("Browser Bridge generic tool protocol: PASS");
