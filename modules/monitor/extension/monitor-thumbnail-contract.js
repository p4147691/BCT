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

  function inheritedWallpaperSnapshot(desktopId, sourceDesktopId, sourceSnapshot, createReply) {
    const id = normalizeDesktopId(desktopId);
    const sourceId = normalizeDesktopId(sourceDesktopId);
    if (!isDesktopId(id) || !isDesktopId(sourceId) || id === sourceId)
      return failure(id,"INVALID_CREATION_LINEAGE");
    if (!createReply || createReply.ok !== true ||
        normalizeDesktopId(createReply.createdDesktopId) !== id ||
        normalizeDesktopId(createReply.sourceDesktopId) !== sourceId)
      return failure(id,"CREATION_LINEAGE_MISMATCH");
    if (!sourceSnapshot?.ok || normalizeDesktopId(sourceSnapshot.desktopId) !== sourceId)
      return failure(id,"SOURCE_WALLPAPER_UNAVAILABLE");
    const inherited = createReply.inheritedWallpaper;
    if (sourceSnapshot.kind === "solid" && inherited?.mode === "solid" &&
        color.test(String(inherited.color || "")) &&
        String(inherited.color).toUpperCase() === String(sourceSnapshot.color).toUpperCase()) {
      return Object.freeze({
        ok:true, desktopId:id, kind:"solid",
        color:String(inherited.color).toUpperCase(),
        proof:String(inherited.proof || "created-desktop-solid-inheritance"),
        inheritedFrom:sourceId
      });
    }
    if (sourceSnapshot.kind === "photo" && inherited?.mode === "photo" &&
        isImage(sourceSnapshot.dataUri) &&
        String(inherited.path || "").trim().toLowerCase() === String(sourceSnapshot.proof || "").trim().toLowerCase()) {
      return Object.freeze({
        ok:true, desktopId:id, kind:"photo", dataUri:String(sourceSnapshot.dataUri),
        proof:String(inherited.path), inheritedFrom:sourceId
      });
    }
    return failure(id,"INHERITED_WALLPAPER_MISMATCH");
  }

  root.MonitorThumbnailContract = Object.freeze({
    normalizeDesktopId, isDesktopId, isImage, wallpaperSnapshot, inheritedWallpaperSnapshot
  });
})(globalThis);
