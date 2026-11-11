"use strict";
// Fixed-purpose adapter. No caller URL, JS, plugin ID or CDP method is accepted.
const fs = require("node:fs");
const path = require("node:path");
const PLUGIN_PATH = "/settings/plugins-settings/plugin_asdk_app_6ac3a06ea58c819195b90feb131b6da5";
const URL = "https://chatgpt.com" + PLUGIN_PATH;

function clickExactRefresh(expectedPath) {
  if (location.origin !== "https://chatgpt.com" || location.pathname !== expectedPath)
    return {clicked: false, code: "PLUGIN_LOCATION_MISMATCH"};
  const visible = e => e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== "hidden" && getComputedStyle(e).display !== "none";
  const headings = [...document.querySelectorAll("h1,h2,h3")]
    .filter(e => visible(e) && e.textContent.trim() === "BCT Control");
  if (headings.length !== 1)
    return {clicked: false, code: "PLUGIN_HEADING_NOT_UNIQUE"};
  const buttons = [...document.querySelectorAll("button")].filter(e =>
    visible(e) && ["도구 새로 고침", "Refresh tools"].includes(e.textContent.trim()));
  if (buttons.length !== 1 || buttons[0].disabled ||
      buttons[0].getAttribute("aria-disabled") === "true")
    return {clicked: false, code: "PLUGIN_REFRESH_NOT_UNIQUE_OR_DISABLED"};
  buttons[0].click();
  return {clicked: true};
}

async function refresh(a, puppeteer) {
  if (a.operation !== "refresh_tools" || a.target !== "bct_control")
    throw Error("PLUGIN_REFRESH_ARGUMENTS_NOT_ALLOWED");
  let browser, session, owned, effect = false, targetUnresolved = false, result;
  try {
    const port = fs.readFileSync(path.join(a.profile_root, "DevToolsActivePort"), "utf8")
      .trim().split(/\r?\n/);
    if (!/^\d+$/.test(port[0]) || Number(port[0]) < 1 || Number(port[0]) > 65535 ||
        !/^\/devtools\/browser\/[a-zA-Z0-9-]+$/.test(port[1] || ""))
      throw Error("INVALID_CDP_PORT");
    browser = await puppeteer.connect({
      browserWSEndpoint: "ws://127.0.0.1:" + port[0] + port[1], defaultViewport: null,
    });
    session = await browser.target().createCDPSession();
    // Target creation itself is a mutation, even if its reply is lost.
    targetUnresolved = true;
    const created = await session.send("Target.createTarget", {url: URL, background: true});
    owned = created.targetId;
    if (!owned) throw Error("OWNED_TARGET_ID_MISSING");
    const target = await browser.waitForTarget(t => t._targetId === owned, {timeout: 15000});
    const page = await target.page();
    if (!page) throw Error("OWNED_PAGE_UNAVAILABLE");
    await page.waitForFunction(p => location.origin === "https://chatgpt.com" &&
      location.pathname === p && document.readyState === "complete",
      {timeout: 15000, polling: 200}, PLUGIN_PATH);
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some(e =>
      ["도구 새로 고침", "Refresh tools"].includes(e.textContent.trim())),
      {timeout: 15000, polling: 200});
    // Lost evaluate response after dispatch is UNKNOWN, never a fresh click.
    effect = true;
    const clicked = await page.evaluate(clickExactRefresh, PLUGIN_PATH);
    if (clicked.clicked !== true) {
      effect = false; throw Error(clicked.code || "PLUGIN_REFRESH_NOT_CLICKED");
    }
    // This proves one click, NOT successful catalogue synchronization.
    result = {status: "PASS", operation: "refresh_tools", target: "bct_control",
      click_dispatched: true, client_catalog_verified: false};
  } catch (e) {
    result = {status: "ERROR", code: String(e.message || e).slice(0, 180),
      effect_started: effect || targetUnresolved};
  } finally {
    if (session && owned) {
      try {
        const closed = await session.send("Target.closeTarget", {targetId: owned});
        if (closed.success !== true) throw Error("OWNED_TAB_CLOSE_UNCONFIRMED");
        targetUnresolved = false;
        result.owned_tab_closed = true;
        if (result.status === "ERROR") result.effect_started = effect;
      } catch {
        result = {...result, status: "ERROR", code: "OWNED_TAB_CLOSE_UNCONFIRMED",
          effect_started: effect || targetUnresolved, owned_tab_closed: false};
      }
    }
    if (session) try { await session.detach(); } catch {}
    if (browser) try { await browser.disconnect(); } catch {}
  }
  return result;
}

module.exports = {refresh, clickExactRefresh, PLUGIN_PATH};
if (require.main === module) {
  (async () => {
    try {
      const a = JSON.parse(fs.readFileSync(0, "utf8"));
      console.log(JSON.stringify(await refresh(a, require(a.puppeteer_module))));
    } catch (e) {
      console.log(JSON.stringify({status: "ERROR", effect_started: false,
        code: String(e.message || e).slice(0, 180)}));
    }
  })();
}
