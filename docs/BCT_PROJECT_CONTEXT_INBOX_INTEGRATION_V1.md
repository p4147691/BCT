# BCT 프로젝트 맥락·보고 통합 설계 V1 — 2026-10-31

## 조사 범위와 실제 정본
- Core Gen254, main 0c915e2d764f283a274e178929ad59d800f767d8. 기존 PR #378 명명 기준 보존.
- `project_context.ProjectContextFeature`는 기존 ProjectMemoryStore append-only ledger를 사용한다. `central-get/save`, `worklog-get/save`, `overview`가 구현돼 있다.
- `worker_result_inbox.WorkerResultInbox`는 delivery_id, work_id, manager_uuid, worker_uuid, 결과 전문·SHA, capture_state, 매니저 판정과 시간을 저장한다. `pending`은 manager_uuid 중심의 **미처리 보고** 조회다.
- **`bct_inbox_get`은 작업자 보고 Inbox가 아니다.** 기존 `get_github_run_inbox`로 initiator_node_id + owned work_id의 GitHub 완료 알림을 읽고, 선택적으로 acknowledge 처리한다.
- `bct_conversation_network_get`은 등록된 프로젝트 구성원·역할·최근 Monitor 관측 조회다. 프로젝트 목표·결정·작업자 보고 전문은 제공하지 않는다.

## 사용자 관점
```text
project-context (사용자용 논리 기능, 새 공개 명령 아님)
├─ 목표/범위/현재 결정/진행 요약/남은 작업/재개 지침
├─ 기존 central-get/save (내부 조회·저장)
└─ 기존 worklog-get/save/overview (내부 조회·저장)
project-inbox (사용자용 논리 기능, 새 공개 명령 아님)
├─ 프로젝트 전체 시간순 보고·판정·인수인계
├─ Work별·노드별·기간별 필터
├─ 기존 WorkerResultInbox (작업자 결과 정본)
├─ 기존 Work/Operation/Inbox 영수증 링크
└─ 기존 bct_inbox_get (GitHub 완료 알림, 별도 소스)
```

## 최소 통합 설계
1. 프로젝트 ID를 정본 키로 사용한다. 표시 이름을 변경해도 구성원·보고 링크가 바뀌지 않아야 한다.
2. 기존 `project-context` central 기록에 목표·범위·결정·현재 진행·남은 일·최종 갱신 시각과 출처를 저장한다. 새 테이블을 만들지 않는다.
3. Work 기록은 기존 worklog로 연결한다. WorkerResultInbox 결과는 delivery_id + work_id를 통해 기존 Work 소속 프로젝트를 검증한 뒤 **읽기 전용으로 집계**한다.
4. 시간순 프로젝트 보고는 WorkerResultInbox의 전체 결과(미처리만 아님)와 매니저 판정, 기존 Work 진행/영수증을 결합한다. 현재 `pending`만으로는 전체 이력이 완성되지 않으므로 별도 read-only 조회 계약이 필요하다.
5. 결과 전문은 필요할 때만 정확한 Work/권한으로 열람한다. 기본 목록은 제출시각·작성 노드·Work·상태·요약·영수증 링크를 보여준다.
6. GitHub 완료 알림은 동일한 `project-inbox` 보기에서 출처를 구분해 표시할 수 있지만 `bct_inbox_get`의 원래 조회/ack 계약은 바꾸지 않는다.
7. 프로젝트 재개 시 `project-context`의 최신 공통 요약과 프로젝트 전체 보고 흐름을 함께 조회해 매니저에게 전달한다. 현재 열려 있지 않은 노드는 `status node`에 넣지 않는다.
8. 기존 데이터의 프로젝트 연결 근거가 없는 보고는 **미분류**로 남기고 임의 귀속하지 않는다. 불명확한 측정 Claim/UNKNOWN은 진행 차단 근거로 쓰지 않는다.

## 오케스트레이션 경계
- 현재 `bct_orchestrate`의 25개 하위 작업은 별개의 호출 계약이다. `project-run-plan`(계획), `session-start`(영속 실행), `node-sync`(노드 연결), `project-run-bind`(RCC attachment 검증), `dispatch`(작업 배정), `chain-run`(연쇄 실행)을 그대로 유지한다.
- 기능이 비슷해 보인다는 이유만으로 삭제하지 않는다. 실제 호출 그래프·테스트·영수증에서 중복이 입증된 부분만 다음 PR에서 정리한다.
- 이 설계 PR에서는 운영 DB, Chrome/RCC/Monitor, Core 실행 코드, 기존 메시지 3개를 변경하지 않는다.

## 후속 구현 수락 기준
- 같은 프로젝트의 완료·미처리·판정 보고를 시간순으로 조회하고 Work/노드 필터가 정확함.
- 다른 프로젝트 결과가 섞이지 않음. 프로젝트 이름 변경 후에도 ID 연결 유지.
- 재개용 맥락 요약과 원본 보고 영수증을 함께 제공.
- 기존 bct_inbox_get, WorkerResultInbox, project-context 및 orchestrate 회귀 통과.
