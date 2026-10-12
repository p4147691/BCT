const $ = (id) => document.getElementById(id);
let snapshot = null;

async function call(message) {
  const response = await chrome.runtime.sendMessage(message);
  if (!response?.ok) throw new Error(response?.error || 'Relay request failed');
  return response;
}

function roleForTab(tabId) {
  const regs = snapshot?.registrations || {};
  for (const [role, reg] of Object.entries(regs)) {
    if (reg.tabId === tabId) return role;
  }
  return '';
}

function setStatus(text) {
  $('status').textContent = String(text || '');
}

function renderTabs() {
  const root = $('tabs');
  root.textContent = '';
  for (const tab of snapshot.tabs || []) {
    const row = document.createElement('div');
    row.className = 'tab-row';
    const title = document.createElement('div');
    title.className = 'tab-title';
    title.title = tab.title;
    title.textContent = tab.title || `Tab ${tab.id}`;
    const input = document.createElement('input');
    input.placeholder = 'CONTROL/WS2';
    input.value = roleForTab(tab.id);
    const button = document.createElement('button');
    button.textContent = '등록';
    button.addEventListener('click', async () => {
      try {
        await call({ type: 'relay:register', role: input.value, tabId: tab.id });
        await refresh();
        setStatus(`${input.value.toUpperCase()} 등록 완료`);
      } catch (error) {
        setStatus(`등록 실패: ${error.message}`);
      }
    });
    row.append(title, input, button);
    root.append(row);
  }
}

function renderState() {
  const settings = snapshot.settings || {};
  const badge = $('armedBadge');
  badge.textContent = settings.armed ? `ARMED ${settings.budget}` : 'DISARMED';
  badge.style.background = settings.armed ? '#166534' : '#7f1d1d';
  renderTabs();
  const latest = (snapshot.results || [])[0];
  if (latest) {
    setStatus(`${latest.from}: ${latest.ok ? latest.reply : latest.error}`.slice(0, 1200));
  } else {
    setStatus('등록할 ChatGPT 탭을 선택하세요. CONTROL은 통솔 채팅입니다.');
  }
}
async function refresh() {
  snapshot = await call({ type: 'relay:getState' });
  renderState();
}

$('refreshAll').addEventListener('click', async () => {
  try {
    setStatus('Relay 전체 상태를 다시 맞추는 중...');
    const result = await call({ type: 'relay:forceRefresh' });
    await refresh();
    setStatus(`새로고침 완료 · endpoint ${result.endpointCount} · 등록 ${result.registrationCount}`);
  } catch (error) {
    setStatus(`새로고침 실패: ${error.message}`);
  }
});

$('bootstrap').addEventListener('click', async () => {
  try {
    setStatus('CONTROL 프로토콜을 넣는 중...');
    await call({ type: 'relay:bootstrap' });
    setStatus('CONTROL 프로토콜 설치 완료. 자동중계는 아직 꺼져 있습니다.');
  } catch (error) {
    setStatus(`CONTROL 설정 실패: ${error.message}`);
  }
});

$('arm').addEventListener('click', async () => {
  try {
    await call({ type: 'relay:arm', armed: true, budget: 6 });
    await refresh();
    setStatus('자동중계가 최대 6회로 제한되어 켜졌습니다.');
  } catch (error) {
    setStatus(`ARM 실패: ${error.message}`);
  }
});

$('disarm').addEventListener('click', async () => {
  try {
    await call({ type: 'relay:arm', armed: false, budget: 0 });
    await refresh();
    setStatus('자동중계를 껐습니다.');
  } catch (error) {
    setStatus(`DISARM 실패: ${error.message}`);
  }
});
$('send').addEventListener('click', async () => {
  const to = $('target').value.trim();
  const text = $('message').value.trim();
  if (!to || !text) {
    setStatus('대상 역할과 메시지를 입력하세요.');
    return;
  }
  try {
    setStatus(`${to.toUpperCase()}에 전송 중...`);
    const response = await call({
      type: 'relay:manualSend',
      to,
      text,
      returnToControl: $('returnControl').checked
    });
    setStatus(`전송 접수: ${response.relayId}`);
    setTimeout(() => refresh().catch(() => {}), 1500);
  } catch (error) {
    setStatus(`전송 실패: ${error.message}`);
  }
});

refresh().catch((error) => setStatus(`초기화 실패: ${error.message}`));
