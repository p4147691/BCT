"use strict";

// Fixed adapter for the BCT Window Monitor only.  The caller supplies local
// connection paths, never an extension ID, URL, function, script, or CDP
// method.  This file has exactly one possible browser effect.
const fs = require("fs");
const path = require("path");
const MONITOR_ID = "kaigandfpieiogfbfaemoimenmipedck";
let browser = null;
let effectStarted = false;

function fail(code) { throw new Error(code); }

async function main(input) {
  const keys = Object.keys(input || {}).sort();
  if (keys.join(",") !== "profile_root,puppeteer_module") fail("INPUT_NOT_ALLOWED");
  if (!path.isAbsolute(input.profile_root) || !path.isAbsolute(input.puppeteer_module)) {
    fail("ABSOLUTE_PATH_REQUIRED");
  }
  const portInfo = fs.readFileSync(
    path.join(input.profile_root, "DevToolsActivePort"), "utf8"
  ).trim().split(/\r?\n/);
  if (!/^\d+$/.test(portInfo[0]) || !portInfo[1].startsWith("/devtools/browser/")) {
    fail("INVALID_CDP_PORT");
  }
  const puppeteer = require(input.puppeteer_module);
  browser = await puppeteer.connect({
    browserWSEndpoint: "ws://127.0.0.1:" + portInfo[0] + portInfo[1],
    defaultViewport: null,
  });
  const prefix = "chrome-extension://" + MONITOR_ID + "/desktop.html";
  const targets = browser.targets().filter(
    target => target.type() === "page" && target.url().startsWith(prefix)
  );
  if (!targets.length) fail("OWNED_MONITOR_PAGE_REQUIRED");
  const page = await targets[0].page();
  if (!page) fail("OWNED_MONITOR_PAGE_UNAVAILABLE");
  const identity = await page.evaluate(() => ({
    id: chrome.runtime.id,
    name: chrome.runtime.getManifest().name,
    version: chrome.runtime.getManifest().version,
  }));
  if (identity.id !== MONITOR_ID || identity.name !== "BCT Window Monitor") {
    fail("OWNED_MONITOR_IDENTITY_MISMATCH");
  }
  effectStarted = true;
  const queued = await page.evaluate(() => {
    chrome.runtime.sendMessage({ type: "monitor-reload-extension" });
    return true;
  });
  if (queued !== true) fail("OWNED_MONITOR_RELOAD_NOT_QUEUED");
  return { status: "PASS", effect_started: true, queued: true, version: identity.version };
}

(async () => {
  try {
    const input = JSON.parse(fs.readFileSync(0, "utf8"));
    console.log(JSON.stringify(await main(input)));
  } catch (error) {
    console.log(JSON.stringify({
      status: "ERROR",
      effect_started: effectStarted,
      code: String(error && error.message || error).slice(0, 180),
    }));
  } finally {
    if (browser) try { await browser.disconnect(); } catch (_) {}
  }
})();
