/*@@MONITOR_FUNCTION:monitorNativeWithTimeout@@*/

/*@@MONITOR_FUNCTION:approveMonitorNodeChatChange@@*/

/*@@MONITOR_FUNCTION:restoreMonitorNodeChatChange@@*/

/*@@MONITOR_FUNCTION:restoreMonitorAllRecovery@@*/

/*@@MONITOR_FUNCTION:restoreMonitorRebootSnapshot@@*/

/*@@MONITOR_FUNCTION:createMonitorContextContinueButton@@*/

/*@@MONITOR_FUNCTION:createMonitorWorkRecoveryButton@@*/

/*@@MONITOR_FUNCTION:restoreMonitorDetachedTask@@*/

let monitorCoreNativePort = null;

const monitorCoreNativePending = [];

/*@@MONITOR_FUNCTION:ensureMonitorCoreNativePort@@*/

/*@@MONITOR_FUNCTION:monitorCoreNative@@*/

/*@@MONITOR_FUNCTION:monitorCoreNativeRequest@@*/

let monitorWallpaperToken = 0;

const monitorWallpaperCache = new Map();
const monitorWallpaperActuals = new Map();

// Substitution wallpaper map removed.

const MONITOR_WALLPAPER_CACHE_MS = 15000;

const MONITOR_WALLPAPER_CACHE_LIMIT = 3;

const MONITOR_WALLPAPER_ACTUAL_LIMIT = 8;
const MONITOR_WALLPAPER_MAX_WIDTH = 960;
const MONITOR_WALLPAPER_MAX_HEIGHT = 600;
// Wallpaper pixels are bounded and cached separately. Individual window captures
// stay disabled until decoded-image ownership in the native capture path is fixed.
const MONITOR_PIXEL_VISUALS_ENABLED = true;
// Per-window pixels use the isolated one-frame WGC helper. Native capture is
// bounded to two concurrent requests and the helper exits after each snapshot.
const MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED = true;

/*@@MONITOR_FUNCTION:monitorRememberWallpaperEntry@@*/

/*@@MONITOR_FUNCTION:monitorLightweightWallpaperDataUri@@*/

const monitorFrameCache = new Map();

const monitorFrameInflight = new Map();

let monitorFrameGeneration = 0;
const monitorFrameDesktopGenerations = new Map();

/*@@MONITOR_FUNCTION:monitorDesktopFrameGeneration@@*/

const MONITOR_FRAME_CACHE_LIMIT = 4;
const MONITOR_DESKTOP_FRAME_CACHE_MAX_AGE_MS = 15000;
const MONITOR_WINDOW_CAPTURE_MAX_AGE_MS = 30000;
/*@@MONITOR_FUNCTION:monitorCaptureMatchesCurrentWindow@@*/

/*@@MONITOR_FUNCTION:monitorRevokeThumbWindowCaptureSource@@*/

if (!globalThis.MonitorThumbnailService?.create) {
  throw new Error("MonitorThumbnailService module is not loaded");
}

// Profiles intentionally have separate caches (thumbnail, preview and frozen),
// but they all consume the same WGC/native capture resource.  A single gate
// prevents a mixed-profile refresh from turning three per-profile limits into
// six simultaneous native captures.
const monitorCaptureScheduler = (() => {
  // One WGC snapshot at a time keeps desktop interaction responsive. Refresh
  // queues remain coalesced by HWND, so this trades a little thumbnail latency
  // for a bounded CPU/GPU burst rather than dropping a requested frame.
  const maxConcurrent = 1;
  const queue = [];
  let active = 0;
  let maxObservedActive = 0;

  const drain = () => {
    while (active < maxConcurrent && queue.length) {
      const next = queue.shift();
      if (!next) continue;
      active += 1;
      maxObservedActive = Math.max(maxObservedActive, active);
      Promise.resolve()
        .then(next.task)
        .then(next.resolve, next.reject)
        .finally(() => {
          active = Math.max(0, active - 1);
          drain();
        });
    }
  };

  return Object.freeze({
    run(task) {
      return new Promise((resolve, reject) => {
        queue.push({ task, resolve, reject });
        drain();
      });
    },
    stats() {
      return Object.freeze({ maxConcurrent, active, queued: queue.length, maxObservedActive });
    }
  });
})();

/*@@MONITOR_FUNCTION:createMonitorWindowCaptureService@@*/

const monitorThumbnailCaptureServices = Object.freeze({
  thumb: createMonitorWindowCaptureService({ maxEntries: 12, maxWidth: 480, maxHeight: 270, quality: 52 }),
  preview: createMonitorWindowCaptureService({ maxEntries: 6, maxWidth: 960, maxHeight: 540, quality: 68 }),
  frozen: createMonitorWindowCaptureService({ maxEntries: 32, maxWidth: 960, maxHeight: 540, quality: 68 })
});

/*@@MONITOR_FUNCTION:monitorWindowCaptureService@@*/

