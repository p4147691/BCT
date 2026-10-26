"use strict";
// Pure thumbnail boundary. It validates identities and converts Native replies
// into the only two background values the renderer accepts: photo or solid.
(function installMonitorThumbnailContract(root) {
  const guid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const image = /^data:image\/(?:jpeg|png|webp);base64,/i;
  const color = /^#[0-9a-f]{6}$/i;
  const normalizeDesktopId = value => String(value || "").trim().toLowerCase();
  const isDesktopId = value => guid.test(String(value || ""));
  const isImage = value => typeof value === "string" && image.test(value);

  function failure(desktopId, reason) {
    return Object.freeze({
      ok:false,
      desktopId:normalizeDesktopId(desktopId),
      kind:"none",
      reason:String(reason || "INVALID_WALLPAPER_REPLY")
    });
  }

  function wallpaperSnapshot(desktopId, reply) {
    const id = normalizeDesktopId(desktopId);
    if (!isDesktopId(id)) return failure(id, "INVALID_DESKTOP_ID");
    if (!reply || reply.ok !== true) return failure(id, reply?.error || "NATIVE_WALLPAPER_UNAVAILABLE");
    if (normalizeDesktopId(reply.desktopId) !== id) return failure(id, "DESKTOP_ID_MISMATCH");
    const wallpaper = reply.wallpaper;
    if (wallpaper?.mode === "solid" && color.test(String(wallpaper.color || ""))) {
      return Object.freeze({
        ok:true, desktopId:id, kind:"solid",
        color:String(wallpaper.color).toUpperCase(),
        proof:String(wallpaper.proof || "")
      });
    }
    if (isImage(wallpaper?.dataUri)) {
      return Object.freeze({
        ok:true, desktopId:id, kind:"photo",
        dataUri:String(wallpaper.dataUri),
        proof:String(reply.wallpaperPath || "native-guid-file")
      });
    }
    return failure(id, "WALLPAPER_PIXELS_MISSING");
  }

  root.MonitorThumbnailContract = Object.freeze({
    normalizeDesktopId, isDesktopId, isImage, wallpaperSnapshot
  });
})(globalThis);
