// Read-only handoff projection. ACT owns identity/task/role; this module owns no state store.
(() => {
  'use strict';
  const text = value => typeof value === 'string' ? value.trim() : '';
  const items = value => Array.isArray(value) ? value.map(text).filter(Boolean) : [];
  const short = value => text(value).slice(0, 2000);
  const list = value => {
    const values = items(value);
    return values.slice(0, 3).map(v => v.slice(0, 1000)).join(' / ') +
      (values.length > 3 ? ` (외 ${values.length - 3}개; 원본 기록 확인)` : '');
  };
  const freshnessLabel = value => value === 'RECENT' ? '최근 기록' : value === 'AGED' ? '오래된 기록 · 실행 상태 확인 필요' : '기록 시점 미확인 · 실행 상태 확인 필요';
  const executionLabel = execution => {
    const state = text(execution?.state).toUpperCase();
    if (!state || state === 'UNLINKED') return '작업 연결 없음 · 현재 실행 상태 확인 필요';
    if (state === 'MISSING') return '연결된 작업을 찾지 못함 · 현재 실행 상태 확인 필요';
    return `연결된 ACT 작업: ${state}${text(execution?.updated_at) ? ` · 확인 ${short(execution.updated_at)}` : ''}`;
  };
  function summarize(record, target) {
    const key = text(target?.conversation_key);
    const unavailable = reason => ({ state: 'UNAVAILABLE', reason, lines: [
      ['복원 상태', `불가 · ${reason}`], ['대상 채팅', key || '연결 정보 없음'],
      ['대상 수신', '전달/읽기 미확인 — 맥락 복원 완료가 아닙니다.']
    ] });
    if (!key) return unavailable('대상 채팅 연결 없음');
    if (!record || typeof record !== 'object') return unavailable('저장된 작업 기록 없음');
    if (text(record.conversation_key) !== key) return unavailable('다른 채팅의 기록 — 표시/실행 중단');
    if (text(target.project) && text(record.project) !== text(target.project)) {
      return unavailable('프로젝트 연결 충돌 — 표시/실행 중단');
    }
    if (text(target.task_id) && text(record.task_id) !== text(target.task_id)) {
      return unavailable('작업 연결 충돌 — 표시/실행 중단');
    }
    const payload = record.payload || {};
    const freshness = record.freshness || {};
    const execution = record.execution || {};
    const hasFreshness = ['RECENT', 'AGED', 'UNKNOWN'].includes(text(freshness.state).toUpperCase());
    const hasExecution = Boolean(text(execution.state));
    const needsLiveCheck = !hasFreshness || !hasExecution || freshness.requires_live_check === true || execution.requires_live_check === true;
    const missing = [];
    if (!text(record.project)) missing.push('프로젝트');
    if (!text(payload.goal)) missing.push('목표');
    if (!items(payload.decisions).length) missing.push('이전 결정');
    if (!items(payload.completed).length && !items(payload.current_changes).length) missing.push('진행 기록');
    if (!items(payload.next_actions).length) missing.push('다음 행동');
    if (needsLiveCheck) missing.push('현재 실행 상태 확인');
    if (!['IDLE', 'WORKING', 'WAITING', 'BLOCKED', 'COMPLETED'].includes(record.status)) missing.push('진행 상태');
    if (!Number.isInteger(record.revision) || record.revision < 1) missing.push('revision');
    if (!Number.isFinite(Date.parse(record.updated_at))) missing.push('기록 시점');
    const stale = record.validation?.state !== 'CURRENT';
    if (stale) missing.push('최신 작업 연결 검증');
    const reason = missing.length ? `누락/재확인: ${missing.join(', ')}` : '필수 기록 준비됨';
    return { state: missing.length ? 'PARTIAL' : 'RECORD_READY', reason, lines: [
      ['이어갈 작업', `${short(record.project) || '프로젝트 미기록'} / ${short(payload.goal) || '목표 미기록'}`],
      ['이전 결정', list(payload.decisions) || '결정 기록 없음 (결정이 없었다는 뜻은 아님)'],
      ['진행', `${short(record.status) || '상태 미기록'} · 완료: ${list(payload.completed) || '미기록'} · 진행 중: ${list(payload.current_changes) || '미기록'}`],
      ['주의/미검증', [list(payload.warnings), list(payload.unverified)].filter(Boolean).join(' / ') || '기록 없음 (문제 없음으로 검증된 것은 아님)'],
      ['다음', list(payload.next_actions) || '다음 행동 기록 없음'],
      ['근거', `ACT handoff · ${key} · revision ${record.revision ?? '?'} · ${short(record.updated_at) || '시점 미기록'}`],
      ['기록 최신성', freshnessLabel(text(freshness.state).toUpperCase())],
      ['실행 상태', executionLabel(execution)],
      ['복원 상태', `${missing.length ? '일부' : '필수 기록 충분'} · ${reason}`],
      ['검증 한계', stale
        ? list(record.validation?.stale_reasons) || '기록 검증 미확인'
        : needsLiveCheck
          ? '저장된 연결은 확인됐지만 현재 실행 진행/완료 여부는 별도 확인 필요'
          : '저장된 작업 연결과 현재 실행 상태 확인됨'],
      ['대상 수신', '전달/읽기 미확인 — 맥락 복원 완료가 아닙니다.']
    ] };
  }

  async function load(target, fetcher, timeoutMs = 5000) {
    if (!text(target?.conversation_key)) return summarize(null, target);
    const controller = new AbortController();
    let timer;
    try {
      return await Promise.race([
        (async () => {
          const response = await fetcher(`act:/handoff?conversation_key=${encodeURIComponent(target.conversation_key)}`,
            { method: 'GET', cache: 'no-store', signal: controller.signal });
          if (!response?.ok) throw new Error('HTTP');
          const body = await response.json();
          if (body?.ok !== true || !Object.prototype.hasOwnProperty.call(body, 'handoff')) throw new Error('INVALID');
          return summarize(body.handoff, target);
        })(),
        new Promise((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('TIMEOUT')); }, timeoutMs); })
      ]);
    } catch (_) {
      return { state: 'UNAVAILABLE', reason: '조회 실패 또는 시간 초과', lines: [
        ['복원 상태', '불가 · 작업 기록 조회 실패 또는 시간 초과. 기록이 없다고 확인된 것은 아닙니다.'],
        ['대상 수신', '전달/읽기 미확인 — 맥락 복원 완료가 아닙니다.']
      ] };
    } finally { clearTimeout(timer); }
  }

  function createButton({ target, fetcher, openConversation, document: doc = globalThis.document }) {
    // Capture exact identifiers, never the title or a subsequently selected row.
    const selected = Object.freeze({ conversation_key: text(target?.conversation_key),
      project: text(target?.project), task_id: text(target?.task_id) });
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'monitor-node-action monitor-context-continue';
    button.textContent = '이어가기';
    button.title = '이전 결정·진행·다음 행동 확인 (역할 이전/자동 실행 없음)';
    button.disabled = !selected.conversation_key;
    button.addEventListener('click', async event => {
      event.stopPropagation();
      if (button.disabled) return;
      button.disabled = true;
      const dialog = doc.createElement('dialog');
      dialog.className = 'monitor-context-summary';
      dialog.setAttribute('aria-label', '이어가기 복원 요약');
      dialog.style.cssText = 'color:#eee;background:#20242c;border:1px solid #79869c;border-radius:10px;padding:20px;width:min(720px,90vw);max-height:80vh;box-sizing:border-box;display:flex;flex-direction:column;gap:12px;overflow:hidden;overflow-wrap:anywhere;font:14px/1.6 system-ui';
      const heading = doc.createElement('h2'); heading.textContent = '이어가기 · 작업 기록';
      heading.style.cssText = 'flex:0 0 auto;margin:0;font-size:20px';
      const output = doc.createElement('div'); output.setAttribute('role', 'status'); output.textContent = '작업 기록 조회 중…';
      output.className = 'monitor-context-summary-body';
      output.style.cssText = 'flex:1 1 auto;min-height:0;overflow:auto;white-space:pre-wrap;padding-right:8px';
      output.tabIndex = 0;
      const actions = doc.createElement('footer');
      actions.className = 'monitor-context-summary-actions';
      actions.style.cssText = 'flex:0 0 auto;display:flex;flex-wrap:wrap;gap:8px;padding-top:12px;border-top:1px solid #515b6c';
      const close = doc.createElement('button'); close.type = 'button'; close.textContent = '닫기';
      close.addEventListener('click', () => dialog.close());
      dialog.addEventListener('close', () => dialog.remove());
      actions.append(close);
      dialog.append(heading, output, actions); doc.body.append(dialog); dialog.showModal();
      try {
        const summary = await load(selected, fetcher);
        if (!dialog.isConnected) return;
        output.textContent = summary.lines.map(([label, value]) => `${label}: ${value}`).join('\n\n');
        // A missing/conflicting summary cannot authorize opening/execution.
        // The existing separate Recovery action remains available for chat-only recovery.
        if (summary.state !== 'UNAVAILABLE' && typeof openConversation === 'function') {
          const open = doc.createElement('button'); open.type = 'button'; open.textContent = '이전 채팅 열기';
          open.addEventListener('click', async () => {
            if (open.disabled) return;
            open.disabled = true;
            try {
              const result = await openConversation();
              output.textContent += result?.ok === true
                ? '\n\n채팅 상태: 열림 확인 · 대상의 기록 수신/읽기는 여전히 미확인입니다.'
                : '\n\n채팅 상태: 열기 실패 · 요약만 조회됨. 맥락 복원 완료가 아닙니다.';
            } catch (_) { output.textContent += '\n\n채팅 상태: 열기 실패 · 대상 수신 미확인.'; }
            finally { open.disabled = false; }
          });
          actions.append(open);
        }
      } finally { button.disabled = false; }
    });
    return button;
  }
  globalThis.MonitorContextResume = Object.freeze({ summarize, load, createButton });
})();
