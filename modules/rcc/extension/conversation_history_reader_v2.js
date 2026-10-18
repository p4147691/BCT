/* Isolated, read-only older-turn collector. Never submits messages. */
(function (root) {
  "use strict";
  const ID_SELECTOR = "[data-message-id], [data-testid^='conversation-turn-']";
  function identify(el) {
    const raw = el.getAttribute("data-message-id") || el.getAttribute("data-testid") || "";
    return raw.trim();
  }
  function scan(doc) {
    const seen = new Map();
    let duplicates = 0, unidentified = 0;
    for (const el of doc.querySelectorAll(ID_SELECTOR)) {
      const id = identify(el);
      if (!id) { unidentified++; continue; }
      const text = (el.innerText || el.textContent || "").trim();
      if (seen.has(id)) { duplicates++; continue; }
      seen.set(id, { id, text });
    }
    return { messages: [...seen.values()], duplicates, unidentified };
  }
  function scrollContainer(first, doc) {
    let node = first;
    while (node && node !== doc.body) {
      if (node.scrollHeight > node.clientHeight + 8 && node.clientHeight > 0) return node;
      node = node.parentElement;
    }
    return doc.scrollingElement || doc.documentElement;
  }
  async function loadOlder(doc, config = {}) {
    const maxSteps = Math.min(Math.max(config.maxSteps || 15, 1), 40);
    const settle = config.settle || (async () => {});
    const collected = new Map();
    let duplicateObservations = 0, unidentified = 0, stagnant = 0, steps = 0;
    const first = doc.querySelector(ID_SELECTOR);
    if (!first) return { status: "PARTIAL", reason: "NO_IDENTIFIED_TURNS", steps, messages: [], duplicates: 0, unidentified: 0 };
    const container = scrollContainer(first, doc);
    let reason = "STEP_LIMIT";
    for (let step = 0; step < maxSteps; step++) {
      const sample = scan(doc);
      steps++;
      duplicateObservations += sample.duplicates;
      unidentified += sample.unidentified;
      let added = 0;
      for (const row of sample.messages) {
        if (!collected.has(row.id)) { collected.set(row.id, row); added++; }
      }
      const wasAtTop = container.scrollTop <= 0;
      const oldHeight = container.scrollHeight;
      container.scrollTop = Math.max(0, container.scrollTop - Math.max(container.clientHeight, 320));
      await settle();
      if (!added && wasAtTop && container.scrollHeight === oldHeight) stagnant++;
      else stagnant = 0;
      if (stagnant >= 3) { reason = "NO_MORE_VISIBLE_PROGRESS"; break; }
    }
    return {
      status: "PARTIAL",
      reason,
      coverage: "OBSERVED_VISIBLE_TURNS",
      full_history_verified: false,
      steps,
      messages: [...collected.values()],
      duplicates: duplicateObservations,
      unidentified,
      note: "Scroll exhaustion cannot prove the server returned the entire conversation."
    };
  }
  const api = { scan, loadOlder };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BCTConversationHistoryV2 = api;
})(typeof globalThis === "object" ? globalThis : this);
