(() => {
  if (globalThis.__relayActivityBridgeV6) return;
  globalThis.__relayActivityBridgeV6 = true;
  const generating = [
    'button[data-testid="stop-button"]', 'button[data-testid="stop-generating-button"]',
    'button[aria-label="Stop generating"]', 'button[aria-label="Stop"]',
    '[data-is-streaming="true"]', '.result-streaming'
  ].some(selector => document.querySelector(selector));
  try { chrome.runtime.sendMessage({ type:'relay:activity', generating, url:location.href, telemetry:{generationState:generating?'GENERATING':'IDLE'} }).catch(()=>{}); } catch (_) {}
})();
