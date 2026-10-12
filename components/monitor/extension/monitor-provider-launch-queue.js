// DesktopWindow Monitor provider launch queue.
// Public boundary: globalThis.MonitorProviderLaunchQueue.
// Owns provider-neutral launch serialization only; endpoint lookup and UI orchestration stay in monitor.js.
// Provider labels here do not define Monitor browser-profile policy; runtime policy lives in MONITOR_STRUCTURE.md.
(() => {
  "use strict";

  const STATE_KEYS = [
    "started", "browserOpened", "endpointReady",
    "sendStarted", "sendConfirmed", "nodeConfirmed", "failed",
  ];

  class MonitorProviderLaunchQueue {
    constructor(options = {}) {
      this.launches = new Map();
      this.open = options.open;
      this.awaitCompletion = options.awaitCompletion;
      this.onChange = options.onChange || (() => {});
      this.onComplete = options.onComplete || (() => {});
      this.createId = options.createId || (() => crypto.randomUUID());
    }

    enqueue(provider = "NAVER") {
      const normalizedProvider = String(provider || "NAVER").toUpperCase();
      const existing = [...this.launches.values()].find((item) => item.provider === normalizedProvider && !item.failed);
      if (existing) return existing;

      const launch = {
        launchId: String(this.createId()), provider: normalizedProvider, started: true,
        browserOpened: false, endpointReady: false, sendStarted: false, sendConfirmed: false,
        nodeConfirmed: false, failed: false, error: "", conversationKey: "", nodeLabel: "",
      };
      this.launches.set(launch.launchId, launch);
      this._emit();
      const previous = this.runChain || Promise.resolve();
      this.runChain = previous.then(() => this._runOne(launch), () => this._runOne(launch));
      return launch;
    }

    update(launchId, patch = {}) {
      const launch = this.launches.get(String(launchId || ""));
      if (!launch) return null;
      for (const key of STATE_KEYS) if (patch[key] === true) launch[key] = true;
      if (patch.conversationKey) launch.conversationKey = String(patch.conversationKey);
      if (patch.nodeLabel) launch.nodeLabel = String(patch.nodeLabel);
      if (patch.error) launch.error = String(patch.error);
      this._emit();
      return launch;
    }

    async _runOne(launch) {
      try {
        const result = await this.open(launch);
        if (!result?.ok || !result?.launched) throw new Error(result?.error || `${launch.provider} ChatGPT 실행 실패`);
        launch.nativeLaunchId = String(result?.launchId || launch.launchId);
        launch.browserOpened = true;
        this._emit();
        await this.awaitCompletion(launch, result);
      } catch (error) {
        launch.failed = true;
        launch.error = error?.message || String(error);
        this._emit();
      }
      this.onComplete(launch);
      this.launches.delete(launch.launchId);
      this._emit();
    }

    _emit() { this.onChange([...this.launches.values()]); }
  }

  globalThis.MonitorProviderLaunchQueue = MonitorProviderLaunchQueue;
})();
