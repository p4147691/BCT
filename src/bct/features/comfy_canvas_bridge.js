/* BCT ComfyUI canvas bridge: fixed read-only request; no mutations. */
export function readComfyCanvas({ origin = location.origin, app = window.app } = {}) {
  if (origin !== "http://127.0.0.1:8188") throw Error("COMFY_ORIGIN_FORBIDDEN");
  const graph = app?.graph;
  if (!graph || typeof graph.serialize !== "function") throw Error("COMFY_LIVE_GRAPH_UNAVAILABLE");
  const snapshot = graph.serialize();
  if (!snapshot || !Array.isArray(snapshot.nodes) || !Array.isArray(snapshot.links))
    throw Error("COMFY_GRAPH_INVALID");
  return { source: "live_canvas_memory", url: origin + "/", graph: structuredClone(snapshot) };
}
