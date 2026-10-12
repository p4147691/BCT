"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

require(path.join(__dirname, "..", "extension", "monitor-thumbnail-service.js"));

const createService = globalThis.MonitorThumbnailService?.create;
assert.equal(typeof createService, "function", "ThumbnailService factory is not loaded");

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function checkConcurrencyAndCoalescing() {
  let active = 0;
  let maxActive = 0;
  let runs = 0;
  const service = createService({
    maxConcurrent: 2,
    maxEntries: 12,
    capture: async ({ hwnd }) => {
      runs += 1;
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 8));
      active -= 1;
      return { value: `blob:${hwnd}`, dispose() {} };
    }
  });

  const sameA = service.requestSnapshot("100", "same-hwnd");
  const sameB = service.requestSnapshot("100", "same-hwnd");
  const remaining = ["101", "102", "103", "104"].map((hwnd) => service.requestSnapshot(hwnd, "burst"));
  const results = await Promise.all([sameA, sameB, ...remaining]);

  assert.equal(runs, 5, "same HWND requests must coalesce");
  assert.ok(maxActive <= 2, `capture concurrency exceeded 2: ${maxActive}`);
  assert.equal(results[0].value, results[1].value);
  assert.equal(service.stats().maxObservedActive, 2);
  service.disposeAll();
}

async function checkInvalidationDisposesStaleResult() {
  let release;
  let disposed = 0;
  const service = createService({
    capture: () => new Promise((resolve) => {
      release = () => resolve({ value: "blob:stale", dispose: () => { disposed += 1; } });
    })
  });

  const pending = service.requestSnapshot("200", "stale-check");
  await tick();
  service.invalidate("200");
  release();
  const result = await pending;

  assert.equal(result, null, "invalidated capture must not enter the cache");
  assert.equal(disposed, 1, "invalidated result must be disposed exactly once");
  assert.equal(service.stats().staleDiscarded, 1);
  service.disposeAll();
}

async function checkLruOwnership() {
  const disposed = [];
  const service = createService({
    maxEntries: 2,
    capture: async ({ hwnd }) => ({
      value: `blob:${hwnd}`,
      dispose: () => disposed.push(hwnd)
    })
  });

  await service.requestSnapshot("300");
  await service.requestSnapshot("301");
  await service.requestSnapshot("302");
  assert.deepEqual(disposed, ["300"], "oldest cached result must be evicted first");
  assert.equal(service.stats().cached, 2);

  service.disposeAll();
  assert.deepEqual(disposed.sort(), ["300", "301", "302"]);
}

(async () => {
  await checkConcurrencyAndCoalescing();
  await checkInvalidationDisposesStaleResult();
  await checkLruOwnership();
  process.stdout.write(JSON.stringify({ ok:true, checks:["concurrency", "coalescing", "stale-dispose", "lru-ownership"] }, null, 2));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
