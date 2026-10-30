# BCT 프로젝트 맥락 통합 설계 V2 — 2026-10-31

## 사용자 결정
- **별도 `project-inbox` 공개 명령이나 신규 저장소를 만들지 않는다.**
- 프로젝트 목표·결정·진행 요약·작업자 제출 보고 흐름·재개 정보는 **기존 `project-context` 하나의 논리적 보기**로 제공한다.
- `bct_inbox_get`은 기존 **GitHub CI/작업 완료 알림** 조회·읽음 처리 용도로 유지하고 적극 활용한다.
- `WorkerResultInbox`는 원본 작업자 결과·SHA·매니저 판정의 내부 저장소로 보존한다. 기존 데이터 복사·삭제·재귀속 금지.

## 실제 구현과 한계
- `ProjectContextFeature`의 `central-get/save`, `worklog-get/save`, `overview`는 기존 append-only ProjectMemoryStore를 사용한다.
- `WorkerResultInbox`의 `pending`은 매니저별 **미처리** 결과만 조회한다. 전체 프로젝트 보고를 자동으로 제공하는 것은 아니다.
- `bct_inbox_get(initiator_node_id,work_id,acknowledge,limit)`은 소유 Work 범위의 GitHub 완료 알림을 읽는다. 자동 조치 실행·프로젝트 전체 작업자 보고 조회로 해석하지 않는다.
- `bct_conversation_network_get`은 프로젝트 구성원·역할·Monitor 관측 정보를 제공하지만 맥락 요약/작업자 보고 전문은 제공하지 않는다.

## 최소 구현 방향
1. 프로젝트 고유 ID로 맥락을 연결한다. 프로젝트 표시 이름 변경이 Work 연결을 깨뜨리지 않도록 한다.
2. 공통 맥락에는 목표·범위·주요 결정·현재 진행·미완료 작업·재개 지침을 저장한다.
3. Work별 작업자 보고는 기존 Work journal 및 WorkerResultInbox의 정확한 Work·delivery ID·SHA를 **참조**한다. 프로젝트 소속이 검증된 결과만 맥락 보기에서 연결한다.
4. `overview`를 프로젝트 재개용 기본 조회로 사용하고, 원본 보고 전문은 정확한 권한과 Work 식별이 확인될 때만 별도 열람한다.
5. GitHub CI 완료 알림은 기존 `bct_inbox_get`을 사용한다. 알림 확인→정확한 GitHub 실행/영수증 검증→필요한 작업 판단→처리 결과 기록의 흐름을 설계한다. 자동 처리·ack는 호출 권한과 검증된 결과가 있을 때만 실행한다.
6. 현재 열려 있지 않은 과거 노드는 `status node`에 포함하지 않는다. 프로젝트 맥락의 이력 참조로만 유지한다.
7. `bct_orchestrate`의 25개 내부 작업, `node-sync`, `create-chat-tab`, `create-chat-window`, `send-message`는 보존한다. 실제 중복 증거 없는 삭제·개명 금지.

## 후속 수락 조건
- 프로젝트 맥락 조회에서 결정·진행·남은 일과 Work별 보고 참조를 일관되게 제공.
- 다른 프로젝트·Work의 결과가 섞이지 않고, 이름 변경 후에도 정확한 ID 연결 유지.
- 기존 GitHub Inbox의 조회/읽음 처리 계약·WorkerResultInbox 저장·ProjectContext 회귀 통과.
- 기존 운영 Core/DB/Chrome/RCC/Monitor는 이 설계 문서 변경으로 수정하지 않는다.
