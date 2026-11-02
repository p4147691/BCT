const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function classify({ text, editor = true, buttons = [], selected = [], pathname = '/' }) {
  const document = {
    body: { innerText: text, textContent: text },
    querySelector: (selector) => editor && selector === '#prompt-textarea' ? {} : null,
    querySelectorAll: (selector) => {
      if (selector === 'button') return buttons.map((textContent) => ({
        textContent,
        getAttribute: () => '',
      }));
      if (selector.includes('[role="tab"]')) return selected.map((textContent) => ({
        textContent,
        getAttribute: () => '',
      }));
      return [];
    },
  };
  const context = vm.createContext({ document, location: { pathname }, console, setTimeout, clearTimeout });
  const source = fs.readFileSync('content/simple_relay_executor.js', 'utf8');
  vm.runInContext(`${source}\nglobalThis.__classify = classifyNewChatSurface;globalThis.__observe = observeConversationSurface;`, context,
    { filename: 'content/simple_relay_executor.js' });
  return JSON.parse(JSON.stringify({ classified: context.__classify(), observed: context.__observe() }));
}

const codex = classify({
  text: '무엇을 만들까요? 작업 위치 환경 선택 승인 요청',
});
assert.equal(codex.classified.kind, 'CODEX_TASK');
assert.equal(codex.observed.kind, 'CODEX');
assert.equal(codex.classified.evidence.hasEditor, true);
assert.deepEqual(codex.classified.evidence.markers, [
  'CODEX_WORKING_DIRECTORY_KO', 'CODEX_ENVIRONMENT_KO', 'CODEX_APPROVAL_KO',
]);

const general = classify({
  text: '새 채팅 대화 검색 무엇을 도와드릴까요?',
});
assert.equal(general.classified.kind, 'GENERAL_CHAT');
assert.equal(general.observed.kind, 'CHAT');
assert.deepEqual(general.classified.evidence.markers, [
  'GENERAL_CHAT_WELCOME', 'GENERAL_CHAT_NAVIGATION',
]);

const currentGeneralHome = classify({
  text: '어디서 시작할까요?',
  buttons: ['임시 채팅'],
});
assert.equal(currentGeneralHome.classified.kind, 'GENERAL_CHAT');
assert.deepEqual(currentGeneralHome.classified.evidence.markers, [
  'GENERAL_CHAT_TEMPORARY', 'GENERAL_CHAT_HOME_ROUTE',
]);

const unknown = classify({ text: '새 채팅', editor: true });
assert.equal(unknown.classified.kind, 'UNKNOWN');
assert.equal(unknown.observed.kind, 'UNKNOWN');
assert.equal(unknown.classified.evidence.hasEditor, true);

const work = classify({ text: '작업 화면', selected: ['Work'] });
assert.equal(work.observed.kind, 'WORK');

console.log('rcc chat surface gate v1: PASS');