const monitorThumbnailService = Object.freeze({
  async requestSnapshot(hwnd, reason = "unspecified", profile = "thumb") {
    monitorRenderDiagnostics.captureRequests += 1;
    const key = String(hwnd || "").trim();
    if (!key || !MONITOR_WINDOW_PIXEL_CAPTURE_ENABLED) return "";
    const item = monitorWindowDesktopLocations.get(key);
    if (monitorWindowUsesFrozenCapture(item)) {
      const shared = String(item?.frozenDataUri || "");
      if (shared.startsWith("data:image/")) return shared;
    }
    const captureProfile = monitorWindowUsesFrozenCapture(item) ? "frozen" : profile;
    const service = monitorWindowCaptureService(captureProfile);
    const cached = service.getCached(key);
    if(cached&&!monitorCaptureMatchesCurrentWindow(cached.meta?.captureTitle,item?.title,cached.meta?.capturedAt))service.invalidate(key);
    const result = await service.requestSnapshot(key, reason).catch(() => null);
    return String(result?.value || "");
  },
  invalidate(hwnd) {
    const key = String(hwnd || "").trim();
    if (monitorWindowUsesFrozenCapture(monitorWindowDesktopLocations.get(key))) return false;
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.invalidate(key) || changed;
    return changed;
  },
  dispose(hwnd) {
    let changed = false;
    for (const service of Object.values(monitorThumbnailCaptureServices)) changed = service.dispose(hwnd) || changed;
    return changed;
  },
  disposeAll() {
    for (const service of Object.values(monitorThumbnailCaptureServices)) service.disposeAll();
  },
  stats() {
    const profiles = Object.fromEntries(Object.entries(monitorThumbnailCaptureServices).map(([name, service]) => [name, service.stats()]));
    const totals = Object.values(profiles).reduce((sum, profile) => {
      for (const key of ["requested", "cacheHits", "coalesced", "queued", "started", "completed", "failed", "staleDiscarded", "evicted", "disposedResults", "active", "queuedNow", "cached", "trackedWindows"]) sum[key] = Number(sum[key] || 0) + Number(profile[key] || 0);
      sum.maxObservedActive = Math.max(Number(sum.maxObservedActive || 0), Number(profile.maxObservedActive || 0));
      return sum;
    }, {});
    return { ...totals, profiles, nativeCapture: monitorCaptureScheduler.stats() };
  }
});

window.addEventListener("pagehide", () => {
  stopMonitorBctNativePreview();
  monitorThumbnailService.disposeAll();
}, { once:true });

/*@@MONITOR_FUNCTION:monitorGetWindowCapture@@*/

let monitorOwnFrozenCaptureHwnd = "";
let monitorOwnFrozenCaptureAttemptedHwnd = "";
let monitorOwnFrozenCaptureBusy = false;

/*@@MONITOR_FUNCTION:ensureMonitorOwnFrozenSnapshot@@*/


let monitorCurrentWallpaperCaptureBusy = false;

/*@@MONITOR_FUNCTION:ensureMonitorCurrentWallpaperSnapshot@@*/

let monitorThumbBatchGeneration = 0;

let monitorThumbBatchInflight = null;

/*@@MONITOR_FUNCTION:monitorCapturePaused@@*/

/*@@MONITOR_FUNCTION:monitorIsActiveDesktopRenderer@@*/

/*@@MONITOR_FUNCTION:getObservedWallpaper@@*/

/*@@MONITOR_FUNCTION:applyObservedWallpaper@@*/

/*@@MONITOR_FUNCTION:monitorActDesktopVisualForDesktop@@*/

/*@@MONITOR_FUNCTION:monitorWindowUsesFrozenCapture@@*/

/*@@MONITOR_FUNCTION:monitorWindowCanRefreshPixels@@*/

/*@@MONITOR_FUNCTION:monitorShouldKeepExistingCapture@@*/

/*@@MONITOR_FUNCTION:monitorChooseCaptureView@@*/

/*@@MONITOR_FUNCTION:monitorWindowFallbackDataUri@@*/

/*@@MONITOR_FUNCTION:captureDesktopFrame@@*/

/*@@MONITOR_FUNCTION:syncMonitorPauseOverlay@@*/

/*@@MONITOR_FUNCTION:monitorAgeIdentityForWorkerGroup@@*/

/*@@MONITOR_FUNCTION:monitorAgeIdentityForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorObservedDesktopForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorActNodeNumbersForHwnd@@*/

/*@@MONITOR_FUNCTION:monitorBadgeNodeNumbersForHwnd@@*/

/*@@MONITOR_FUNCTION:syncMonitorDesktopNumberBadge@@*/

/*@@MONITOR_FUNCTION:syncMonitorNonChatCountdown@@*/

/*@@MONITOR_FUNCTION:syncMonitorStatusLayer@@*/

/*@@MONITOR_FUNCTION:reconcileFrame@@*/
