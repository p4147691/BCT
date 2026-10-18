/* Isolated, read-only older-turn collector. Never submits messages. */
(function (root) {
  "use strict";
  const ID_SELECTOR = "[data-turn-key], [data-content-search-turn-key], [data-message-id], [data-testid^='conversation-turn-']";
  const ANONYMOUS_SELECTOR = "[data-message-author-role], [data-content-search-unit-key], [data-chatgpt-search-unit-key], [data-testid='conversation-turn']";
  // Reuse the RCC turn identity priority: keyed conversation turns win over
  // generic message or test selectors, so nested DOM wrappers cannot split a turn.
  function identify(el) {
    for (const attr of ["data-turn-key", "data-content-search-turn-key", "data-message-id"]) {
      const value = el.getAttribute(attr);
      if (typeof value === "string" && value.trim()) return value.trim();
    }
    const testid = el.getAttribute("data-testid");
    return typeof testid === "string" && /^conversation-turn-.+/.test(testid) ? testid.trim() : "";
  }
  function canonicalTurn(node) {
    const keyedParent = typeof node.closest === "function" ? node.closest("[data-turn-key]") : null;
    if (keyedParent) return keyedParent;
    const keyedChildren = typeof node.querySelectorAll === "function"
      ? node.querySelectorAll("[data-turn-key]") : [];
    return keyedChildren.length === 1 ? keyedChildren[0] : node;
  }
  function conversationId(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:" || !["chatgpt.com", "chat.openai.com"].includes(parsed.hostname)) return null;
      const match = parsed.pathname.match(/^\/(?:g\/[A-Za-z0-9_-]+\/)?c\/([a-f0-9-]{36})\/?$/i);
      return match ? match[1].toLowerCase() : null;
    } catch (_) { return null; }
  }
  function scan(doc) {
    const seen = new Map();
    let duplicates = 0, unidentified = 0;
    for (const candidate of doc.querySelectorAll(ID_SELECTOR)) {
      const el = canonicalTurn(candidate);
      const id = identify(el);
      if (!id) { unidentified++; continue; }
      const text = (el.innerText || el.textContent || "").trim();
      if (seen.has(id)) { duplicates++; continue; }
      seen.set(id, { id, text });
    }
    // Candidate messages without a reliable turn ID cannot be treated as captured.
    // Exclude nested author nodes already covered by an identified ancestor/child.
    for (const el of doc.querySelectorAll(ANONYMOUS_SELECTOR)) {
      if (identify(el)) continue;
      if (typeof el.closest === "function" && el.closest(ID_SELECTOR)) continue;
      if (typeof el.querySelector === "function" && el.querySelector(ID_SELECTOR)) continue;
      unidentified++;
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
    let duplicatesInSamples = 0, reobserved = 0, conflictingTexts = 0;
    let unidentified = 0, stagnant = 0, steps = 0;
    const expected = config.expectedConversationUrl ? conversationId(config.expectedConversationUrl) : null;
    const result = (reason) => ({
      status: "PARTIAL", reason, coverage: "OBSERVED_VISIBLE_TURNS",
      full_history_verified: false, steps, messages: [...collected.values()],
      duplicates: duplicatesInSamples + reobserved, duplicatesInSamples,
      reobserved, conflictingTexts, unidentified,
      gaps_verifiable: false,
      note: "Observed turn IDs cannot prove that every older or virtualized turn loaded."
    });
    if (config.expectedConversationUrl && !expected) return result("EXPECTED_IDENTITY_INVALID");
    const currentIdentity = () => doc.location?.href ? conversationId(doc.location.href) : null;
    if (expected && currentIdentity() !== expected) return result("CONVERSATION_ID_MISMATCH");
    const first = doc.querySelector(ID_SELECTOR);
    const observe = () => {
      const sample = scan(doc);
      duplicatesInSamples += sample.duplicates;
      unidentified += sample.unidentified;
      let added = 0;
      for (const row of sample.messages) {
        if (collected.has(row.id)) {
          reobserved++;
          if (collected.get(row.id).text !== row.text) conflictingTexts++;
        } else {
          collected.set(row.id, row);
          added++;
        }
      }
      return added;
    };
    if (!first) {
      observe();
      return result("NO_IDENTIFIED_TURNS");
    }
    const container = scrollContainer(first, doc);
    observe(); // Initial screen. Scroll-triggered screens are observed separately.
    let reason = "STEP_LIMIT";
    for (let step = 0; step < maxSteps; step++) {
      if (expected && currentIdentity() !== expected) { reason = "CONVERSATION_ID_CHANGED"; break; }
      const wasAtTop = container.scrollTop <= 0;
      const oldHeight = container.scrollHeight;
      container.scrollTop = Math.max(0, container.scrollTop - Math.max(container.clientHeight, 320));
      await settle();
      if (expected && currentIdentity() !== expected) { reason = "CONVERSATION_ID_CHANGED"; break; }
      steps++;
      const added = observe(); // Including the FINAL scroll; no dropped last page.
      const stillAtTop = container.scrollTop <= 0;
      if (added === 0 && wasAtTop && stillAtTop && oldHeight === container.scrollHeight) stagnant++;
      else stagnant = 0;
      if (stagnant >= 3) { reason = "NO_MORE_VISIBLE_PROGRESS"; break; }
    }
    return result(reason);
  }
  const api = { scan, loadOlder, conversationId };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.BCTConversationHistoryV2 = api;
})(typeof globalThis === "object" ? globalThis : this);
