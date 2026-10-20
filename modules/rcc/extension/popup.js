const $ = (id) => document.getElementById(id);
let snapshot = null;

async function readState() {
  const response = await chrome.runtime.sendMessage({ type: 'relay:getState' });
  if (!response?.ok) throw new Error(response?.error || 'RCC state read failed');
  return response;
}

function conversationKey(url) {
  const match = String(url || '').match(/\/c\/([a-f0-9-]{36})(?:[/?#]|$)/i);
  return match ? match[1].toLowerCase() : '';
}

function roleForConversation(key) {
  const binding = snapshot?.simpleRelayV0Binding || {};
  if (key && key === binding.managerConversationKey) return 'MANAGER';
  if (key && key === binding.workerConversationKey) return 'WORKER';
  return 'UNBOUND';
}

function setStatus(text) {
  $('status').textContent = String(text || '');
}

function renderTabs() {
  const root = $('tabs');
  root.textContent = '';
  for (const tab of snapshot?.tabs || []) {
    const key = conversationKey(tab.url);
    const row = document.createElement('div');
    row.className = 'tab-row';

    const title = document.createElement('div');
    title.className = 'tab-title';
    title.title = tab.title || '';
    title.textContent = tab.title || `Tab ${tab.id}`;

    const meta = document.createElement('div');
    meta.className = 'tab-meta';
    meta.textContent = `${roleForConversation(key)} · ${key || 'UUID 없음'} · Tab ${tab.id}`;

    row.append(title, meta);
    root.append(row);
  }
  if (!root.childElementCount) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '열린 ChatGPT 대화가 없습니다.';
    root.append(empty);
  }
}

async function refresh() {
  snapshot = await readState();
  renderTabs();
  const binding = snapshot.simpleRelayV0Binding;
  const bound = binding?.managerConversationKey && binding?.workerConversationKey;
  setStatus(`열린 대화 ${snapshot.tabs.length}개 · Simple Relay ${bound ? '연결됨' : '미연결'}\n조작 기능은 BCT Control에서 수행합니다.`);
}

$('refresh').addEventListener('click', () => {
  setStatus('다시 조회 중...');
  refresh().catch((error) => setStatus(`조회 실패: ${error.message}`));
});

refresh().catch((error) => setStatus(`초기 조회 실패: ${error.message}`));
