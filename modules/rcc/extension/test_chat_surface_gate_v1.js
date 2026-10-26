const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function classify({ text, editor = true, buttons = [], controls = [] }) {
  const document = {
    body: { innerText: text, textContent: text },
    querySelector: (selector) => editor && selector === '#prompt-textarea' ? {} : null,
    querySelectorAll: (selector) => {
      if (selector === 'button') return buttons.map((textContent) => ({
        textContent,
        getAttribute: () => '',
      }));
      if (selector.includes('[role="checkbox"]')) return controls.map((textContent) => ({
        textContent,
        getAttribute: () => '',
      }));
      return [];
    },
  };
  const context = vm.createContext({ document, console, setTimeout, clearTimeout });
  const source = fs.readFileSync('content/simple_relay_executor.js', 'utf8');
  vm.runInContext(`${source}\nglobalThis.__classify = classifyNewChatSurface;`, context,
    { filename: 'content/simple_relay_executor.js' });
  return JSON.parse(JSON.stringify(context.__classify()));
}

const codex = classify({
  text: '무엇을 만들까요? 작업 위치 환경 선택 승인 요청',
});
assert.equal(codex.kind, 'CODEX_TASK');
assert.equal(codex.evidence.hasEditor, true);
assert.deepEqual(codex.evidence.markers, [
  'CODEX_WORKING_DIRECTORY_KO', 'CODEX_ENVIRONMENT_KO', 'CODEX_APPROVAL_KO',
]);

const general = classify({
  text: '새 채팅 대화 검색 무엇을 도와드릴까요?',
});
assert.equal(general.kind, 'GENERAL_CHAT');
assert.deepEqual(general.evidence.markers, [
  'GENERAL_CHAT_WELCOME', 'GENERAL_CHAT_NAVIGATION',
]);

const currentGeneralHome = classify({
  text: '어디서 시작할까요?',
  buttons: ['임시 채팅'],
  controls: ['작성기 모드', 'Chat', 'Work'],
});
assert.equal(currentGeneralHome.kind, 'GENERAL_CHAT');
assert.deepEqual(currentGeneralHome.evidence.markers, [
  'GENERAL_CHAT_TEMPORARY', 'GENERAL_CHAT_MODE',
]);

const unknown = classify({ text: '새 채팅', editor: true });
assert.equal(unknown.kind, 'UNKNOWN');
assert.equal(unknown.evidence.hasEditor, true);

console.log('rcc chat surface gate v1: PASS');
