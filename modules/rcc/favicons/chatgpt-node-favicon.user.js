// ==UserScript==
// @name         BCT · ChatGPT 노드 번호 파비콘
// @namespace    https://local.bct/
// @version      0.1.2
// @description  RCC가 검증한 대화 UUID와 N번호를 Chrome 탭 아이콘에 표시(이벤트 기반).
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==

// Based on D:\BCT\data\chatgpt-node-favicon.user.js v0.1.1.
// Staged source only: never install or mutate operating Chrome without supervisor acceptance.
(() => {
  'use strict';
  const API = 'http://127.0.0.1:18790/monitor/state';
  const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
  const NODE = /^N([1-9][0-9]{0,3})$/;
  const ATTR = 'data-bct-node-favicon-v1';
  let lastId = '';
  let lastNode = '';
  let decorated = null;
  let inflight = false;
  let pending = false;
  let queued = false;
  let generation = 0;

  function currentConversation() {
    const match = location.pathname.match(/(?:^|\/)c\/([0-9a-f-]{36})(?:\/|$)/i);
    return match && UUID.test(match[1]) ? match[1].toLowerCase() : '';
  }

  function chooseNode(payload, conversation) {
    if (!conversation || !payload || !payload.rcc || !Array.isArray(payload.rcc.instances)) return '';
    // A known broken RCC projection is not trustworthy, even when it still has stale rows.
    if (payload.rcc.payload && payload.rcc.payload.state !== 'MATCH') return '';
    const matches = [];
    for (const instance of payload.rcc.instances) {
      for (const tab of Array.isArray(instance && instance.tabs) ? instance.tabs : []) {
        if (String(tab.conversation_key || '').toLowerCase() !== conversation) continue;
        const label = String(tab.node_label || '');
        const url = String(tab.url || '');
        // A userscript cannot learn its own Chrome tabId. Refuse duplicate UUID tabs,
        // ambiguous labels, missing exact tab identity, and mismatched URL/registration.
        if (!NODE.test(label) || !Number.isInteger(tab.tab_id) || !Number.isInteger(tab.window_id)
            || tab.presence !== 'OPEN'
            || !new RegExp('^https://chatgpt\\.com/c/' + conversation + '(?:[/?#]|$)', 'i').test(url)) {
          return '';
        }
        matches.push(label);
      }
    }
    return matches.length === 1 ? matches[0] : '';
  }

  function iconPng(node) {
    const match = NODE.exec(node);
    if (!match) return '';
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';
    ctx.fillStyle = '#234060';
    ctx.beginPath();
    ctx.roundRect(1, 1, 62, 62, 12);
    ctx.fill();
    ctx.strokeStyle = '#d9ecff';
    ctx.lineWidth = 2;
    ctx.stroke();
    const digits = match[1];
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 18px Arial, sans-serif';
    ctx.fillText('N', 32, 17);
    ctx.font = 'bold ' + (digits.length >= 4 ? 22 : digits.length === 3 ? 27 : 35) + 'px Arial, sans-serif';
    ctx.fillText(digits, 32, 44);
    try { return canvas.toDataURL('image/png'); }
    catch (_) { return ''; }
  }

  function remove() {
    for (const el of document.querySelectorAll('link[' + ATTR + ']')) el.remove();
    decorated = null;
    lastNode = '';
  }

  function render(node) {
    if (!NODE.test(node)) { remove(); return; }
    if (!document.head) return;
    const icon = iconPng(node);
    if (!icon) { remove(); return; }
    let link = decorated;
    if (!link || !link.isConnected) {
      const own = Array.from(document.querySelectorAll('link[' + ATTR + ']'));
      link = own.shift() || document.createElement('link');
      for (const extra of own) extra.remove();
      link.rel = 'icon';
      link.type = 'image/png';
      link.sizes = '64x64';
      link.setAttribute(ATTR, '');
      decorated = link;
    }
    if (link.href !== icon) link.href = icon;
    if (document.head.lastElementChild !== link) document.head.append(link);
    lastNode = node;
  }

  function requestNode(conversation, done) {
    GM_xmlhttpRequest({
      method: 'GET', url: API, timeout: 3500,
      headers: { Accept: 'application/json' },
      onload: (response) => {
        if (response.status !== 200 || response.responseText.length > 2000000) return done('');
        try { done(chooseNode(JSON.parse(response.responseText), conversation)); }
        catch (_) { done(''); }
      },
      onerror: () => done(''),
      ontimeout: () => done('')
    });
  }

  function refresh() {
    const id = currentConversation();
    if (id !== lastId) {
      lastId = id;
      generation += 1;
      remove();
    }
    if (!id) { pending = false; return; }
    if (inflight) { pending = true; return; }
    inflight = true;
    const thisGeneration = generation;
    requestNode(id, (node) => {
      inflight = false;
      if (thisGeneration === generation && currentConversation() === id) {
        if (node) render(node);
        else remove();
      }
      if (pending || currentConversation() !== id) {
        pending = false;
        scheduleRefresh();
      }
    });
  }

  function scheduleRefresh() {
    if (queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; refresh(); });
  }

  // Restore icon priority if ChatGPT updates <head>; never mutate title or page body.
  if (document.head) {
    const observer = new MutationObserver(() => {
      if (currentConversation() !== lastId) { scheduleRefresh(); return; }
      if (lastNode && decorated && document.head.lastElementChild !== decorated) {
        queueMicrotask(() => { if (lastNode) render(lastNode); });
      }
    });
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
  }
  // Native Chrome Navigation API receives SPA pushState/replaceState/Back transitions.
  if (window.navigation && window.navigation.addEventListener) {
    window.navigation.addEventListener('currententrychange', scheduleRefresh);
  }
  window.addEventListener('popstate', scheduleRefresh);
  window.addEventListener('hashchange', scheduleRefresh);
  window.addEventListener('pageshow', scheduleRefresh);
  window.addEventListener('focus', scheduleRefresh);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) scheduleRefresh();
  });
  // Optional trusted BCT/RCC notifier contract. The event never supplies a label:
  // always revalidate against the Core projection. No timer or roster polling.
  window.addEventListener('bct:conversation-roster-changed', scheduleRefresh);
  refresh();
})();
