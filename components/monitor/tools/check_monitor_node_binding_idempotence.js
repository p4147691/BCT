const fs = require("fs");
const path = require("path");
const vm = require("vm");

const monitorPath = path.join(__dirname, "..", "extension", "monitor.js");
const source = fs.readFileSync(monitorPath, "utf8");

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`missing ${name}`);
  const bodyStart = source.indexOf("{", start);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`unterminated ${name}`);
}

const writes = [];
const context = {
  monitorNodeBindings: new Map(),
  monitorNodeBindingsReady: true,
  monitorPersistedNodeBindingsSignature: "",
  MONITOR_NODE_BINDINGS_KEY: "bindings",
  chrome: { storage: { local: { set: async (value) => { writes.push(value); } } } },
};
vm.createContext(context);
vm.runInContext([
  extractFunction("monitorCanonicalJsonValue"),
  extractFunction("monitorCanonicalNodeBindings"),
  extractFunction("monitorNodeBindingsSignature"),
  extractFunction("monitorPersistNodeBindings"),
  "this.runPersist = monitorPersistNodeBindings;",
].join("\n"), context);

const binding = {
  conversation_key: "conversation-1",
  tab_id: 7,
  hwnd: "123",
  transport_instance_id: "transport-1",
  nested: { z: 2, a: 1 },
  confirmed_at: 100,
};
context.monitorNodeBindings.set("tab:transport-1:7", binding);
context.monitorNodeBindings.set("lineage:transport-1:window-1", binding);
context.monitorNodeBindings.set("hwnd:123", binding);

if (context.runPersist() !== true) throw new Error("first material write was skipped");
if (writes.length !== 1 || writes[0].bindings.length !== 1) throw new Error("aliases were not deduplicated");
if (context.runPersist() !== false || writes.length !== 1) throw new Error("identical binding caused another write");

context.monitorNodeBindings.set("hwnd:123", { ...binding, confirmed_at: 999 });
if (context.runPersist() !== false || writes.length !== 1) throw new Error("write-only observation time caused another write");

context.monitorNodeBindings.set("hwnd:123", { ...binding, tab_id: 8 });
if (context.runPersist() !== true || writes.length !== 2) throw new Error("material binding change was not persisted");

if (!source.includes("const bindingsActuallyChanged=nextSignature!==monitorPersistedNodeBindingsSignature")) {
  throw new Error("storage self-write render guard missing");
}

console.log("PASS: node binding aliases persist once; identical writes and self-render feedback are suppressed");
