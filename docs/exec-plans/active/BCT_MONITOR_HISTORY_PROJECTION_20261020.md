# BCT 현재 노드 / 과거 기록 Monitor projection — 독립 소스 계약

상태: SOURCE-ONLY / ISOLATED / NOT LOADED BY MONITOR / NOT DEPLOYED

기준: PR #249 HEAD c7500d0c9d0e629e00404d52dd905d53311c96a4.
이 작업은 별도 후속 브랜치에서 수행하며 PR #249, 기존 Monitor 활성 UI,
RCC, Native Host, BCT LIVE, 운영 state.sqlite/Claim을 수정하지 않는다.

## 목적

- **현재**: nodes.active=1인 등록 노드의 현재 이름, 역할, 연결 기록 건수만 표시.
  실제 온라인/업무 배정 가능 여부는 RCC 관측·정책 검사 없이 판단하지 않는다.
- **과거**: orchestration_session_nodes의 과거 참여 관계를 노드 active와 독립 조회.
  과거 시점의 이름/역할을 증명하는 스냅샷이 없으면 UNKNOWN이다.
- **프로젝트**: conversation_network 프로젝트/대화 멤버십을 표시하되
  Work와의 연결은 별도 증거가 없으면 NOT_PROVEN이다.
- **협업 기록**: Work→Session, Operation·Event 및 메시지·RESULT/ACK/Decision의
  상세 구조화 기록은 PR #249 읽기 전용 백엔드에서 명시 요청 시 조회한다.
- **대화 원문**: 구조화된 Mailbox는 전체 ChatGPT 원문과 다르다.
  Snapshot coverage 미확정 시 NOT_VERIFIED, FULL로 승격 금지.

## 경계/데이터 흐름

1. 운영 SQLite 자체를 Monitor가 열지 않는다.
2. 기존 방식으로 **동일 시점** 백업·무결성 검증이 끝난 격리 SQLite 복사본을 준비한다.
   백업/해시 영수증은 기존 검사 결과를 재사용; 이 PR에서 백업 자동화 없음.
3. `history_monitor_projection.history_view(snapshot, work_ids=[...],
   project_ids=[...])`를 **명시적 사용자 조회 요청**에 한해서 실행.
   운영 파일명이 state.sqlite인 DB로는 직접 연결하지 못하도록 제한한다.
4. 반환 스키마 `BCT_MONITOR_HISTORY_VIEW_V1`에
   `source=IMMUTABLE_SQLITE_SNAPSHOT`, `snapshot_only=true`를 포함.
   연결된 사용자 대화 내용/토큰/Operation payload는 목록에 넣지 않는다.
5. `MonitorHistoryReadonly.mount({ document, loadSnapshot })`로
   현재/과거 두 탭을 표시할 수 있다. `loadSnapshot`은 사용자 클릭으로만 실행,
   자동 polling·GET/POST·background job·RCC command 없음.
6. 실제 Monitor `desktop.html` load graph, `monitor.js`,
   `monitor-bct-shell.js`, 운영 UI 및 Native Host는 **이 PR에서 수정하지 않음**.
   독립 수락 뒤 별도 명시 승인 시 정확한 read-only provider 연결을 추가한다.

## 안전/정합성

- N번호·탭·창·HWND를 과거 노드 영구 ID와 동일시하지 않는다.
- project/conversation, node/work/session/assignment는 독립 식별자를 사용한다.
- FAILED, UNKNOWN, NOT_APPLIED를 SUCCESS로 해석하지 않는다.
- `NOT_CAPTURED`, `PARTIAL`, `NOT_VERIFIED`를 FULL로 추정하지 않는다.
- `textContent` 사용, 임의 문자열 HTML 해석·자동 링크 실행 없음.
- 조회 예외/타임아웃은 UNAVAILABLE. 비어 있는 기록으로 덮어쓰지 않는다.
- 선택 Work/Project ID는 각각 최대 12개, 목록은 최대 100개 표시; 잘린 결과는 경고.
- 외래 키·메시지 digest·epoch의 기존 검증 범위를 넘어선 의미적 완결성 보장 없음.
- 기존 시점/버전의 정확한 historical display name, 다대다 Work↔Project,
  전체 transcript 자체는 아직 별도 데이터 확보가 필요한 범위.

## 테스트

```
PYTHONPATH=src python -m unittest tests.test_history_monitor_projection tests.test_history_readonly tests.test_project_memory tests.test_conversation_history -q
node modules/monitor/tools/check_monitor_history_readonly.cjs
git diff --check
```

현재 PR은 Monitor UI에 실제 표시되지 않으며 배포·Live E2E 통과라고 말하면 안 된다.
