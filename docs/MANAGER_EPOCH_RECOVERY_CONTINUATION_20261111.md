# BCT Manager Epoch 자동 복구 — 영수증 연속성 점검 (격리 후보)

원 Work: bct-supervisor-resilient-chain-20261110
기준 검증 SHA: f65a0863f6afd0d838ec5a641d859ab5eaeefb25
N36/N37 원래 E2E 완료: 재전송·노드 교체 금지.
N40 동일 UUID 두 번째 전송 독립 Chrome/RCC 호스트 E2E: HOLD. N40/N42 및 미커밋·UNKNOWN 보존.

## 완료된 격리 개선
기존 Manager Epoch가 영속적으로 확정됐지만 후계 A에게 첫 인계하기 전 Core가 종료되면, 다음 실행에서는 현재 Manager가 정상이라 신규 승계를 수행하지 않아 PENDING 인계가 남을 수 있었다.
기존 manager_succession_recovery 루프는 현재 Epoch, 현재 Manager, 유일한 정확 attachment 및 bindingReceiptId, Work owner가 일치하는 기존 PENDING/NOT_APPLIED 인계를 자동 조회한다.
후계 A RCC 상태가 IDLE일 때 기존 claim_manager_handoff로 원 delivery ID를 먼저 영속 점유하고 이어서 send/complete를 수행한다.
DELIVERING/UNKNOWN/DELIVERED/BLOCKED, 오래된 Epoch, 다른 attachment, 감시 UNKNOWN은 재전송하지 않는다.
새 Manager를 임의 선출하지 않으며, 원래 작업과 Work·Task·Generation·Watch·Alarm 기록을 그대로 사용한다.

## 장애 주입 확인
Epoch Commit → Core 중단 → 원 PENDING 인계 복귀, 전달은 한 번.
전송 ACK UNKNOWN → 원래 영수증 보존, Core 재시작 후 재전송 없음.
DELIVERING에서 Core 중단 → 재전송 없음.
두 번째 Core lease 소유자 동시 활동 → 불필요한 인계 중복 없음.

## 미완료 및 의존 차단
후계 AI가 실제로 원래 Task/Generation을 재개하고 결과까지 반환했다는 실사용 E2E 증거는 없음.
새 Chat 실제 생성, 활성 Manager Epoch 신규 후계 등록의 완전 무인 실사용 경로는 별도 검증 필요.
N40 Chrome/RCC 독립 실사용 검증 전 동일 UUID 두 번째 전송 의존 시험은 HOLD. 시뮬레이션을 실사용 성공으로 표시하지 않는다.
정확 SHA CI·독립 검수와 명시적 사용자 승인 전 main/LIVE 보류.

## 범위 보완
- PENDING/NOT_APPLIED 인계가 8개 이상이고 일부 후계자가 BUSY여도 전체 후보를 순서대로 검사한다. 별도 커서와 wrap으로 재시작 후에도 누락 없이 재검사한다.
- 진짜 SQLite 샘플 10개 인계에서 3개씩 4회 검사 후 처음으로 순환함을 확인했고, 이전 Manager Epoch 후보는 배제했다.
- 테스트 시뮬레이션에는 사용자 Windows/RCC 새 Chat 전송이 포함되지 않는다.

## 정확한 후계 attachment 추가 보호
- 인계 영수증에 결속된 후계 attachment가 활성 목록에서 최신 generation인지 다시 확인한다. 더 새로운 활성 attachment가 등장하면 이전 bindingReceiptId/탭으로 보내지 않는다.
- 실제 SQLite 장부에서 더 새 attachment를 주입하는 테스트와 Epoch/UNKNOWN 회귀가 통과했다.

## 후계 Manager Task/Generation 원장 조회 보완 (2026-11-11)

기존 자동 복구 후보 a2411ec의 후속 격리 변경이다. 별도의 신규 사용자 승인이나 새 MCP 공개 명령은 추가하지 않는다.

기존 Orchestration 상태 조회에서 활성 Manager Epoch가 2 이상일 때 원래 Work의 정확한 Task/Generation, assignment/attempt state, 원 dispatch operation ID, 대기 중인 Manager Wake, Chain Watch와 미확인 반환을 읽기 전용으로 연결한다.

이 조회는 새 후계 노드가 이미 확정된 Work/Session/Epoch일 때에만 사용할 수 있다. 오래된 Epoch, 종료된 Session, 다른 Work, Work assignment epoch 불일치는 거부한다.

미전송 QUEUED는 기존 경로에서만 채택할 수 있고, dispatch_operation_id가 있으면 외부 제출 여부를 기존 Operation 영수증으로 대조해야 한다. UNKNOWN/기존 발송은 재실행하지 않는다. Watch와 반환의 저장된 원래 Task Generation은 유지한다.

결과 제한은 최대 200개이며 Work별 실제 전체 개수와 complete_listing을 함께 반환한다. 50건 초과 시 결과가 전체라고 잘못 표시하지 않는다.

이미 완료된 N36/N37에는 전송·Check·Replace 없음. N40/N42는 현재 GENERATING 관찰 및 독립 Chrome/RCC 호스트가 아직 확인되지 않아 실제 후계 전송 지시 없음.

코드/DB 격리 회귀는 실제 AI가 Task 완료까지 수행했다는 증거가 아니며, N40 실사용 패치 E2E PASS 전 실사용 Chain 승계 시험은 HOLD한다.

활성 Manager Epoch에서 후계 Chat 생성과 실제 사용자 대화 재개는 계속 미완료. N40/N42 파일, 다른 worktree, UNKNOWN, 운영/main/LIVE 보존.
