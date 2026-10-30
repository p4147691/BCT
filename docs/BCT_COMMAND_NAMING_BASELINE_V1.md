# BCT 명령어 기준 V1 — 2026-10-31

이 문서는 **현재 합의된 명명·책임 경계**다. 사용자용 이름은 실제 MCP 이름과 다를 수 있다. **미구현 별칭을 실행 가능한 명령으로 가장하지 않는다.** BCT Core Gen253 / main b48d294 기준. 새 기능은 이 문서를 먼저 대조하고 중복 구현을 피한다.

## 1. 상태 (현재 구현)

| 사용자 표현 | 실제 호출 | 범위 |
|---|---|---|
| status bct | bct_status(scope="bct") | Core/서비스/운영 스냅샷. 미관측 MCP/터널 값은 추정하지 않음 |
| status node | bct_status(scope="node") | **현재 실제 노드만**. 번호·이름·역할·소속·메모·담당 작업; 닫힌 노드 제외 |
| status rcc | bct_status(scope="rcc") | RCC 인스턴스·세션·탭·대화 |
| status monitor | bct_status(scope="monitor") | Monitor 관측·표시 투영 |

## 2. 노드 수정 (현재 Monitor 경로 / 사용자용 이름 제안)

- `update-node` — 우클릭 노드의 이름·대화망·역할·담당 작업·메모 수정. **사용자용 제안 이름이며 별도 공개 MCP 도구는 아직 없음.**
- `updateConversationScope` — Monitor의 기존 Core 전달 함수 (**내부 실행**).
- `configure_conversation_scope` — 기존 SQLite 메타데이터 저장 함수 (**내부 지원**).
- `save-node`/`store-node`는 과거 이름 제안일 뿐 **실제 명령이 아니며 새로 만들지 않음**.
- 같은 노드 메타데이터를 중복 등록하지 않는다. 노드 번호·RCC 주소·권한은 서로 다른 개념이다.

## 3. 프로젝트 맥락과 보고 (단계적 통합)

- `project-context` — 목표·범위·결정·진행 요약·남은 작업·재개 정보. **설계 명칭, 완성된 공개 명령 아님**.
- `project-inbox` — 프로젝트 전체의 시간순 작업자 제출·매니저 판정·인수인계. 노드/작업별 필터는 하위 보기. **설계 명칭, 완성된 공개 명령 아님**.
- 기존 `bct_conversation_network_get` (**공개 조회**)은 특정 등록 프로젝트의 이름·구성원·역할·최근 Monitor 관측을 읽음. 프로젝트 맥락 전문이나 작업자 보고 전문은 포함하지 않음.
- 기존 `bct_inbox_get` (**공개 조회**)은 영속 Inbox 결과 조회. 범용 프로젝트 집계 기능을 이미 갖췄다고 가정하지 않음.
- 프로젝트는 고유 ID와 표시 이름을 구분한다. 표시 이름 변경을 이유로 모든 노드를 수동으로 재등록하지 않도록 설계한다.
- 전역 감독관은 특정 대화망 구성원이 아니다. 매니저·작업자 역할은 우클릭 설명값이며 실행 권한과 다르다.

## 4. 협업 실행 (기존 공개 진입점 유지)

- `bct_orchestrate` (**공개**) — 협업 관리. 내부 하위 단계:
  - `project-run-plan` (**내부 지원**) — 기존 등록망을 기반으로 매니저 후보·실행 계획.
  - `start` (**내부 실행**) — 영속 협업 실행 기록 생성; ChatGPT 탭 생성이 아님.
  - `node-sync` (**내부 지원, 보존 필수**) — 실제 노드·대화 식별 정보 동기화.
  - `project-run-bind` (**내부 실행**) — 협업 실행과 현재 RCC attachment 연결 검증.
  - `dispatch` (**내부 실행**) — 구체적인 작업 배정·실행.
  - `chain-run` (**내부 실행**) — 다단계 실행 흐름.
- 준비/연결/실행은 사용자에게 자동화하되, 중복 판단은 실제 호출·영수증·회귀로 검증 후 한다. 내부 명령의 무근거 삭제·개명 금지.

## 5. 메시지 (완성된 공개 명칭 유지)

- `create-chat-tab` — 새 ChatGPT 탭 생성 (**공개**).
- `create-chat-window` — 새 Chrome 창·ChatGPT 탭 생성 (**공개**).
- `send-message` — 정확한 대상 전송·응답 회수 (**공개**).
- 내부: `state` (**내부 지원**), `send-to-tab`/`send-to-created-tab` (**내부 실행**), `result`/`read-latest-assistant` (**내부 결과 처리**).
- `bct_operation_get` (**공개 조회**) — BCT Operation 영수증·ACK·실행 상태. RCC `result`와 별도 계층.
- 구형 `send`/`create-and-send`/`result-of-create-and-send`는 신규 실행 제거 후보. 과거 기록 판독·소유권 검증은 PR #374에서 분리 후 불필요한 실행 코드만 삭제.

## 운영 규칙

1. **로컬 main 정본**: 격리 개발 → PR CI → 로컬 main 병합·회귀 → 정확한 LIVE 배포·E2E → GitHub main 게시·main CI.
2. 새 채팅은 현재 BCT capabilities/실제 도구 계약을 확인한다. 본 문서의 사용자용 이름만으로 도구가 존재한다고 가정하지 않는다.
3. 신규 명령 추가 시 정확한 실제 이름·인자·분류(공개/내부 실행/내부 지원/내부 호환/결과 처리)·대체 관계를 함께 갱신한다.
4. 이 단계는 이름과 책임 경계의 **기준선**이며 Core/RCC/Monitor/Chrome 및 운영 DB의 동작 변경을 수반하지 않는다.

## GitHub 알림 명칭 (2026-10-31 추가)
- `bct_github_inbox_get` — GitHub CI/작업 완료 알림 조회 및 선택적 읽음 처리 (**신규 공개 이름**).
- `bct_inbox_get` — 기존 호출을 위한 **공개 호환 별칭**. 동일 구현을 호출하며 별도 저장소를 만들지 않는다.
- `WorkerResultInbox` — 작업자 결과·매니저 판정·연속 처리 복구에 필요한 기존 **내부 결과 처리**. 삭제·개명·프로젝트 맥락 통합 금지.
- `project-context` — 기존 프로젝트 맥락·Work 기록. 별도 project-inbox 생성 금지.
