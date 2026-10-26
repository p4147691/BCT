"use strict";
// The thumbnail module knows this interface, never Chrome Native Messaging.
// The host application injects its one canonical correlated transport.
(function installMonitorDesktopVisualSource(root) {
  function create({request, maxWidth = 960, maxHeight = 600, quality = 68} = {}) {
    if (typeof request !== "function") throw new TypeError("DesktopVisualSource requires request(message)");
    async function readWallpaper(desktopId) {
      return await request({
        type:"getDesktopVisualSnapshot",
        desktopId:String(desktopId || ""),
        maxWidth:Number(maxWidth),
        maxHeight:Number(maxHeight),
        quality:Number(quality)
      });
    }
    return Object.freeze({readWallpaper});
  }
  root.MonitorDesktopVisualSource = Object.freeze({create});
})(globalThis);
