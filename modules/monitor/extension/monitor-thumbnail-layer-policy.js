"use strict";
// Declares which independently owned thumbnail layers may render. This keeps
// staged acceptance in the canonical compositor instead of adding a fallback
// renderer or scattering temporary feature flags through the Monitor bundle.
(function installMonitorThumbnailLayerPolicy(root) {
  const MODES = Object.freeze({
    FULL: "full",
    BACKGROUND_ONLY: "background-only",
  });
  const LAYERS = Object.freeze(["background", "windows", "semantic", "summary"]);

  function create(requestedMode = MODES.FULL) {
    const mode = requestedMode === MODES.BACKGROUND_ONLY
      ? MODES.BACKGROUND_ONLY
      : MODES.FULL;
    const enabled = mode === MODES.BACKGROUND_ONLY ? ["background"] : LAYERS;
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
