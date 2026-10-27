"use strict";
// Owns only the bottom thumbnail's background pixels/color and their state.
(function installMonitorThumbnailBackgroundLayer(root) {
  function create({contract, visualSource} = {}) {
    if (!contract?.wallpaperSnapshot) throw new TypeError("Thumbnail background requires contract");
    if (!visualSource?.readWallpaper) throw new TypeError("Thumbnail background requires visualSource");
    const states = new WeakMap();

    function resolve(visual, desktopId) {
      const id = contract.normalizeDesktopId(desktopId);
      if (!visual || !contract.isDesktopId(id)) return null;
      if (contract.normalizeDesktopId(visual.dataset?.desktopId) !== id) return null;
      let state = states.get(visual);
      if (!state || state.desktopId !== id) {
        visual.style.backgroundImage = "";
        visual.style.backgroundColor = "";
        state = {
          desktopId:id,
          generation:0,
          status:"unobserved",
          reason:"",
          accepted:false,
          acceptedKind:"",
          acceptedAt:0,
          acceptedSnapshot:null,
          inflight:null,
          forcedDrain:null,
          forceQueued:false
        };
        states.set(visual,state);
      }
      return state;
    }

    function commit(visual, desktopId, snapshot, generation) {
      const state = resolve(visual,desktopId);
      if (!state || (generation != null && state.generation !== generation)) return false;
      if (snapshot.ok && snapshot.kind === "solid") {
        visual.style.backgroundImage = "";
        visual.style.backgroundColor = snapshot.color;
      } else if (snapshot.ok && snapshot.kind === "photo") {
        visual.style.backgroundColor = snapshot.baseColor;
        visual.style.backgroundImage = "url(" + JSON.stringify(snapshot.dataUri) + ")";
      } else if (!state.accepted) {
        visual.style.backgroundImage = "";
        visual.style.backgroundColor = "";
      }
      if (snapshot.ok) {
        state.accepted = true;
        state.acceptedKind = snapshot.kind;
        state.acceptedAt = Date.now();
        state.acceptedSnapshot = snapshot;
      }
      state.status = snapshot.ok ? "captured" : state.accepted ? "retained" : "failed";
      state.reason = snapshot.ok ? "" : snapshot.reason;
      visual.dataset.wallpaperCapture = state.status;
      if (snapshot.ok) {
        visual.dataset.wallpaperSource = snapshot.kind === "solid" ? "native-solid-color" : "native-guid-file";
      } else if (!state.accepted) {
        visual.dataset.wallpaperSource = "none";
      }
      visual.dataset.wallpaperFailureReason = state.reason;
      visual.dataset.wallpaperDesktopId = state.desktopId;
      visual.dataset.wallpaperAcceptedKind = state.acceptedKind;
      visual.dataset.wallpaperAcceptedAt = state.acceptedAt ? String(state.acceptedAt) : "";
      return snapshot.ok;
    }

    function apply(visual, desktopId, reply, generation) {
      return commit(visual,desktopId,contract.wallpaperSnapshot(desktopId,reply),generation);
    }

    function accepted(visual,desktopId) {
      const state=resolve(visual,desktopId);
      return state?.acceptedSnapshot || null;
    }

    function startRead(visual, desktopId, state) {
      const generation = ++state.generation;
      state.status = "pending";
      state.reason = "";
      visual.dataset.wallpaperCapture = "pending";
      visual.dataset.wallpaperFailureReason = "";
      const task = (async () => {
        let reply;
        try { reply = await visualSource.readWallpaper(desktopId); }
        catch (error) { reply = {ok:false,error:String(error?.message || "NATIVE_UNAVAILABLE")}; }
        if (states.get(visual) !== state || generation !== state.generation) return false;
        return apply(visual,desktopId,reply,generation);
      })();
      state.inflight = task;
      void task.then(
        () => { if (state.inflight === task) state.inflight = null; },
        () => { if (state.inflight === task) state.inflight = null; }
      );
      return task;
    }

    function refresh(visual, desktopId, {force = false} = {}) {
      const state = resolve(visual,desktopId);
      if (!state) return Promise.resolve(false);
      // A confirmed image/color is retained until a real Windows change event.
      // A failed read is never frozen permanently; the next normal refresh may retry.
      if (!force && state.status === "captured" && !state.inflight && !state.forcedDrain)
        return Promise.resolve(true);
      if (state.forcedDrain) {
        if (force) state.forceQueued = true;
        return state.forcedDrain;
      }
      if (!state.inflight) return startRead(visual,desktopId,state);
      if (!force) return state.inflight;

      // A real Windows change arriving during a read queues one follow-up read.
      // Repeated events are coalesced; an already valid reply is never discarded
      // merely because another normal render requested the same tile.
      state.forceQueued = true;
      const drain = (async () => {
        let result = await state.inflight.catch(() => false);
        while (states.get(visual) === state && state.forceQueued) {
          state.forceQueued = false;
          result = await startRead(visual,desktopId,state).catch(() => false);
        }
        return result;
      })();
      state.forcedDrain = drain;
      void drain.then(
        () => { if (state.forcedDrain === drain) state.forcedDrain = null; },
        () => { if (state.forcedDrain === drain) state.forcedDrain = null; }
      );
      return drain;
    }

    function invalidate(visual,desktopId) {
      const state = resolve(visual,desktopId);
      if (state) {
        ++state.generation;
        state.forceQueued = false;
      }
    }

    return Object.freeze({resolve,apply,accepted,refresh,invalidate});
  }
  root.MonitorThumbnailBackgroundLayer = Object.freeze({create});
})(globalThis);
