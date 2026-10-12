(() => {
  if (globalThis.__ACT_NATURAL_ROLE_BRIDGE_V1__) return;
  globalThis.__ACT_NATURAL_ROLE_BRIDGE_V1__ = true;

  let last = { text: '', at: 0 };
  const candidate = /(오케스트레이터|코디네이터\s*[12]?|일반\s*워커|워커로\s*돌아가|일꾼|특수\s*역할|역할\s*내려놔)/;

  function editor() {
    return document.querySelector('#prompt-textarea, textarea[data-id="root"], div[contenteditable="true"][data-virtualkeyboard="true"], div[contenteditable="true"]');
  }

  function textNow() {
    const el = editor();
    return String(el?.tagName === 'TEXTAREA' ? el.value : (el?.innerText || el?.textContent || '')).trim();
  }

  function dispatchCandidate() {
    const text = textNow();
    if (!text || text.length > 500 || !candidate.test(text)) return;
    const now = Date.now();
    if (last.text === text && now - last.at < 2000) return;
    last = { text, at: now };
    chrome.runtime.sendMessage({ type: 'relay:actNaturalCommand', text }).catch(() => {});
  }
  document.addEventListener('keydown', (event) => {
    if (!event.isComposing && event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
      const el = editor();
      if (el && (event.target === el || el.contains(event.target))) dispatchCandidate();
    }
  }, true);

  document.addEventListener('click', (event) => {
    if (event.target?.closest?.('button[data-testid="send-button"], form button[type="submit"]')) dispatchCandidate();
  }, true);

  document.addEventListener('submit', () => dispatchCandidate(), true);
  globalThis.__RCC_RELAY_RECEIVER_READY__ = true;
})();
