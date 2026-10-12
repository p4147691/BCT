// Read-only recovery workboard. ACT remains the sole authority for work state.
(() => {
  'use strict';
  const CARD_LIMIT = 50;
  const SCOPES = new Set(['PROJECT', 'CROSS_PROJECT', 'SYSTEM', 'UNASSIGNED']);
  const text = value => typeof value === 'string' ? value.trim() : '';
  const items = value => Array.isArray(value) ? value.map(text).filter(Boolean) : [];
  const clip = (value, limit = 1000) => text(value).slice(0, limit);
  async function timed(timeoutMs, work) {
    const controller = new AbortController(); let timer;
    try { return await Promise.race([work(controller.signal), new Promise((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(Error('TIMEOUT')); }, timeoutMs); })]); }
    finally { clearTimeout(timer); }
  }
  function validCard(card) {
    if (!card || typeof card !== 'object' || !SCOPES.has(text(card.scope)) || !Number.isFinite(Date.parse(card.updated_at))) return false;
    if (text(card.source).toUpperCase() === 'ACT_TASK') return !text(card.conversation_key) && !text(card.project) && text(card.task_id) && card.handoff_available === false;
    return text(card.conversation_key) && Number.isInteger(card.revision) && card.revision > 0;
  }
  async function loadCards(fetcher, timeoutMs = 5000) {
    try { return await timed(timeoutMs, async signal => {
      const response = await fetcher(`act:/work-recovery?limit=${CARD_LIMIT}`, { method: 'GET', cache: 'no-store', signal });
      if (!response?.ok) throw Error('HTTP'); const body = await response.json();
      if (body?.ok !== true || !Array.isArray(body.cards) || body.cards.length > CARD_LIMIT || !body.cards.every(validCard)) throw Error('SCHEMA');
      return { state: body.cards.length ? 'READY' : 'EMPTY', cards: body.cards };
    }); } catch (_) { return { state: 'UNAVAILABLE', reason: '최신 작업 대장을 조회하지 못했습니다. 기록이 없다고 확인된 것은 아닙니다.', cards: [] }; }
  }
  async function loadRecord(card, fetcher, timeoutMs = 5000) {
    try { return await timed(timeoutMs, async signal => {
      const response = await fetcher(`act:/handoff?conversation_key=${encodeURIComponent(card.conversation_key)}`, { method: 'GET', cache: 'no-store', signal });
      if (!response?.ok) throw Error('HTTP'); const body = await response.json(); const record = body?.handoff;
      if (body?.ok !== true || !record || text(record.conversation_key) !== text(card.conversation_key) || text(record.project) !== text(card.project)) throw Error('MISMATCH');
      return { state: 'READY', record };
    }); } catch (_) { return { state: 'UNAVAILABLE', reason: '선택한 작업의 최신 인수인계 기록을 조회하지 못했습니다.' }; }
  }
  function summary(record, card) {
    const target = { conversation_key: text(card?.conversation_key), project: text(card?.project), task_id: text(card?.task_id) };
    return globalThis.MonitorContextResume?.summarize(record, target) || { state: 'UNAVAILABLE', reason: '요약 모듈을 사용할 수 없습니다.', lines: [] };
  }
  function section(scope) { return scope === 'SYSTEM' ? '시스템 작업' : scope === 'CROSS_PROJECT' ? '여러 프로젝트 공통 작업' : '프로젝트 작업'; }
  function recoveryBucket(card) { const validation = text(card?.validation?.state).toUpperCase(); const status = text(card?.status).toUpperCase(); if (text(card?.source).toUpperCase() === 'ACT_TASK') return card?.execution?.requires_live_check === true ? 'RECHECK' : 'CURRENT'; if (validation !== 'CURRENT') return 'RECHECK'; if (card?.freshness?.requires_live_check === true || card?.execution?.requires_live_check === true) return 'RECHECK'; return status === 'COMPLETED' ? 'COMPLETED' : 'CURRENT'; }
  function recoveryBucketLabel(bucket) { return bucket === 'CURRENT' ? '현재 작업' : bucket === 'COMPLETED' ? '최근 완료 기록' : '과거 기록 · 재확인 필요'; }
  function itemBlock(label, value) {
    const values = items(value); if (!values.length) return `${label}: 미기록`;
    const lines = values.slice(0, 8).map(entry => `- ${clip(entry)}`); if (values.length > lines.length) lines.push(`- 추가 ${values.length - lines.length}개는 원본 기록에서 확인 필요`);
    return `${label}:\n${lines.join('\n')}`;
  }
  function handoffText(record, card) {
    const state = summary(record, card); if (state.state === 'UNAVAILABLE') return '';
    const payload = record.payload || {}; const reasons = items(record.validation?.stale_reasons); const needsLiveCheck = record.freshness?.requires_live_check === true || record.execution?.requires_live_check === true; const recipientWarning = text(record.validation?.state).toUpperCase() !== 'CURRENT' || needsLiveCheck ? '수신 시 유의: 이 기록은 현재 작업으로 이어갈 수 없는 과거·재확인 기록입니다. 배경 확인용으로만 사용하고 현재 상태를 새로 확인하세요.' : text(record.status).toUpperCase() === 'COMPLETED' ? '수신 시 유의: 이 기록은 마지막 확인 시점에 완료된 기록입니다. 새 작업으로 재개하기 전에 현재 상태와 새 요청을 확인하세요.' : '';
    return ['[작업 인수인계 — ACT 최신 저장 기록]', `구분: ${section(card.scope)}`, `프로젝트: ${clip(record.project) || '미기록'}`, `관련 프로젝트: ${items(payload.related_projects).join(', ') || '미기록'}`, `작업 ID: ${clip(record.task_id) || '미기록'}`, `마지막 작업자/역할: ${clip(record.role) || '미기록'}`, `진행 상태: ${clip(record.status) || '미기록'} · 위험: ${clip(record.risk) || '미기록'}`, `마지막 확인: ${clip(record.updated_at) || '미기록'} · revision ${record.revision ?? '미기록'}`, `연결 검증: ${clip(record.validation?.state) || '미확인'}${reasons.length ? ` (${reasons.join(', ')})` : ''}`, `기록 최신성: ${clip(record.freshness?.state) || '미확인'}${record.freshness?.requires_live_check === true ? ' · 현재 실행 상태 확인 필요' : ''}`, `실행 상태: ${clip(record.execution?.state) || '미확인'}${record.execution?.requires_live_check === true ? ' · 현재 실행 상태 확인 필요' : ''}`, `복원 판정: ${state.state} · ${state.reason}`, recipientWarning, '', `목표: ${clip(payload.goal) || '미기록'}`, itemBlock('완료 확인', payload.completed), itemBlock('진행 중', payload.current_changes), itemBlock('이전 결정', payload.decisions), itemBlock('주의/미검증', [...items(payload.warnings), ...items(payload.unverified)]), itemBlock('다음 행동', payload.next_actions), '', '새 채팅 처리 원칙: 이 기록은 확인된 배경과 다음 행동입니다. 누락·오래됨·미검증 항목을 완료 사실로 간주하지 말고, 변경 또는 실행 전에 현재 상태를 다시 확인하세요.', '', '새 채팅 첫 응답 규칙: 필요한 안전·식별 확인이 있더라도, 사용자가 보게 되는 첫 답변에서는 코드 변경·명령 실행·광범위한 상태 복구보다 먼저 아래를 짧게 보여주세요.', '- 인수인계를 받았다는 확인', '- 이어받은 작업: 위 목표와 진행 중 항목을 한두 문장으로 요약', '- 마지막으로 확인된 상태와 미검증/누락 항목', '- 지금 확인할 다음 행동', '이 첫 요약 뒤에만 해당 프로젝트의 현재 코드와 관련된 최근 검증 결과를 필요한 범위에서 확인하세요. 이 기록만으로 다른 프로젝트·노드·전역 작업을 추정하거나 완료로 선언하지 마세요.'].filter(Boolean).join('\n');
  }
  function taskText(card) {
    const execution = card?.execution || {}; const needsLiveCheck = execution.requires_live_check === true;
    return ['[작업 인수인계 — ACT 작업 대장]', '구분: 프로젝트 미지정 ACT 작업', `작업 ID: ${clip(card?.task_id) || '미기록'}`, `작업 제목: ${clip(card?.title) || '미기록'}`, `담당자/실행자: ${clip(card?.role) || '미기록'}`, `진행 상태: ${clip(card?.status) || '미기록'} · 위험: ${clip(card?.risk) || '미기록'}`, `마지막 확인: ${clip(card?.updated_at) || '미기록'}`, `실행 상태: ${clip(execution.state) || '미확인'}${needsLiveCheck ? ' · 현재 실행 상태 확인 필요' : ''}`, `lease: ${clip(execution.lease_owner) || '미확인'}${execution.lease_expires_at ? ` · ${clip(execution.lease_expires_at)}` : ''}`, '', '주의: 이 카드는 ACT 작업 대장에만 있는 작업입니다. 연결된 이전 채팅·프로젝트 인수인계는 없으므로 새 채팅에서 현재 ACT 상태를 먼저 확인하고, 프로젝트나 역할을 추정하지 마세요.', '새 채팅 첫 응답 규칙: 인수인계 수신, 현재 작업 상태, 연결된 채팅/프로젝트가 미기록이라는 점, 다음 확인 행동을 짧게 먼저 보여주세요.'].join('\n');
  }
  function taskDetail(card) {
    const execution = card?.execution || {};
    return [['기록 종류', 'ACT 작업 대장 (연결된 채팅 인수인계 없음)'], ['작업', `${clip(card?.title) || '제목 미기록'} / ${clip(card?.task_id) || 'ID 미기록'}`], ['상태', `${clip(card?.status) || '미기록'} · 위험 ${clip(card?.risk) || '미기록'}`], ['담당자/실행자', clip(card?.role) || '미기록'], ['실행', `${clip(execution.state) || '미확인'}${execution.requires_live_check === true ? ' · 현재 상태 재확인 필요' : ''}`], ['lease', `${clip(execution.lease_owner) || '미확인'}${execution.lease_expires_at ? ` · ${clip(execution.lease_expires_at)}` : ''}`], ['확인 시점', clip(card?.updated_at) || '미기록'], ['주의', '프로젝트·이전 채팅·맥락은 미기록입니다. 이 항목만으로 역할이나 작업 맥락을 추정하지 마세요.']];
  }
  async function copy(value, clipboard = globalThis.navigator?.clipboard) { if (!value || typeof clipboard?.writeText !== 'function') return false; try { await clipboard.writeText(value); return true; } catch (_) { return false; } }
  function createButton({ fetcher, openConversation, clipboard, document: doc = globalThis.document }) {
    const button = doc.createElement('button'); button.type = 'button'; button.className = 'monitor-provider-launch monitor-work-recovery'; button.textContent = '프로젝트·작업'; button.title = '최신 저장 작업 대장과 새 채팅용 인수인계를 엽니다';
    button.addEventListener('click', event => {
      event.stopPropagation(); const dialog = doc.createElement('dialog'); dialog.className = 'monitor-context-summary monitor-work-recovery-dialog'; dialog.setAttribute('aria-label', '프로젝트와 작업'); dialog.style.cssText = 'color:#eee;background:#20242c;border:1px solid #79869c;border-radius:10px;padding:20px;width:min(760px,90vw);max-height:80vh;box-sizing:border-box;display:flex;flex-direction:column;gap:12px;overflow:hidden;overflow-wrap:anywhere;font:14px/1.6 system-ui';
      const heading = doc.createElement('h2'); heading.textContent = '프로젝트·작업'; heading.style.cssText = 'flex:0 0 auto;margin:0;font-size:20px';
      const note = doc.createElement('p'); note.textContent = 'ACT에 마지막으로 확인·저장된 작업을 표시합니다. 인수인계 복사는 저장된 작업 요약을 클립보드에 담습니다. 새 채팅에 붙여넣으세요. 이전 채팅 열기는 원래 대화를 여는 별도 기능이며 기록을 자동 전송하거나 작업을 재개하지 않습니다.'; note.style.cssText = 'flex:0 0 auto;margin:0';
      const output = doc.createElement('div'); output.setAttribute('role', 'status'); output.tabIndex = 0; output.className = 'monitor-context-summary-body'; output.style.cssText = 'flex:1 1 auto;min-height:0;overflow:auto;white-space:pre-wrap;padding-right:8px';
      const header = doc.createElement('header'); header.style.cssText = 'flex:0 0 auto;display:flex;align-items:center;flex-wrap:wrap;gap:8px';
      const navigation = doc.createElement('nav'); navigation.setAttribute('aria-label', '작업 화면 이동'); navigation.style.cssText = 'margin-left:auto;display:flex;justify-content:flex-end;flex-wrap:wrap;gap:8px';
      const actions = doc.createElement('footer'); actions.style.cssText = 'flex:0 0 auto;display:flex;justify-content:flex-end;flex-wrap:wrap;gap:8px;padding-top:12px;border-top:1px solid #515b6c'; const refresh = doc.createElement('button'); refresh.type = 'button'; refresh.textContent = '새로고침'; const close = doc.createElement('button'); close.type = 'button'; close.textContent = '닫기'; close.addEventListener('click', () => dialog.close()); navigation.append(refresh, close); dialog.addEventListener('close', () => dialog.remove()); dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }); header.append(heading, navigation); dialog.append(header, note, output, actions); doc.body.append(dialog); dialog.showModal();
      const detailActions = []; const clearDetailActions = () => { while (detailActions.length) detailActions.pop().remove(); };
      let selectedCard = null;
      let viewGeneration = 0;
      let refreshCards;
      const addBackToWorkboard = () => {
        const back = doc.createElement('button'); back.type = 'button'; back.textContent = '작업 목록으로'; back.title = '프로젝트·작업 목록으로 돌아갑니다.';
        back.addEventListener('click', () => { selectedCard = null; void refreshCards(); });
        navigation.prepend(back); detailActions.push(back);
      };
      const showDetail = async card => {
        const generation = ++viewGeneration; const isCurrent = () => dialog.isConnected && generation === viewGeneration;
        selectedCard = card; clearDetailActions(); addBackToWorkboard();
        if (text(card?.source).toUpperCase() === 'ACT_TASK') { const needsLiveCheck = card?.execution?.requires_live_check === true; output.textContent = taskDetail(card).map(([label, value]) => `${label}: ${value}`).join('\n\n'); if (needsLiveCheck) output.textContent += '\n\n주의: 이 작업은 현재 실행 상태 재확인이 필요합니다. 과거 기록만으로 재개하지 마세요.'; const copyButton = doc.createElement('button'); copyButton.type = 'button'; copyButton.textContent = needsLiveCheck ? '참고용 작업 요약 복사' : '작업 요약 복사'; copyButton.title = needsLiveCheck ? '현재 상태를 재확인해야 하는 작업의 참고용 요약을 복사합니다. 작업을 재개하거나 소유권을 바꾸지 않습니다.' : '연결된 채팅이 없는 ACT 작업의 안전한 요약을 복사합니다.'; copyButton.addEventListener('click', async () => { copyButton.disabled = true; const copied = await copy(taskText(card), clipboard); if (isCurrent()) output.textContent += copied ? '\n\n인수인계 상태: 클립보드에 복사됨 · 연결된 채팅/프로젝트는 새 채팅에서 추정하지 마세요.' : '\n\n인수인계 상태: 클립보드 복사 실패'; copyButton.disabled = false; }); actions.prepend(copyButton); detailActions.push(copyButton); return; }
        output.textContent = '선택한 작업의 최신 인수인계 기록 조회 중…'; const loaded = await loadRecord(card, fetcher); if (!isCurrent()) return; if (loaded.state === 'UNAVAILABLE') { output.textContent = `조회 상태: ${loaded.reason}`; return; }
        const state = summary(loaded.record, card); output.textContent = state.lines.map(([label, value]) => `${label}: ${value}`).join('\n\n'); const validation = text(loaded.record.validation?.state).toUpperCase(); const needsLiveCheck = loaded.record.freshness?.requires_live_check === true || loaded.record.execution?.requires_live_check === true; const completed = text(loaded.record.status).toUpperCase() === 'COMPLETED'; const referenceOnly = validation !== 'CURRENT' || needsLiveCheck; if (referenceOnly) output.textContent += '\n\n주의: 이 기록은 현재 작업으로 이어갈 수 없는 과거·재확인 기록입니다. 현재 상태를 확인한 뒤에만 참고하세요.'; else if (completed) output.textContent += '\n\n안내: 이 기록은 마지막 확인 시점에 완료된 기록입니다. 새 작업으로 재개하기 전에 현재 상태와 새 요청을 확인하세요.'; const copyButton = doc.createElement('button'); copyButton.type = 'button'; copyButton.textContent = referenceOnly ? '참고용 인수인계 복사' : '인수인계 복사'; copyButton.title = referenceOnly ? '현재 작업을 재개하지 않는 참고용 인수인계를 복사합니다. 붙여넣은 새 채팅에서 현재 상태를 다시 확인해야 합니다.' : '새 채팅에 이어갈 인수인계를 복사합니다.'; copyButton.disabled = state.state === 'UNAVAILABLE'; copyButton.addEventListener('click', async () => { if (copyButton.disabled) return; copyButton.disabled = true; const copied = await copy(handoffText(loaded.record, card), clipboard); if (isCurrent()) output.textContent += copied ? '\n\n인수인계 상태: 클립보드에 복사됨 · 새 채팅이 읽고 이해했는지는 붙여넣은 뒤 확인하세요.' : '\n\n인수인계 상태: 클립보드 복사 실패'; copyButton.disabled = false; }); actions.prepend(copyButton); detailActions.push(copyButton);
        if (typeof openConversation === 'function') { const openTarget = { ...card, profile_id: text(loaded.record.profile_id) || text(card.profile_id) }; const open = doc.createElement('button'); open.type = 'button'; open.textContent = '이전 채팅 열기'; open.title = '기록과 일치하는 Chrome 프로필에서 이전 대화를 엽니다. 열기만 하며 작업·역할·소유권은 바꾸지 않습니다.'; open.disabled = state.state === 'UNAVAILABLE'; open.addEventListener('click', async () => { if (open.disabled) return; open.disabled = true; output.textContent += '\n\n채팅 상태: 이전 채팅을 여는 중…'; try { const opened = await openConversation(openTarget); if (!isCurrent()) return; output.textContent += opened?.ok === true ? `\n\n채팅 상태: 열림 확인 · ${opened.status === 'ALREADY_OPEN' ? '이미 열린 대화를 확인했습니다. 해당 Chrome 탭을 선택하세요(자동 화면 전환은 하지 않습니다).' : '등록된 Chrome 프로필에 이전 대화를 열었습니다.'} 대상의 기록 수신/읽기는 미확인입니다.` : `\n\n채팅 상태: 열기 실패 · ${text(opened?.error) || '복구 대상 정보를 확인할 수 없습니다.'}\n안내: 해당 대화가 열려 있지 않으면 ACT에 저장된 Chrome 프로필이 정확히 하나여야 합니다. 프로필이 없거나 여러 개면 목록의 해당 노드에서 이어가기/복구를 사용하세요.`; } catch (_) { if (isCurrent()) output.textContent += '\n\n채팅 상태: 열기 실패 · 연결 또는 Native Host 응답을 확인하세요. 작업 상태는 바뀌지 않았습니다.'; } finally { open.disabled = false; } }); actions.prepend(open); detailActions.push(open); }
      };
      refreshCards = async () => {
        const generation = ++viewGeneration;
        clearDetailActions(); output.textContent = 'ACT 최신 작업 대장 조회 중…'; const loaded = await loadCards(fetcher); if (!dialog.isConnected || generation !== viewGeneration) return; if (loaded.state === 'UNAVAILABLE') { output.textContent = `조회 상태: ${loaded.reason}`; return; } if (loaded.state === 'EMPTY') { output.textContent = '저장된 작업이 없습니다. 저장 누락인지 실제 작업 없음인지는 별도 확인이 필요합니다.'; return; }
        output.textContent = ''; for (const bucket of ['CURRENT', 'COMPLETED', 'RECHECK']) { const cards = loaded.cards.filter(card => recoveryBucket(card) === bucket); if (!cards.length) continue; const bucketTitle = doc.createElement('h3'); bucketTitle.textContent = recoveryBucketLabel(bucket); output.append(bucketTitle); const groups = new Map(); for (const card of cards) { const key = card.scope === 'PROJECT' ? `PROJECT:${text(card.project) || '분류 미지정'}` : card.scope; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(card); } for (const [key, groupedCards] of groups) { const title = doc.createElement('h4'); title.textContent = key === 'UNASSIGNED' ? 'ACT 작업 대장 · 프로젝트 미지정' : key.startsWith('PROJECT:') ? `프로젝트 · ${key.slice(8)}` : section(key); output.append(title); for (const card of groupedCards) { const row = doc.createElement('section'); row.style.cssText = 'border-bottom:1px solid #515b6c;padding:8px 0;display:flex;gap:8px;align-items:center'; const validation = text(card.validation?.state) || '검증 미확인'; const freshness = text(card.freshness?.state) || '기록 시점 미확인'; const execution = text(card.execution?.state) || '실행 상태 미확인'; const related = items(card.related_projects).join(', '); const label = doc.createElement('span'); label.style.cssText = 'flex:1;min-width:0'; label.textContent = `${card.title ? `${card.title} · ` : ''}${card.status || '상태 미기록'} · ${card.task_id || '작업 ID 미기록'} · ${card.role || '작업자 미기록'} · 확인 ${card.updated_at} · ${validation} · ${freshness} · 실행 ${execution}${related ? ` · 관련 ${related}` : ''}`; const select = doc.createElement('button'); select.type = 'button'; select.textContent = text(card.source).toUpperCase() === 'ACT_TASK' ? '작업 보기' : '인수인계 보기'; select.addEventListener('click', () => { void showDetail(card); }); row.append(label, select); output.append(row); } } }
      };
      refresh.addEventListener('click', () => { void (selectedCard ? showDetail(selectedCard) : refreshCards()); }); void refreshCards();
    }); return button;
  }
  globalThis.MonitorWorkRecovery = Object.freeze({ loadCards, loadRecord, handoffText, taskText, copy, createButton, recoveryBucket });
})();
