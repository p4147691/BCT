(() => {
  const SESSION_KEY = "desktopWindowPopupSession";
  const NUMBER_MAP_KEY = "desktopWindowDisplayNumbers.v1";
  const BASE_TITLE = "DesktopWindow Monitor";
  const numberLabel = document.getElementById("desktopNumber");

  let monitorProfileLabel = "G";
  let currentWindowId = null;
  let geometryAdjusted = false;
  let refreshTimer = null;
  let wallpaperRefreshTimer = null;
  let wallpaperImageToken = 0;
  let wallpaperSource = null;
  let lastProjectedStyleSignature = "";
  let lastWindowGeometrySignature = "";

  function normalizeSessions(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    if (Number.isInteger(value.desktopWindowId)) {
      return { [String(value.desktopWindowId)]: value };
    }

    const sessions = {};
    for (const session of Object.values(value)) {
      if (!session || typeof session !== "object" || !Number.isInteger(session.desktopWindowId)) continue;
      sessions[String(session.desktopWindowId)] = session;
    }
    return sessions;
  }

  function readNumberMap() {
    try {
      const parsed = JSON.parse(localStorage.getItem(NUMBER_MAP_KEY) || "{}");
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function allocateDisplayNumbers(sessions) {
    const popupIds = Object.keys(sessions)
      .map(Number)
      .filter(Number.isInteger)
      .sort((a, b) => a - b);
    const liveKeys = new Set(popupIds.map(String));
    const previous = readNumberMap();
    const next = {};
    const used = new Set();

    // Keep a Desktop's existing number for as long as that popup stays alive.
    for (const popupId of popupIds) {
      const key = String(popupId);
      const value = Number(previous[key]);
      if (!liveKeys.has(key) || !Number.isInteger(value) || value < 1 || used.has(value)) continue;
      next[key] = value;
      used.add(value);
    }

    // New Desktops reuse the smallest free number, so 1,2,3 remains compact.
    for (const popupId of popupIds) {
      const key = String(popupId);
      if (Number.isInteger(next[key])) continue;
      let number = 1;
      while (used.has(number)) number += 1;
      next[key] = number;
      used.add(number);
    }

    try {
      localStorage.setItem(NUMBER_MAP_KEY, JSON.stringify(next));
    } catch (_) {
    }
    return { map: next, count: popupIds.length };
  }

  function updateNumberPresentation(displayNumber, _count) {
    if (Number.isInteger(displayNumber) && displayNumber > 0) {
      const label = String(displayNumber);
      const visibleLabel = `${monitorProfileLabel || "G"}${label}`;
      document.title = `${BASE_TITLE} · ${visibleLabel}`;
      if (numberLabel) {
        numberLabel.textContent = visibleLabel;
        numberLabel.hidden = false;
      }
      return;
    }

    document.title = BASE_TITLE;
    if (numberLabel) {
      numberLabel.textContent = "";
      numberLabel.hidden = true;
    }
  }

  function horizontalFrameInset() {
    const frameWidth = Math.max(0, window.outerWidth - window.innerWidth);
    // Chromium popup resize borders on Windows are normally only a few DIPs.
    // Clamp so an unusual page/OS metric can never move the window excessively.
    return Math.max(0, Math.min(8, Math.round(frameWidth / 2)));
  }

  function currentMonitorRect() {
    // Chrome reports screen/window geometry in CSS pixels, so keeping every part of
    // this calculation in CSS pixels also makes it DPI-aware without mixing units.
    return {
      left: Number(screen.availLeft) || 0,
      top: Number(screen.availTop) || 0,
      width: Math.max(1, Number(screen.width) || window.innerWidth || 1),
      height: Math.max(1, Number(screen.height) || window.innerHeight || 1)
    };
  }

  function nativeShellMirrorOwnsWallpaper() {
    return document.body.classList.contains("shell-mirror-active");
  }

  function wallpaperStyleSignature() {
    const style = document.body.style;
    return [
      style.backgroundImage,
      style.backgroundSize,
      style.backgroundPosition,
      style.backgroundRepeat
    ].join("|");
  }

  function parsePixelPair(value) {
    if (typeof value !== "string") return null;
    const match = value.trim().match(/^(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px$/i);
    if (!match) return null;
    const width = Number(match[1]);
    const height = Number(match[2]);
    if (!(width > 0) || !(height > 0)) return null;
    return { width, height };
  }

  function inferWallpaperMode(style) {
    const size = (style.backgroundSize || "").trim().toLowerCase();
    const repeat = (style.backgroundRepeat || "").trim().toLowerCase();

    if (repeat === "repeat") return "tile";
    if (size === "contain") return "fit";
    if (size === "100% 100%") return "stretch";
    if (size === "cover") return "fill";
    if (parsePixelPair(size)) return "center";
    return "fill";
  }

  function scheduleWallpaperProjection(delay = 0) {
    if (nativeShellMirrorOwnsWallpaper()) return;
    if (wallpaperRefreshTimer) clearTimeout(wallpaperRefreshTimer);
    wallpaperRefreshTimer = setTimeout(() => {
      wallpaperRefreshTimer = null;
      captureWallpaperSourceAndProject();
    }, delay);
  }

  function captureWallpaperSourceAndProject() {
    if (nativeShellMirrorOwnsWallpaper()) {
      wallpaperSource = null;
      lastProjectedStyleSignature = "";
      return;
    }

    const style = document.body.style;
    const signature = wallpaperStyleSignature();

    // Ignore the style mutations generated by our own projection. A later refresh
    // from desktop.js restores the Windows-mode style first, which produces a new
    // signature and is captured normally.
    if (signature && signature === lastProjectedStyleSignature) return;

    const image = style.backgroundImage || "";
    if (!image || image === "none" || !image.includes("data:image/jpeg;base64,")) {
      wallpaperSource = null;
      lastProjectedStyleSignature = "";
      return;
    }

    const mode = inferWallpaperMode(style);
    const explicitSize = parsePixelPair(style.backgroundSize);
    const previousNatural = wallpaperSource?.image === image
      ? { width: wallpaperSource.naturalWidth, height: wallpaperSource.naturalHeight }
      : { width: 0, height: 0 };

    wallpaperSource = {
      image,
      mode,
      originalWidth: explicitSize?.width || 0,
      originalHeight: explicitSize?.height || 0,
      naturalWidth: previousNatural.width || 0,
      naturalHeight: previousNatural.height || 0
    };

    if (wallpaperSource.naturalWidth > 0 && wallpaperSource.naturalHeight > 0) {
      projectWallpaperAsFullScreenThumbnail();
      return;
    }

    const token = ++wallpaperImageToken;
    const probe = new Image();
    probe.onload = () => {
      if (token !== wallpaperImageToken || !wallpaperSource || wallpaperSource.image !== image) return;
      wallpaperSource.naturalWidth = probe.naturalWidth || probe.width || 0;
      wallpaperSource.naturalHeight = probe.naturalHeight || probe.height || 0;
      projectWallpaperAsFullScreenThumbnail();
    };
    probe.src = image.slice(5, -2).replace(/\\"/g, '"');
  }

  function setProjectedWallpaper(size, position, repeat) {
    const style = document.body.style;
    if (style.backgroundSize !== size) style.backgroundSize = size;
    if (style.backgroundPosition !== position) style.backgroundPosition = position;
    if (style.backgroundRepeat !== repeat) style.backgroundRepeat = repeat;
    lastProjectedStyleSignature = wallpaperStyleSignature();
  }

  function projectWallpaperAsFullScreenThumbnail() {
    if (nativeShellMirrorOwnsWallpaper() || !wallpaperSource) return;

    const monitor = currentMonitorRect();
    const clientWidth = Math.max(1, window.innerWidth);
    const clientHeight = Math.max(1, window.innerHeight);
    // The Desktop Window is a miniature of the entire Windows wallpaper canvas.
    // First reproduce the Windows wallpaper layout on the full monitor, then scale
    // that finished composition down to this popup's complete client area.
    const scaleX = clientWidth / monitor.width;
    const scaleY = clientHeight / monitor.height;
    const dpr = Math.max(1, Number(window.devicePixelRatio) || 1);
    const mode = wallpaperSource.mode || "fill";

    let sourceWidth = wallpaperSource.naturalWidth;
    let sourceHeight = wallpaperSource.naturalHeight;
    if (mode === "tile" || mode === "center") {
      sourceWidth = wallpaperSource.originalWidth > 0
        ? wallpaperSource.originalWidth / dpr
        : sourceWidth;
      sourceHeight = wallpaperSource.originalHeight > 0
        ? wallpaperSource.originalHeight / dpr
        : sourceHeight;
    }

    if (!(sourceWidth > 0) || !(sourceHeight > 0)) return;

    if (mode === "tile") {
      setProjectedWallpaper(
        `${sourceWidth * scaleX}px ${sourceHeight * scaleY}px`,
        "0px 0px",
        "repeat"
      );
      return;
    }

    let renderedWidth = monitor.width;
    let renderedHeight = monitor.height;
    let imageLeft = 0;
    let imageTop = 0;

    if (mode === "center") {
      renderedWidth = sourceWidth;
      renderedHeight = sourceHeight;
      imageLeft = (monitor.width - renderedWidth) / 2;
      imageTop = (monitor.height - renderedHeight) / 2;
    } else if (mode === "fit") {
      const scale = Math.min(monitor.width / sourceWidth, monitor.height / sourceHeight);
      renderedWidth = sourceWidth * scale;
      renderedHeight = sourceHeight * scale;
      imageLeft = (monitor.width - renderedWidth) / 2;
      imageTop = (monitor.height - renderedHeight) / 2;
    } else if (mode === "stretch") {
      renderedWidth = monitor.width;
      renderedHeight = monitor.height;
    } else {
      // Windows Fill. The finished monitor-sized crop is then reduced as one image,
      // so even a small Desktop Window still contains the complete screen result.
      const scale = Math.max(monitor.width / sourceWidth, monitor.height / sourceHeight);
      renderedWidth = sourceWidth * scale;
      renderedHeight = sourceHeight * scale;
      imageLeft = (monitor.width - renderedWidth) / 2;
      imageTop = (monitor.height - renderedHeight) / 2;
    }

    setProjectedWallpaper(
      `${renderedWidth * scaleX}px ${renderedHeight * scaleY}px`,
      `${imageLeft * scaleX}px ${imageTop * scaleY}px`,
      "no-repeat"
    );
  }

  function windowGeometrySignature() {
    return [
      window.innerWidth,
      window.innerHeight,
      window.outerWidth,
      window.outerHeight,
      screen.availLeft,
      screen.availTop,
      screen.width,
      screen.height,
      window.devicePixelRatio
    ].join("|");
  }

  async function alignPopupToSource(session) {
    const bounds = session?.sourceBounds;
    if (!bounds || ![bounds.left, bounds.top, bounds.width, bounds.height].every(Number.isInteger)) return;
    if (!Number.isInteger(currentWindowId)) return;

    // Let Chrome finish creating the native popup frame before applying the final
    // edge compensation. This is intentionally one-shot so later user moves win.
    await new Promise((resolve) => setTimeout(resolve, 70));

    const inset = horizontalFrameInset();
    // The visible gap reported in practice is only about 1-2 DIPs. Moving the full
    // Windows resize frame off-screen can clip the title-bar icon, so never correct
    // more than two DIPs even when Chromium reports a wider native frame.
    const edgeCompensation = Math.min(2, inset);
    const availLeft = Number(screen.availLeft) || 0;
    const availWidth = Number(screen.availWidth) || 0;
    const availRight = availLeft + availWidth;
    const tolerance = Math.max(2, edgeCompensation + 1);
    const sourceRight = bounds.left + bounds.width;
    const touchesLeft = Math.abs(bounds.left - availLeft) <= tolerance;
    const touchesRight = availWidth > 0 && Math.abs(sourceRight - availRight) <= tolerance;

    const target = {
      left: bounds.left,
      top: bounds.top,
      width: bounds.width,
      height: bounds.height
    };

    // Correct only the tiny visible seam at a monitor edge. Keeping this correction
    // deliberately small preserves the native title-bar icon and resize affordance.
    if (edgeCompensation > 0 && touchesLeft) {
      target.left -= edgeCompensation;
      target.width += edgeCompensation;
    }
    if (edgeCompensation > 0 && touchesRight) {
      target.width += edgeCompensation;
    }

    try {
      await chrome.windows.update(currentWindowId, target);
      setTimeout(() => projectWallpaperAsFullScreenThumbnail(), 80);
    } catch (_) {
    }
  }

  async function refreshDesktopIdentity() {
    try {
      if (!Number.isInteger(currentWindowId)) {
        const current = await chrome.windows.getCurrent();
        currentWindowId = current?.id;
      }
      if (!Number.isInteger(currentWindowId)) return;

      const stored = await chrome.storage.session.get(SESSION_KEY);
      const sessions = normalizeSessions(stored?.[SESSION_KEY]);
      const allocation = allocateDisplayNumbers(sessions);
      const displayNumber = Number(allocation.map[String(currentWindowId)]);
      updateNumberPresentation(displayNumber, allocation.count);

      const session = sessions[String(currentWindowId)];
      if (session && !geometryAdjusted) {
        geometryAdjusted = true;
        alignPopupToSource(session);
      }
    } catch (_) {
      // Cosmetic/window-alignment support must never block the Desktop itself.
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      refreshDesktopIdentity();
    }, 25);
  }

  let closeRequestInFlight = false;

  async function requestDesktopClose(reason) {
    if (closeRequestInFlight) return;
    closeRequestInFlight = true;
    try {
      await chrome.runtime.sendMessage({ type: "desktop-window-close-request", reason });
    } catch (_) {
    } finally {
      // The window normally closes before this matters. Reset only for a failed
      // request so a second key press can retry without reloading the page.
      setTimeout(() => { closeRequestInFlight = false; }, 250);
    }
  }

  window.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    if (document.querySelector(".rename-input")) return;
    const viewer = document.getElementById("textViewer");
    if (viewer && !viewer.hidden) return;

    if (event.key === "Escape") {
      event.preventDefault();
      requestDesktopClose("escape");
    }
  });

  const wallpaperObserver = new MutationObserver(() => {
    if (!nativeShellMirrorOwnsWallpaper()) scheduleWallpaperProjection(20);
  });
  wallpaperObserver.observe(document.body, { attributes: true, attributeFilter: ["style", "class"] });

  const refreshWallpaperProjectionForGeometryChange = () => {
    const signature = windowGeometrySignature();
    if (signature === lastWindowGeometrySignature) return;
    lastWindowGeometrySignature = signature;
    if (!nativeShellMirrorOwnsWallpaper()) projectWallpaperAsFullScreenThumbnail();
  };
  window.addEventListener("resize", refreshWallpaperProjectionForGeometryChange, { passive: true });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "session" && changes[SESSION_KEY]) {
      scheduleRefresh();
      refreshWallpaperProjectionForGeometryChange();
    }
  });

  chrome.windows.onRemoved.addListener(() => scheduleRefresh());
  lastWindowGeometrySignature = windowGeometrySignature();
  refreshDesktopIdentity();
  scheduleWallpaperProjection(40);
})();
