# BCT 메시지·대화망·Monitor·Browser Bridge 정리표 (2026-10-30)

> 범위: Core Gen250, main 02a4c12915fc987e1eb9eb265de5c7a646acff05 기준. 이 문서는 분류·경계 정리이며, 실행 중인 RCC/Chrome/Monitor의 설치나 재시작을 요구하지 않는다.

## 사용자가 기억할 공개 진입점

```text
BCT
├─ 메시지
│  ├─ create-chat-tab       기존 창에 새 ChatGPT 탭 생성
│  ├─ create-chat-window    새 Chrome 창에 ChatGPT 탭 생성
│  └─ send-message          기존/생성 탭 메시지 제출 (rcc-send-message-v1)
│     ├─ state              정확한 RCC 세션·탭·대화 식별 (읽기)
│     ├─ send-to-tab        기존 탭 내부 전송 경로 (직접 공개 호출 금지)
│     ├─ send-to-created-tab 생성 탭 내부 전송 경로 (직접 공개 호출 금지)
│     ├─ bct_operation_get  원본 Operation 영수증/제출 ACK 확인
│     ├─ result             해당 전송의 RCC 저장 결과 조회
│     └─ read-latest-assistant 최신 답변 읽기 (이번 턴 완료 보증 아님)
├─ 대화망·노드
│  ├─ bct_status            Core/Monitor 전체 노드·연결·작업 관측
│  │  └─ current_nodes      현재 확인된 ChatGPT 탭/노드, 등록 노드와 별도 집계
│  ├─ bct_conversation_network_get 등록된 대화 범위·구성원·라벨 조회
│  ├─ bct_orchestrate       협업 세션/매니저·작업자 연결
│  │  ├─ node-sync         내부 노드·대화 연결 동기화 (보존)
│  │  ├─ status            협업 상태 조회
│  │  ├─ inspect-result-receipt 작업자 결과 영수증 확인
│  │  └─ manager-wake      매니저 후속 처리 경로
│  └─ bct_inbox_get         결과 Inbox 읽기
└─ 내부 브라우저 경계
   ├─ RCC                   실제 Chrome 탭 상태·메시지 전달 정본
   ├─ Monitor               노드/창/탭 관측·표시, 별도 전송 정본 아님
   └─ Browser Bridge        독립 시험 경로; 운영 RCC와 병렬 메시지 경로로 승격 금지
```

## 정본 소유권

- BCT Core: Work/Operation/영수증/등록 대화망/노드 라벨의 영속 소유자.
- RCC: 브라우저의 실제 탭·세션·대화 상태와 메시지 제출 효과의 관측자. 전송 대상은 정확한 ID/생성 영수증으로만 지정한다.
- Monitor: 현재 창·탭·노드 표시를 읽기 전용으로 투영한다. Monitor의 N 라벨은 사람을 위한 별칭이며 전송 주소나 권한 근거가 아니다.
- `compose_worker_delivery`: 등록된 활성 대화 범위의 구성원/노드 라벨/역할을 Worker 지시문에 포함하는 **내부 조합 함수**. 전체 Monitor 실시간 화면 복제가 아니다.
- `compose_manager_return_frame`: 정확한 Worker 결과를 Manager로 되돌릴 때 문맥을 조합하는 **내부 함수**. 수신/처리 ACK를 자동으로 증명하는 별도 공개 명령이 아니다.
- `node-label-notify`: 확정된 노드 라벨 이벤트를 정확한 RCC 탭에 전달하는 **표시용 내부 경로**. 대화망 상태 메시지 전달과 혼동하지 않는다.

## 유지 / 통합 / 폐기 판단

| 분류 | 대상 | 근거 / 조치 |
|---|---|---|
| 유지 | send-message, create-chat-tab, create-chat-window, state | Core Gen250 공개 계약; 실제 새 탭·새 창 전송 E2E |
| 유지 | bct_status.current_nodes, bct_conversation_network_get, node-sync | 실제 등록망·현재 탭 분리 및 협업 연결 |
| 유지 | send-to-tab, send-to-created-tab, result, bct_operation_get | 현재 send-message 하위 경로 및 영수증 확인 |
| 내부 전용 | simple-relay-send/return, delivery-status/return/response-read, manager-wake | 기존 협업/복구 계층; 공개 명령으로 재노출하지 않음 |
| 제거 후보 | send, create-and-send, result-of-create-and-send | 신규 공개 사용 차단; PR #374에서 과거 영수증 권한/판독 경로를 분리한 뒤 실행 분기 제거 |
| 별도 검토 | PR #366 | 독립 증거 조회 코드 중 기존 result/Operation과 중복되는 부분만 추출; 미검증 UNKNOWN을 차단 근거로 사용하지 않음 |
| 정리 검토 | PR #285 | 구형 shim 5개는 릴리스 매니페스트 및 일부 소스 테스트에 참조가 존재하므로 무검증 삭제 금지. 매니페스트/테스트와 함께 검증 |
| 유지 검토 | PR #249/#252 | 과거 노드·협업 이력 조회 및 Monitor 표시; 현재 current_nodes와는 시간 범위가 다름 |
| 분리 보류 | PR #281/#282 및 Browser Bridge 계열 | 현재 RCC 운영 전송 경로를 대체하지 않음; 독립 격리 개발과 설치 경계 유지 |
| 완료·중복 | PR #362/#354/#276 | HEAD가 main 조상인 것으로 확인해 CLOSED; 브랜치/영수증 보존 |

## 구현/검증 규칙

1. 하나의 자연어 메시지 요청에는 공개 `send-message`만 선택한다. 내부 하위 명령은 Core가 결정한다.
2. 제출 ACK, 실제 수신, 최종 Assistant 응답을 구분한다. `read-latest-assistant`만으로 해당 사용자 턴 완료를 선언하지 않는다.
3. `state`는 RCC 탭 확인, `bct_status`는 Core/Monitor 전체 상태, `bct_conversation_network_get`은 등록 대화 범위 정보다.
4. 구형 명령 제거는 기존 영수증 판독·소유권 검증을 분리하고 회귀시험이 통과한 경우에만 진행한다.
5. 운영 Monitor/Chrome/RCC/Browser Bridge를 변경하는 별도 PR은 각 소유권·릴리스/실사용 시험 경계를 따로 검증한다.
6. 불완전한 측정값이나 미검증 Claim은 개발 차단·성공 증명으로 사용하지 않는다.
