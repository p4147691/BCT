# PR #363 후속: UNKNOWN 진단 및 레거시 호출자 감사 (초기 조사)
기준 main: 50e164bc0d0e25ef69ea59492e057fd1727be80d / Core Gen241
원본 PR #363: MERGED, 원본 Worktree 미커밋 문서 2건 보존

## 이번 격리 후보
- 새 문서 2건은 원본 Worktree의 변경 내용을 바이트 동일하게 승계.
- 읽기 전용 UNKNOWN 단계 진단 함수: 원본 Operation ID/상태/오류/단계 영수증과 별도 관측 호스트 상태를 받아 마지막 성공 단계, 부족한 증거, 실패 판정 지점을 구성. 성공이나 원본 Outcome 수정을 수행하지 않음.
- 테스트: 새로운 3개 + 기존 RCC 82개 = 85/85 PASS. 실제 전송/영수증 기록 경로와 통합되기 전의 isolated helper.

## 실제 호출자·복구 의존성 소스 조사 (삭제 금지)
- src/bct/features/orchestration.py:1486: 내부 오케스트레이션의 legacy send 호출
- src/bct/worker_dispatch_recovery.py:649: Worker 디스패치 복구 send
- src/bct/core/operations.py:96-195: reconcile-send, reconcile-create-and-send 및 원본 digest/권한 검사
- src/bct/features/rcc.py:1972, 2044, 2275-2301: create-and-send, send 및 과거 UNKNOWN 원본 별도 reconciliation 경로
- src/bct/integrations/rcc.py:445: send/send-wakeback 호환성
- modules/rcc/PROVENANCE.md:256-264: 역사적 create-and-send 복구 근거
- src/bct/mcp_server.py:48-57: 공개 신규 send-message 기본 안내 (레거시 호환 유지)
- 운영 데이터의 실제 호출자 전수조회는 미완료. 위는 git 추적 소스 조사로 한정.

## 감독관 E2E 영수증 재사용 (재전송 없음)
- Work BCT-SUPERVISOR-PR363-PR359-PROTECTED-MERGE-20261030-01:
  - pr363-isolated-new-window-send-once-06 FINISHED/APPLIED, host_state RESULT_PERSISTED, command send-to-created-tab
  - pr363-followup-last-assistant-read-04 FINISHED/APPLIED, command read-latest-assistant
- 응답 전문, 동일 메시지 해시, 창/탭별 나머지 시나리오 연결 증거는 아직 확보하지 못했으므로 물리 E2E 전체 PASS로 판정하지 않음.

## 미완료 (READY_FOR_REVIEW 금지)
1. 자동 진단을 실 BCT Operation에 연결하고 권한·연계·영수증 스키마를 검증.
2. 원본 UNKNOWN 보존형 별도 reconcile receipt를 구현하고 충분한 동일성·단일 턴·ACK·답변 증거로 fail-closed 테스트.
3. 운영 DB의 실제 send/create-and-send 호출자 및 historical recovery 의존성 전수 감사.
4. 감독관 E2E 전체 4종 영수증/응답 전문 회수 및 아직 미검증인 경우 안전한 독립 수락시험.
5. 변경 HEAD CI 및 최신 main merge-tree 충돌 검증.
