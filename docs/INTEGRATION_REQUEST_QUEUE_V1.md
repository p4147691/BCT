# BCT 통합 준비 요청함 V1

상태: 격리 소스 구현 단계. Core LIVE 설치와 MCP 도구 갱신이 확인되기 전까지 운영 사용 가능으로 선언하지 않는다.

## 저장 위치와 순서

기존 BCT 영속 SQLite: D:\BCT\runtime\state\state.sqlite
테이블: integration_requests
접수 순서: sequence INTEGER PRIMARY KEY AUTOINCREMENT (전체 접수 순서)
접수 상태: QUEUED. 이 V1은 등록과 조회만 하며 자동 전송, 감독관 할당, 병합, LIVE 배포, GitHub 게시, 요청 소비를 하지 않는다.

request_id + 제출 Work + 정확한 내용이 같으면 기존 접수 순번을 돌려준다. 같은 ID로 다른 내용을 제출하면 충돌을 반환한다. 저장 영수증에는 sequence, request_digest SHA256, manager_work_id, 등록 시각이 포함된다.

## 기본 노드 지침

모든 BCT 협업 노드의 기본 작업 범위는 "격리 공간에서 구현 및 테스트하고 메인 병합 직전 준비 완료"까지다. 사용자가 별도로 직접 지시하지 않았으면 공유 local main 병합, LIVE 적용, GitHub main 게시는 하지 않는다.

Worker는 변경 파일, feature HEAD, 테스트 근거와 남은 문제를 원래 매니저에게 보고한다.
프로젝트/독립 작업 매니저는 검수 PASS 후 BCT에 통합 요청을 한 번 등록하고 접수 번호를 결과로 보고한다. 통합 요청 접수는 통합 완료가 아니다.
교통정리 노드는 접수 순서로 조회하고 일괄 실행 담당자를 판단한다. 감독관은 특별 권한자가 아니다. 사용자가 매니저에게 직접 실행을 지시하면 감독관 승인 없이 그 매니저가 기존 BCT 권한 및 충돌 검증 아래 실행할 수 있다.

## 등록 API (Core 배포 이후)

BCT MCP 도구: bct_integration_queue
- submit: work_id=<현재 매니저 Work>, operation=submit, request=<아래 JSON>. Work에는 write가 필요하다.
- list: work_id=<조회 Work>, operation=list, repository_root=D:\BCT\source (선택), limit=50. Work에는 read가 필요하다.
- 모든 요청은 증가하는 sequence 순서로 조회된다. list 조회는 "실행 담당자 선정"이나 "요청 소비"가 아니다.

JSON 제출 양식 (예시 SHA는 반드시 실제 검증값으로 교체):

    {
      "request_id": "monitor-fix-20261028-01",
      "project_id": "monitor",
      "repository_root": "D:\\BCT\\source",
      "expected_main_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "feature_branch": "fix/monitor-thumbnail",
      "feature_head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "changed_files": ["modules/monitor/extension/features/thumbnail.js"],
      "test_receipts": ["focused:PASS", "CI:SUCCESS"],
      "candidate_ci_run_id": null,
      "target_live_products": ["monitor"],
      "acceptance_criteria": "실행 중 최소화 노드 번호와 새 창 즉시 갱신 실제 검증",
      "rollback_plan": "기존 설치 payload와 정확한 SHA로 롤백",
      "manager_conversation_uuid": "",
      "context_note": ""
    }

문서/코드만 바뀌어 설치 대상이 없으면 target_live_products=["NO_LIVE_CHANGE"]를 쓴다. request_id는 업무별로 고유하게 정한다. 원래 제출 내용을 바꿔야 한다면 새 요청 ID를 사용하고 이전 ID와 관계를 context_note에 기록한다.

## 공통 지침을 내리는 방식

1. BCT Manager/Worker에게 앞으로 새로 전달하는 메시지는 기존 relay_prompt.py가 글로벌 공통 규칙을 자동 합성한다. 프로젝트별 추가 지시를 덮어쓰지 않고 함께 전달한다. 이미 제출한 메시지에는 소급 적용하지 않는다.
2. Codex 등 BCT 소스를 작업하는 노드는 .cursor/rules/bct-delivery-flow.mdc(alwaysApply)로 같은 원칙을 읽는다.
3. 이미 열려 있는 일반 ChatGPT 탭에 자동 일괄 주입되는 것은 아니다. 사용자나 담당자가 최초 1회 메시지를 전달해야 하며, RCC로 실제 전송하려면 정확한 바인딩과 사용자 승인 및 영수증이 필요하다. 무단 방송, 새 탭 생성, UNKNOWN 재전송 금지.

## 후속 단계 (현재 미구현)

접수 요청을 감독관 기본 노드로 통지 -> 수신 ACK -> 사용자 직접 지정 또는 감독관 일괄 배정 -> 동일 repo에 대해 하나의 임시 효과 예약 -> guarded local main merge -> 검증/CI -> LIVE E2E -> GitHub main 마지막 동기화 -> 단계별 완료 영수증 기록.

기존 orchestration_mailbox는 세션/assignment 종속이고, manager Wake는 Worker 결과에 종속된다. github_run_inbox는 CI 상태용이다. 이 요청함을 기존 Inbox와 혼동하거나 독점 권한/새 감독 시스템을 만들지 않는다. 내부 node-sync는 유지한다.
