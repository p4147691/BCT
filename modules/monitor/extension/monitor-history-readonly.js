// Optional, read-only Monitor history panel adapter.
// No auto-load, no Core endpoint, no RCC calls and no node authority.
(() => {
  'use strict';
  const SCHEMA = 'BCT_MONITOR_HISTORY_VIEW_V1';
  const text = value => typeof value === 'string' ? value : '';
  const safeRows = value => Array.isArray(value) ? value.slice(0, 100) : [];
  function model(payload) {
    if (!payload || payload.schema !== SCHEMA || payload.snapshot_only !== true ||
        payload.source !== 'IMMUTABLE_SQLITE_SNAPSHOT' ||
        !Array.isArray(payload.current?.nodes) || !Array.isArray(payload.history?.nodes) ||
        !Array.isArray(payload.history?.works) || !Array.isArray(payload.history?.projects)) {
      return {state: 'UNAVAILABLE', reason: '검증된 이력 스냅샷을 조회할 수 없습니다.'};
    }
    if (payload.conversation_coverage === 'FULL' && payload.full_history_verified !== true) {
      return {state: 'UNAVAILABLE', reason: '대화 원문 커버리지 증거가 일치하지 않습니다.'};
    }
    return {
      state: 'READY',
      current: safeRows(payload.current.nodes),
      historyNodes: safeRows(payload.history.nodes),
      works: safeRows(payload.history.works),
      projects: safeRows(payload.history.projects),
      truncated: ['current', 'history'].some(section => {
        const s = payload[section]; return Object.values(s).some(Array.isArray) &&
          Object.values(s).some(rows => Array.isArray(rows) && rows.length > 100);
      }),
      coverage: payload.full_history_verified === true && payload.conversation_coverage === 'FULL'
        ? 'FULL' : text(payload.conversation_coverage) || 'NOT_VERIFIED',
    };
  }
  function mount({document: doc, loadSnapshot}) {
    if (!doc || typeof loadSnapshot !== 'function') throw new TypeError('DEPENDENCIES_REQUIRED');
    let mode = 'current', generation = 0, disposed = false, last = null;
    const root = doc.createElement('section');
    root.className = 'monitor-history-readonly';
    root.setAttribute('aria-label', 'BCT 노드 및 과거 기록');
    const controls = doc.createElement('div');
    const current = doc.createElement('button');
    const past = doc.createElement('button');
    for (const b of [current, past]) b.type = 'button';
    current.textContent = '현재 노드';
    past.textContent = '과거 기록';
    controls.append(current, past);
    const output = doc.createElement('div');
    output.setAttribute('role', 'status');
    root.append(controls, output);
    function line(value) {
      const el = doc.createElement('p');
      el.textContent = String(value);
      output.appendChild(el);
    }
    function render() {
      output.textContent = '';
      current.setAttribute('aria-pressed', String(mode === 'current'));
      past.setAttribute('aria-pressed', String(mode === 'history'));
      if (!last) { line('조회 버튼을 선택하면 보존된 스냅샷만 읽습니다.'); return; }
      if (last.state === 'LOADING') { line('기록 조회 중…'); return; }
      if (last.state !== 'READY') { line(last.reason || '조회 불가 (기록 부재로 확정하지 않음)'); return; }
      if (mode === 'current') {
        line('현재 등록 노드 (온라인·업무 가능 여부는 별도 검증 필요)');
        if (!last.current.length) line('등록 노드 조회 결과 없음');
        for (const n of last.current) line(`${text(n.node_id)} · ${text(n.name)} · 연결/배정 상태: 미검증`);
      } else {
        line('과거 프로젝트·노드 기록 (원문 커버리지: ' + last.coverage + ')');
        if (!last.historyNodes.length && !last.works.length && !last.projects.length)
          line('스냅샷에 조회 가능한 과거 기록 없음 (전체 과거가 없다는 뜻은 아님)');
        for (const n of last.historyNodes) line(`참여 노드 ${text(n.node_id)} · 세션 ${Number(n.session_count) || 0}건 · 과거 이름/역할: 미확정`);
        for (const w of last.works) line(`Work ${text(w.work_id)} · 세션 ${Number(w.session_count) || 0}건 · Operation ${Number(w.operation_count) || 0}건`);
        for (const p of last.projects) line(`프로젝트 ${text(p.project_id)} · 대화 ${safeRows(p.conversation_keys).length}건 (Work 연계: 미검증)`);
      }
      if (last.truncated) line('표시 제한: 일부 항목만 표시됨');
    }
    async function refresh(nextMode = mode) {
      mode = nextMode === 'history' ? 'history' : 'current';
      const currentGeneration = ++generation;
      last = {state: 'LOADING'}; render();
      try {
        const response = model(await loadSnapshot());
        if (!disposed && currentGeneration === generation) { last = response; render(); }
      } catch (_) {
        if (!disposed && currentGeneration === generation) {
          last = {state: 'UNAVAILABLE', reason: '조회 실패. 기록이 없다고 판단하지 않습니다.'}; render();
        }
      }
    }
    current.addEventListener('click', () => refresh('current'));
    past.addEventListener('click', () => refresh('history'));
    render();
    return {element: root, refresh, dispose() { disposed = true; ++generation; root.remove(); }};
  }
  const api = Object.freeze({model, mount});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else if (typeof globalThis !== 'undefined') globalThis.MonitorHistoryReadonly = api;
})();
