(() => {
  "use strict";

  const DEFAULT_MAX_CONCURRENT = 2;
  const DEFAULT_MAX_ENTRIES = 12;
  const DEFAULT_MAX_WIDTH = 480;
  const DEFAULT_MAX_HEIGHT = 270;

  function clampInteger(value, fallback, min, max) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, Math.trunc(parsed)));
  }

  function normalizeHwnd(hwnd) {
    const key = String(hwnd ?? "").trim();
    if (!/^\d+$/.test(key) || key === "0") return "";
    return key;
  }

  function normalizeCaptureResult(result) {
    if (result == null) return null;
    if (typeof result === "object" && Object.prototype.hasOwnProperty.call(result, "value")) {
      return {
        value: result.value,
        dispose: typeof result.dispose === "function" ? result.dispose : null,
        meta: result.meta && typeof result.meta === "object" ? result.meta : null
      };
    }
    return { value: result, dispose: null, meta: null };
  }

  function safeDispose(entry, counters) {
    if (!entry) return;
    if (typeof entry.dispose === "function") {
      try { entry.dispose(); }
      catch (_) {}
    }
    counters.disposedResults += 1;
  }

  function createMonitorThumbnailService(options = {}) {
    if (typeof options.capture !== "function") {
      throw new TypeError("ThumbnailService requires a capture adapter");
    }

    const capture = options.capture;
    const maxConcurrent = clampInteger(
      options.maxConcurrent,
      DEFAULT_MAX_CONCURRENT,
      1,
      4
    );
    const maxEntries = clampInteger(
      options.maxEntries,
      DEFAULT_MAX_ENTRIES,
      1,
      64
    );
    const maxWidth = clampInteger(
      options.maxWidth,
      DEFAULT_MAX_WIDTH,
      64,
      1920
    );
    const maxHeight = clampInteger(
      options.maxHeight,
      DEFAULT_MAX_HEIGHT,
      64,
      1080
    );

    const queue = [];
    const states = new Map();
    const cache = new Map();

    let activeCount = 0;
    let shutdown = false;
    let nextJobId = 1;

    const counters = {
      requested: 0,
      cacheHits: 0,
      coalesced: 0,
      queued: 0,
      started: 0,
      completed: 0,
      failed: 0,
      staleDiscarded: 0,
      evicted: 0,
      disposedResults: 0,
      maxObservedActive: 0
    };

    function stateFor(key) {
      let state = states.get(key);
      if (!state) {
        state = {
          generation: 1,
          active: null,
          queued: null
        };
        states.set(key, state);
      }
      return state;
    }

    function removeCached(key) {
      const entry = cache.get(key);
      if (!entry) return false;
      cache.delete(key);
      safeDispose(entry, counters);
      return true;
    }

    function remember(key, generation, captured) {
      removeCached(key);
      cache.set(key, {
        generation,
        value: captured.value,
        dispose: captured.dispose,
        meta: captured.meta
      });

      while (cache.size > maxEntries) {
        const oldestKey = cache.keys().next().value;
        if (!oldestKey) break;
        const oldest = cache.get(oldestKey);
        cache.delete(oldestKey);
        safeDispose(oldest, counters);
        counters.evicted += 1;
      }
    }

    function settleJob(job, outcome, error = null) {
      const state = states.get(job.key);
      if (state?.active === job) state.active = null;
      if (state?.queued === job) state.queued = null;

      if (error) {
        counters.failed += 1;
        job.reject(error);
      } else {
        job.resolve(outcome);
      }
    }

    async function runJob(job) {
      activeCount += 1;
      counters.started += 1;
      counters.maxObservedActive = Math.max(
        counters.maxObservedActive,
        activeCount
      );

      const state = states.get(job.key);
      if (state) {
        if (state.queued === job) state.queued = null;
        state.active = job;
      }

      try {
        const raw = await capture({
          hwnd: job.key,
          reason: job.reason,
          generation: job.generation,
          maxWidth,
          maxHeight
        });
        const captured = normalizeCaptureResult(raw);

        if (!captured) {
          counters.completed += 1;
          settleJob(job, null);
          return;
        }

        const latest = states.get(job.key);
        if (
          shutdown ||
          !latest ||
          latest.generation !== job.generation
        ) {
          safeDispose(captured, counters);
          counters.staleDiscarded += 1;
          settleJob(job, null);
          return;
        }

        remember(job.key, job.generation, captured);
        counters.completed += 1;
        settleJob(job, {
          hwnd: job.key,
          generation: job.generation,
          value: captured.value,
          meta: captured.meta,
          fromCache: false
        });
      } catch (error) {
        settleJob(job, null, error);
      } finally {
        activeCount = Math.max(0, activeCount - 1);
        drain();
      }
    }

    function drain() {
      if (shutdown) return;
      while (activeCount < maxConcurrent && queue.length) {
        const job = queue.shift();
        if (!job) continue;

        const state = states.get(job.key);
        if (!state || state.generation !== job.generation) {
          if (state?.queued === job) state.queued = null;
          counters.staleDiscarded += 1;
          job.resolve(null);
          continue;
        }

        void runJob(job);
      }
    }

    function requestSnapshot(hwnd, reason = "event") {
      if (shutdown) {
        return Promise.reject(new Error("ThumbnailService is disposed"));
      }

      const key = normalizeHwnd(hwnd);
      if (!key) {
        return Promise.reject(new TypeError("Invalid HWND"));
      }

      counters.requested += 1;
      const state = stateFor(key);
      const cached = cache.get(key);

      if (cached?.generation === state.generation) {
        cache.delete(key);
        cache.set(key, cached);
        counters.cacheHits += 1;
        return Promise.resolve({
          hwnd: key,
          generation: state.generation,
          value: cached.value,
          meta: cached.meta,
          fromCache: true
        });
      }

      if (state.active?.generation === state.generation) {
        counters.coalesced += 1;
        return state.active.promise;
      }

      if (state.queued?.generation === state.generation) {
        counters.coalesced += 1;
        return state.queued.promise;
      }

      let resolve;
      let reject;
      const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
      });

      const job = {
        id: nextJobId++,
        key,
        reason: String(reason || "event"),
        generation: state.generation,
        promise,
        resolve,
        reject
      };

      state.queued = job;
      queue.push(job);
      counters.queued += 1;
      drain();
      return promise;
    }

    function invalidate(hwnd) {
      const key = normalizeHwnd(hwnd);
      if (!key) return false;
      const state = stateFor(key);
      state.generation += 1;
      return removeCached(key);
    }

    function dispose(hwnd) {
      const key = normalizeHwnd(hwnd);
      if (!key) return false;
      const state = stateFor(key);
      state.generation += 1;
      state.queued = null;
      removeCached(key);
      return true;
    }

    function getCached(hwnd) {
      const key = normalizeHwnd(hwnd);
      if (!key) return null;
      const state = states.get(key);
      const entry = cache.get(key);
      if (!state || !entry || entry.generation !== state.generation) {
        return null;
      }
      return {
        hwnd: key,
        generation: entry.generation,
        value: entry.value,
        meta: entry.meta,
        fromCache: true
      };
    }

    function disposeAll() {
      if (shutdown) return;
      shutdown = true;

      for (const job of queue.splice(0)) {
        job.resolve(null);
      }

      for (const entry of cache.values()) {
        safeDispose(entry, counters);
      }
      cache.clear();

      for (const state of states.values()) {
        state.generation += 1;
        state.queued = null;
      }
    }

    function stats() {
      return Object.freeze({
        ...counters,
        active: activeCount,
        queuedNow: queue.length,
        cached: cache.size,
        trackedWindows: states.size,
        maxConcurrent,
        maxEntries,
        maxWidth,
        maxHeight,
        shutdown
      });
    }

    return Object.freeze({
      requestSnapshot,
      invalidate,
      dispose,
      disposeAll,
      getCached,
      stats
    });
  }

  globalThis.MonitorThumbnailService = Object.freeze({
    create: createMonitorThumbnailService
  });
})();
