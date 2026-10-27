"use strict";
// Declares which independently owned thumbnail layers may render. This keeps
// staged acceptance in the canonical compositor instead of adding a fallback
// renderer or scattering temporary feature flags through the Monitor bundle.
(function installMonitorThumbnailLayerPolicy(root) {
  const MODES = Object.freeze({
    FULL: "full",
    BACKGROUND_ONLY: "background-only",
    BACKGROUND_WINDOWS: "background-windows",
    BACKGROUND_WINDOWS_INTERACTION: "background-windows-interaction",
  });
  const LAYERS = Object.freeze(["background", "windows", "interaction", "semantic", "summary"]);

  function create(requestedMode = MODES.FULL) {
    const mode = requestedMode === MODES.BACKGROUND_ONLY
      ? MODES.BACKGROUND_ONLY
      : requestedMode === MODES.BACKGROUND_WINDOWS
        ? MODES.BACKGROUND_WINDOWS
        : requestedMode === MODES.BACKGROUND_WINDOWS_INTERACTION
          ? MODES.BACKGROUND_WINDOWS_INTERACTION
        : MODES.FULL;
    const enabled = mode === MODES.BACKGROUND_ONLY
      ? ["background"]
      : mode === MODES.BACKGROUND_WINDOWS
        ? ["background", "windows"]
        : mode === MODES.BACKGROUND_WINDOWS_INTERACTION
          ? ["background", "windows", "interaction"]
        : LAYERS;
    return Object.freeze({
      mode,
      allows(layer) {
        return enabled.includes(String(layer || ""));
      },
      enabledLayers: Object.freeze([...enabled]),
    });
  }

  root.MonitorThumbnailLayerPolicy = Object.freeze({MODES, LAYERS, create});
})(globalThis);
