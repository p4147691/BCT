"use strict";
// Shared state/role/selection contract: source-only, no browser or disk effects.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const extension = path.join(__dirname, "../extension");
const src = fs.readFileSync(path.join(extension, "monitor-node-token-visual-contract.js"), "utf8");
const html = fs.readFileSync(path.join(extension, "desktop.html"), "utf8");
const css = fs.readFileSync(path.join(extension, "monitor.css"), "utf8");
const projection = fs.readFileSync(path.join(extension, "monitor-bct-thumbnail-projection.js"), "utf8");
const minimized = fs.readFileSync(path.join(__dirname, "../domains/node-identity.js"), "utf8");
const bridge = fs.readFileSync(path.join(__dirname, "../domains/thumbnail-wallpaper.js"), "utf8");
const ctx = { globalThis: null };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx);
const contract = ctx.MonitorNodeTokenVisualContract;
assert.ok(Object.isFrozen(contract));
const manager = { roleTags: ["USER", "Manager"] };
const supervisor = { roleTags: ["supervisor"] };
const working = { kind: "working", conversationKey: "c1" };
const ready = { kind: "ready", conversationKey: "c2" };
const abnormal = { kind: "abnormal", conversationKey: "c3" };
assert.deepEqual([...contract.classesFor(manager, working, false)],
  ["is-role-manager", "has-report", "is-working"]);
assert.deepEqual([...contract.classesFor(supervisor, ready, true)],
  ["is-role-supervisor", "has-report", "is-ready", "is-selected"]);
assert.deepEqual([...contract.classesFor({}, abnormal, false)],
  ["has-report", "is-abnormal"]);
assert.equal(contract.roleFor({ roleTags: ["manager", "supervisor"] }), "",
  "contradictory role metadata may not invent a preferred authority");
assert.equal(contract.roleFor({ scopeName: "Manager", nodeLabel: "N1" }), "",
  "roles must never be guessed from labels");
assert.equal(contract.shouldAcknowledge(working), false);
assert.equal(contract.shouldAcknowledge(ready), true);
assert.equal(contract.shouldAcknowledge(abnormal), true);
assert.equal(contract.shouldAcknowledge({ kind: "ready" }), false);
assert.equal(contract.shouldAcknowledge({ kind: "stopped", conversationKey: "c4" }), true);
assert.equal(contract.activityFor({kind:"completed"}), "ready");
assert.equal(contract.activityFor({kind:"stopped"}), "abnormal");
assert.equal(contract.activityFor({kind:"failed"}), "abnormal");
for (const selector of ["monitor-thumbnail-tab-token", "monitor-desktop-minimized-node"]) {
  const selected = selector === "monitor-thumbnail-tab-token"
    ? ".monitor-thumbnail-tab-token.is-selected"
    : ".monitor-desktop-minimized-node-selected";
  const workingRule = css.match(new RegExp("\\." + selector + "\\.is-working\\s*\\{([^}]*)\\}"));
  const readyRule = css.match(new RegExp("\\." + selector + "\\.is-ready\\s*\\{([^}]*)\\}"));
  const abnormalRule = css.match(new RegExp("\\." + selector + "\\.is-abnormal\\s*\\{([^}]*)\\}"));
  const selectedRule = css.match(new RegExp(selected.replaceAll(".", "\\.") + "\\s*\\{([^}]*)\\}"));
  assert.match(workingRule?.[1] || "", /color:#ff9e35!important/);
  assert.match(readyRule?.[1] || "", /color:#45e67b!important/);
  assert.match(abnormalRule?.[1] || "", /color:#ff5f67!important/);
  assert.match(selectedRule?.[1] || "", /color:#fff!important/);
  assert.ok((selectedRule?.[1] || "").includes("transform:scale(1.16)"));
  assert.ok(css.indexOf(selected) > css.indexOf("." + selector + ".is-abnormal"),
    "selected white must override all activity rules");
  for (const role of ["manager", "supervisor"]) {
    const roleRule = css.match(new RegExp("\\." + selector + "\\.is-role-" + role + "\\s*\\{([^}]*)\\}"));
    assert.match(roleRule?.[1] || "", new RegExp(role === "manager" ? "#ffd75a" : "#55a9ff"));
    assert.match(roleRule?.[1] || "", /outline:1px solid/);
    assert.match(roleRule?.[1] || "", /border-radius:0!important/);
  }
}
assert.match(projection, /MonitorNodeTokenVisualContract/);
assert.match(projection, /nodeForTab/);
assert.match(minimized, /MonitorNodeTokenVisualContract/);
assert.match(bridge, /nodeForTab:/);
assert.ok(minimized.includes("shouldAcknowledge(selectedReport)"),
  "explicit list selection acknowledges only terminal reports");
assert.ok(html.indexOf("monitor-node-token-visual-contract.js") <
  html.indexOf("monitor-bct-thumbnail-projection.js"),
  "pure helper must be loaded before both renderers");
console.log("PASS: shared thumbnail/minimized role outline, activity colors, white selection and acknowledgement boundary");
