# Chat Input Queue V1 — 독립 영속 입력 큐

상태: 격리 브랜치에서만 구현. 운영 Core LIVE에 아직 적용되지 않음.
대표 MCP 명령: **queue_message** (action + object).
구현: src/bct/chat_input_queue.py, 공개 경계: src/bct/mcp_server.py.

## 목표와 안전 경계
- A의 연속 지시를 **대상 대화 UUID별 SQLite FIFO**에 저장하고, B가 현재 일을 마쳤다고 검증된 시점에 한 건만 claim하도록 준비.
- 입력: 소유 Work ID, 대상 대화 UUID, 안정된 message_id, 원문 instruction(최대 24KB), 선택 origin UUID.
- 출력: sequence, 상태, SHA-256, claim ID, 대기 목록과 개수. claim만 원문 반환; status는 원문을 숨김.
- **status는 읽기만 수행**하며 빈 DB 상태에서도 자동 생성/소비하지 않음. 작업 상태 변경 시 Work의 orchestrate 권한 필요, 조회에는 read 필요.
- 외부 효과 **없음**: Chrome/RCC 전송, Chain Message, Delayed Send, Run Plan, Task Run, 서비스 재시작, GitHub/배포 작업과 무연결.
- 기존 BCT Store.transaction (BEGIN IMMEDIATE), 이벤트 영수증, Work 소유권 검증을 재사용. 이전 integration_queue 브랜치의 FIFO sequence/중복 ID 원칙만 차용.

## 공개 명령 계약

대표 형태: queue_message(work_id, target_conversation_key, action, ...)

| action | 추가 인자 | 의미 |
| --- | --- | --- |
| enqueue | message_id, instruction, origin_conversation_key 선택 | 대상 큐 끝에 원문 추가; 동일 ID+Work+대상+원문은 duplicate=true, 다른 내용은 충돌 |
| status | limit 선택 (1~100, 기본30) | 대상별 개수, head 및 목록(원문 제외), read_only=true |
| claim | claim_id | 첫 미완료 한 건만 CLAIMED 및 원문 반환. 다른 활성/보류 head가 있으면 BLOCKED |
| complete | message_id, claim_id, result_sha256 | 정확한 claim을 DONE으로 처리. result SHA는 외부 응답의 독립 증명 아님 |
| hold | message_id, claim_id, reason, hold_kind | UNKNOWN(기본)→HELD_UNKNOWN 또는 PRE_DISPATCH→HELD_PRE_DISPATCH |
| resume | message_id, 원래 claim_id | HELD_PRE_DISPATCH만 QUEUED로. HELD_UNKNOWN 재개 불가 |

상태: QUEUED → CLAIMED → DONE, 또는 CLAIMED → HELD_PRE_DISPATCH → QUEUED,
또는 CLAIMED → HELD_UNKNOWN (안전 보류, 자동 해제 없음).

대상 A에서 지시 1, 2, 3을 등록한 뒤 1을 claim하면 2와 3은 1이 DONE 처리될 때까지 전달되지 않는다. 대상 B의 큐는 A와 독립된다.

## 복구·중복·영수증
- message_id는 전체 큐에서 고유; 같은 ID의 다른 Work/대상/원문은 충돌.
- claim_id도 전역 고유. 이력 테이블로 과거 claim ID 재사용 차단.
- 동일 활성 claim ID 재조회는 duplicate=true. **새 실행을 허용한다는 뜻이 아니다.**
- 재시작해도 CLAIMED와 HELD는 그대로 남으며 타임아웃 자동 재소비 없음.
- UNKNOWN은 선예약/응답 증거 없이 재전송하거나 재개할 수 없음.
- PRE_DISPATCH는 호출자의 분류일 뿐 신뢰된 무전송 증거가 아니므로, 추후 연결 어댑터는 원본 BCT Operation 영수증을 독립 검증해야 함.
- complete는 내부 큐 처리 기록일 뿐 B 응답 완료의 증명 아님. 실제 B 응답이 끝나기 전 호출 금지.

## 미래 연결 포트 — 이번에는 연결하지 않음
1. 입력 어댑터: 검증된 A Work와 정확한 B 대화 UUID, 안정된 message_id로 enqueue하고 저장 ACK 반환.
2. readiness 어댑터: B의 실제 idle/기존 작업 완료, 최신 RCC instance/session/tab/window/conversation을 검증한 뒤에만 claim.
3. delivery 어댑터: 원본 Operation ID/대상/SHA를 먼저 영속적으로 확정하고 정확히 한 번 submit. UNKNOWN 재전송 금지.
4. 결과 어댑터: 신뢰된 responseTurnKey, 응답 SHA, Manager 반환 증거 확인 뒤 complete, 불분명하면 hold UNKNOWN.
5. Monitor: 카운트·순번·보류상태만 읽기 전용으로 보여주며 원문·자동소비 금지.

## 공식 근거
- AWS SQS FIFO group ID 및 deduplication: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-key-terms.html
- AWS FIFO ordering / delivery logic: https://docs.aws.amazon.com/en_en/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-understanding-logic.html
- Microsoft SQLite 원자 트랜잭션: https://learn.microsoft.com/en-us/dotnet/standard/data/sqlite/transactions

본 구현은 클라우드 큐를 사용하지 않는다. BCT의 기존 안전 규약이 우선한다.
