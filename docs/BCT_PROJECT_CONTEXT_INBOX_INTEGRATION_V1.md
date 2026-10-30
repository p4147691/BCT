# BCT 프로젝트 맥락·GitHub 알림 기준 V3 — 2026-10-31

## 확정 사용자 구조
- `project-context` — 프로젝트 목표·결정·진행 요약·Work 기록·재개 지침의 단일 사용자 관점. 기존 ProjectContextFeature `central-get/save`, `worklog-get/save`, `overview` 재사용.
- `bct_github_inbox_get` — 기존 `bct_inbox_get`을 더 명확히 부를 **공개 도구 개명 후보**. 현재 실제 도구 이름은 `bct_inbox_get`; Work별 GitHub CI/작업 완료 알림을 조회하고 선택적 acknowledge를 수행한다. 자동 작업 처리는 별도 검증이 필요하다.
- **`project-inbox` 신규 명령/저장소를 만들지 않는다.**
- **`WorkerResultInbox`를 project-context에 새로 통합하지 않는다.** 사용자가 요청한 프로젝트 기록 기능의 필수 구성 요소로 취급하지 않는다.

## WorkerResultInbox 삭제 판단 (실제 소스 조회)
- `src/bct/worker_result_inbox.py`에는 별도 SQLite 저장, 결과 SHA 검증, 매니저별 미처리 보고 조회·판정이 구현돼 있다.
- `src/bct/worker_result_recovery.py`가 이 클래스에 직접 의존한다.
- `src/bct/delivery_continuation_recovery.py`의 `plan_worker_result_inbox`가 `WorkerResultRecovery`를 호출한다. 이는 옵트인된 별도 복구 경로이며 일반 `run_once`와 구분돼 있다.
- 관련 테스트 `tests/test_worker_result_inbox.py`, `tests/test_worker_result_recovery.py`, `tests/test_relay_runtime_settings.py`가 있다.
- 따라서 **project-inbox를 취소했다는 이유만으로 WorkerResultInbox를 삭제할 수는 없다.** 실제 운영 호출/활성화/외부 의존성 확인 후 사용하지 않는 것이 입증되면 별도 격리 리팩터링으로 제거한다.
- 현재 프로젝트 맥락 설계에서는 WorkerResultInbox를 직접 참조하지 않으며, 기존 저장·복구 데이터와 코드는 변경하지 않는다.

## 오케스트레이션 및 메시지 보존
- 기존 `bct_orchestrate` 25개 하위 작업과 `node-sync` 보존. 실제 중복 근거 없는 개명·삭제 금지.
- `create-chat-tab`, `create-chat-window`, `send-message` 보존.
- 현재 `status bct/node/rcc/monitor` 및 Monitor 우클릭 저장 구조 보존.

## 후속 구현·수락
1. 기존 project-context 공통 맥락·Work별 기록을 프로젝트 재개용 보기로 연결한다.
2. 기존 `bct_inbox_get`의 Work별 GitHub 알림 계약을 유지하면서 새 이름 `bct_github_inbox_get`이 필요한지 호출 의존성·MCP 도구 호환을 확인한다. 개명은 기존 호출을 깨지 않는 방식으로만 한다.
3. WorkerResultInbox의 실제 운영 진입점/호출 그래프를 조사하고 별도 제거 가능성만 보고한다. 현재 코드·테이블·기록 삭제 금지.
4. 이번 설계 변경은 Core·DB·Chrome·RCC·Monitor 운영 동작을 변경하지 않는다.
