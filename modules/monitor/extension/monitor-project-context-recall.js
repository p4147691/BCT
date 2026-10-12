// Read-only project-scoped work recall. ACT retains all identity and role authority.
(() => {
  'use strict';
  const text = value => typeof value === 'string' ? value.trim() : '';
  const project = value => text(value).slice(0, 240);
  const unavailable = reason => ({ state: 'UNAVAILABLE', reason, records: [] });
  async function load(projectName, fetcher, timeoutMs = 5000) {
    const exactProject = project(projectName);
    if (!exactProject) return unavailable('프로젝트 이름을 입력하세요.');
    const controller = new AbortController(); let timer;
    try {
      return await Promise.race([
        (async () => {
          const response = await fetcher(`act:/handoffs?project=${encodeURIComponent(exactProject)}&limit=8`, { method: 'GET', cache: 'no-store', signal: controller.signal });
          if (!response?.ok) throw new Error('HTTP');
          const body = await response.json();
          if (body?.ok !== true || text(body.project) !== exactProject || !Array.isArray(body.handoffs)) throw new Error('INVALID');
          const records = body.handoffs.filter(row => row && typeof row === 'object' && text(row.project) === exactProject && text(row.conversation_key));
          if (records.length !== body.handoffs.length) throw new Error('PROJECT_MISMATCH');
          return { state: records.length ? 'READY' : 'EMPTY', project: exactProject, records };
        })(),
        new Promise((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('TIMEOUT')); }, timeoutMs); })
      ]);
    } catch (_) { return unavailable('조회 실패 또는 시간 초과. 기록이 없다고 확인된 것은 아닙니다.'); }
    finally { clearTimeout(timer); }
  }
  function detail(record, exactProject) {
    const target = { conversation_key: text(record?.conversation_key), project: exactProject };
    return globalThis.MonitorContextResume?.summarize(record, target) || { state: 'UNAVAILABLE', lines: [['복원 상태', '요약 모듈을 사용할 수 없습니다.']] };
  }
  function createButton({ fetcher, openConversation, document: doc = globalThis.document }) {
    const button = doc.createElement('button'); button.type = 'button'; button.className = 'monitor-provider-launch monitor-project-context-recall';
    button.textContent = '내 작업'; button.title = '프로젝트별 저장 작업 기록 찾기 (역할 이전/자동 실행 없음)';
    button.addEventListener('click', event => {
      event.stopPropagation();
      const dialog = doc.createElement('dialog'); dialog.className = 'monitor-context-summary monitor-project-context-dialog'; dialog.setAttribute('aria-label', '프로젝트별 작업 기록 찾기');
      dialog.style.cssText = 'color:#eee;background:#20242c;border:1px solid #79869c;border-radius:10px;padding:20px;width:min(720px,90vw);max-height:80vh;box-sizing:border-box;display:flex;flex-direction:column;gap:12px;overflow:hidden;overflow-wrap:anywhere;font:14px/1.6 system-ui';
      const heading = doc.createElement('h2'); heading.textContent = '내가 하던 일'; heading.style.cssText = 'flex:0 0 auto;margin:0;font-size:20px';
      const form = doc.createElement('form'); form.style.cssText = 'display:flex;gap:8px;flex:0 0 auto';
      const input = doc.createElement('input'); input.type = 'text'; input.maxLength = 240; input.placeholder = '정확한 프로젝트 이름'; input.autocomplete = 'off'; input.style.cssText = 'flex:1;min-width:0';
      const search = doc.createElement('button'); search.type = 'submit'; search.textContent = '찾기'; form.append(input, search);
      const output = doc.createElement('div'); output.className = 'monitor-context-summary-body'; output.setAttribute('role', 'status'); output.tabIndex = 0; output.style.cssText = 'flex:1 1 auto;min-height:0;overflow:auto;white-space:pre-wrap;padding-right:8px'; output.textContent = '프로젝트 이름을 입력하면 해당 프로젝트의 저장된 작업 기록만 조회합니다.';
      const actions = doc.createElement('footer'); actions.style.cssText = 'flex:0 0 auto;display:flex;flex-wrap:wrap;gap:8px;padding-top:12px;border-top:1px solid #515b6c';
      const close = doc.createElement('button'); close.type = 'button'; close.textContent = '닫기'; close.addEventListener('click', () => dialog.close()); actions.append(close);
      dialog.addEventListener('close', () => dialog.remove()); dialog.append(heading, form, output, actions); doc.body.append(dialog); dialog.showModal(); input.focus?.();
      form.addEventListener('submit', async submit => {
        submit.preventDefault(); const exactProject = project(input.value);
        if (!exactProject) { output.textContent = '프로젝트 이름을 입력하세요.'; return; }
        search.disabled = true; output.textContent = '작업 기록 조회 중…'; const result = await load(exactProject, fetcher);
        if (!dialog.isConnected) return;
        if (result.state === 'UNAVAILABLE') { output.textContent = `조회 상태: ${result.reason}`; search.disabled = false; return; }
        if (result.state === 'EMPTY') { output.textContent = `조회 상태: ${exactProject}에 저장된 작업 기록이 없습니다.`; search.disabled = false; return; }
        output.textContent = '';
        for (const record of result.records) {
          const row = doc.createElement('section'); row.style.cssText = 'border-bottom:1px solid #515b6c;padding:8px 0'; const summary = detail(record, exactProject);
          const title = doc.createElement('strong'); title.textContent = `${record.status || '상태 미기록'} · ${record.conversation_key}`;
          const body = doc.createElement('div'); body.textContent = summary.lines.map(([label, value]) => `${label}: ${value}`).join('\n\n');
          const open = doc.createElement('button'); open.type = 'button'; open.textContent = '이전 채팅 열기'; open.disabled = summary.state === 'UNAVAILABLE' || typeof openConversation !== 'function';
          open.addEventListener('click', async () => { if (open.disabled) return; open.disabled = true; try { const opened = await openConversation({ conversation_key: text(record.conversation_key), project: exactProject }); body.textContent += opened?.ok === true ? '\n\n채팅 상태: 열림 확인 · 대상 수신/읽기는 미확인입니다.' : '\n\n채팅 상태: 열기 실패 · 맥락 복원 완료가 아닙니다.'; } catch (_) { body.textContent += '\n\n채팅 상태: 열기 실패 · 대상 수신 미확인.'; } finally { open.disabled = false; } });
          row.append(title, body, open); output.append(row);
        }
        search.disabled = false;
      });
    });
    return button;
  }
  globalThis.MonitorProjectContextRecall = Object.freeze({ load, createButton });
})();
