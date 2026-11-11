"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {refresh, clickExactRefresh, PLUGIN_PATH} = require("../scripts/chatgpt_tools_refresh.cjs");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");

function fixture({heading = "BCT Control", count = 1, disabled = false,
                  origin = "https://chatgpt.com", pathname = PLUGIN_PATH} = {}) {
  let clicks = 0;
  const element = textContent => ({textContent, getClientRects: () => [1]});
  global.location = {origin, pathname};
  global.getComputedStyle = () => ({visibility: "visible", display: "block"});
  const buttons = Array.from({length: count}, () => ({
    ...element("도구 새로 고침"), disabled, getAttribute: () => null,
    click: () => { clicks++; },
  }));
  global.document = {querySelectorAll: s => s === "button" ? buttons : [element(heading)]};
  return () => clicks;
}
test("exact plugin button clicked once", () => {
  const clicks = fixture();
  assert.equal(clickExactRefresh(PLUGIN_PATH).clicked, true);
  assert.equal(clicks(), 1);
});
for (const [name, args] of Object.entries({
  "ambiguous buttons": {count: 2}, "missing button": {count: 0},
  "disabled button": {disabled: true}, "wrong plugin": {heading: "Other"},
  "wrong origin": {origin: "https://example.com"}, "wrong path": {pathname: "/"},
})) {
  test(name + " never clicks", () => {
    const clicks = fixture(args);
    assert.equal(clickExactRefresh(PLUGIN_PATH).clicked, false);
    assert.equal(clicks(), 0);
  });
}

async function runFake(options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bct-refresh-"));
  fs.writeFileSync(path.join(root, "DevToolsActivePort"), "1234\n/devtools/browser/exact-id\n");
  const calls = [];
  const session = {
    send: async (method, args) => {
      calls.push({method, args});
      if (method === "Target.createTarget") return {targetId: "owned"};
      return {success: !options.closeFailure};
    }, detach: async () => {},
  };
  const page = {waitForFunction: async () => {}, evaluate: async fn => {
    if (options.evaluateFailure) throw Error("RESPONSE_LOST");
    return fn(PLUGIN_PATH);
  }};
  const browser = {
    target: () => ({createCDPSession: async () => session}),
    waitForTarget: async predicate => {
      assert.equal(predicate({_targetId: "unrelated"}), false);
      assert.equal(predicate({_targetId: "owned"}), true);
      return {page: async () => page};
    }, disconnect: async () => {},
  };
  try {
    const result = await refresh({operation: "refresh_tools", target: "bct_control",
      profile_root: root}, {connect: async () => browser});
    return {result, calls};
  } finally { fs.rmSync(root, {recursive: true}); }
}
test("refresh owns only its background tab and reports no catalogue proof", async () => {
  const clicks = fixture();
  const {result, calls} = await runFake();
  assert.equal(result.status, "PASS");
  assert.equal(result.client_catalog_verified, false);
  assert.equal(result.owned_tab_closed, true);
  assert.equal(clicks(), 1);
  assert.equal(calls[0].args.background, true);
  assert.deepEqual(calls[1], {method: "Target.closeTarget", args: {targetId: "owned"}});
});
test("lost evaluate response is UNKNOWN and no replay", async () => {
  fixture();
  const {result, calls} = await runFake({evaluateFailure: true});
  assert.equal(result.status, "ERROR");
  assert.equal(result.effect_started, true);
  assert.equal(calls.length, 2);
});
test("ambiguous control is confirmed no click", async () => {
  const clicks = fixture({count: 2});
  const {result} = await runFake();
  assert.equal(result.effect_started, false);
  assert.equal(result.owned_tab_closed, true);
  assert.equal(clicks(), 0);
});
test("failed cleanup cannot be reported as APPLIED", async () => {
  fixture();
  const {result} = await runFake({closeFailure: true});
  assert.equal(result.status, "ERROR");
  assert.equal(result.effect_started, true);
  assert.equal(result.owned_tab_closed, false);
});
