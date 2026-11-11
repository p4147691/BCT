# BCT Manager Epoch 후계 작업 재개 — 독립 코드 검수 패키지

기준 SHA: a2411ecb5ce7f09a615038cf956e6e63f40d94da
후속 후보 브랜치: feat/manager-epoch-task-inventory-20261111
원 Work: bct-supervisor-resilient-chain-20261110

## 범위
현재 Manager Epoch가 2 이상이며 활성 Work·Orchestration Session의 Epoch가 정확히 일치하면 기존 Orchestration 상태 조회에 원래 Assignment·Task/Generation·dispatch Operation ID·미처리 Manager Wake와 Chain Watch·미확인 반환의 읽기 전용 목록을 제공한다.
다른 Work·이전 Epoch·종료된 Session·Work assignment epoch 불일치는 새 작업으로 인정하지 않는다. 조회 결과에는 원장별 실제 건수와 목록의 완전성 플래그를 함께 제공하며 50개를 넘으면 생략을 명확히 표시한다.
조회의 next_safe_step은 안내용이며 작업 재실행 권한이 아니다. 이미 외부 제출된 Operation 및 UNKNOWN은 새 ID로 재전송하지 않는다.
기존 Check/Recheck/Recover/Replace 및 8단계 R은 변경하지 않는다.

## 확인된 노드 / 전송 경계
N36·N37: CONFIRMED/IDLE, chain-recipe-live-e2e-final-1 Generation 1 Watch RETURNED_TO_MANAGER. 복구·재전송하지 않음.
N40·N42: CONFIRMED, 당시 GENERATING, 작업 간섭 및 새 지시 전송하지 않음.
N40 독립 Chrome/RCC 호스트 실사용 패치 전송은 CI PASS와 달리 HOLD. 동일 UUID 두 번째 전송에 의존하는 후계 실제 업무 재개·Windows E2E는 HOLD.
기존 UNKNOWN과 운영 RCC·원본 미커밋·N40/N42 공유 파일은 보존. main/LIVE 변경 금지.

## 검수자가 확인할 정확한 코드
src/bct/manager_successor_inventory.py: 현재 Work/Session/Epoch 조회 조건·원장별 읽기 전용 경계·COUNT와 LIMIT.
src/bct/core/orchestration.py: 기존 snapshot에 보조 inventory를 연결하되 종료된 Session과 초기 Epoch에서는 생성하지 않는 계약.
tests/test_orchestration.py: QUEUED Generation 채택, dispatch UNKNOWN Operation 보존, pending Chain Watch·반환, truncation.
bct.toml 및 scripts/build_component_library.py: 운영 배포 목록·컴포넌트 해시의 신규 모듈 포함.

## 잔여 위험 / 다음 미완료
1. 활성 Manager가 통째로 미관측이며 정확한 기존 RCC 호스트가 없는 경우의 신규 후계 A 생성·등록·Epoch 승계는 이번 후보에서 구현하지 않는다.
2. 원래 Manager가 실제로 실종된 경우의 전권 승계는 이미 저장된 Epoch takeover/attachment와 N40 실사용 호스트 검증에 의존하며 일반 Worker 임의 승격은 금지한다.
3. 이 목록은 원래 업무의 실행 계획/원문을 재생성하지 않는다. 정확한 Source/Direction/Task/Operation 영수증을 읽을 다음 단계만 지정한다.
4. 후계 AI가 실제로 원래 Task를 수행했다는 결과 응답과 Windows 현장 E2E 증거는 없다.
5. 독립 체크아웃 테스트와 CI는 다른 AI/사람의 독립 코드 검수와 구분한다.

## 검수 판정 조건
전체 저장된 Work의 ID·Epoch/Generation 불변성, UNKNOWN 무재전송, 기존 8R Chain 회귀, 상태 조회 비침습성, 실제 Work/Task 목록 생략 표시, 배포 목록 일치 및 exact SHA CI 확인.
승인 전 main/LIVE는 그대로 유지.

# PR #476 검수 발견 사항 및 후속 격리 수정

기준 SHA: bd0ab1b0c4907a6798f781df6cf03940e9193b1d
검수 대상: PR #476 (base a2411ec, head bd0ab1b). 원본 PR/영수증은 보존.

## 발견 1: 원래 메시지 ID가 있지만 Operation ID가 비어 있는 경우
이전 next_safe_step은 dispatch_operation_id만 검사했고, dispatch_message_id가 존재해도 attempt=QUEUED면 ADOPT_QUEUED_GENERATION_ONLY_IF_NOT_DISPATCHED를 반환할 수 있었다.
후계 A가 이를 미전송 작업으로 잘못 읽지 않도록 어떤 영속 메시지 ID든 원래 영수증 대조 지시로 분류한다. assignment_state 또한 QUEUED인 경우에만 미전송 채택 후보로 표시한다.

## 발견 2: Snapshot과 후계 Inventory의 Epoch 경합
기존 Orchestration snapshot은 DB connection을 닫고 후계 Inventory를 별도 connection으로 읽으므로, 두 조회 사이에 새 Manager Epoch가 등록되면 ValueError로 상태 조회 자체가 중단될 수 있었다.
후계 Inventory 내부의 모든 SELECT는 하나의 SQLite BEGIN 읽기 스냅샷을 사용하고, Snapshot과 읽기 사이의 Epoch/Work 변경 오류는 EPOCH_CHANGED_RECHECK 상태로 반환하여 잘못된 작업 목록을 표시하지 않는다.

## 격리 회귀
진짜 미전송 vs 영속 메시지 ID 단독 보존/재조회, Dispatching assignment에서 queued attempt 판정, Epoch 변경 중 상태 조회의 안전한 실패, 기존 원장 ID/UNKNOWN 무재전송. 외부 RCC 호출 없음.

## 미완료 및 독립 검수 범위
이번 수정은 이미 준비된 후계 A가 안전하게 무엇을 읽을지 정하는 내부 읽기 전용 경계다. 새 후계 생성·Manager 활성 Epoch 실제 승계·실제 AI 업무 재개를 구현 또는 실증한 것으로 간주하지 않는다.
PR #476에 독립 리뷰 승인은 없었다. 별도 detached checkout의 테스트는 자기 재시험이며 타 AI/인간의 독립 승인과 별도다.
N40가 수정 중인 Chrome/RCC 실사용 동일 UUID 두 번째 전송 경로는 HOLD. N36/N37 완료 영수증·운영·UNKNOWN·N40/N42 공유 파일·원본 미커밋·main/LIVE 모두 보존.

## PR #476·#477 통합 검토 — 2026-11-11
PR #476 SHA 71a5efe: cross-session Watch와 corrupt JSON 독립 코드감사 재현, 수정 후보 CI 14/14 성공, 독립 재승인 없음.
PR #477 SHA ff58752: dispatch_message_id 단독 QUEUED 및 Snapshot-Epoch 경합 수정, CI 14/14 성공, 독립 승인 없음.
두 브랜치는 bd0ab1b에서 갈라졌으므로 clean integration worktree에서 합쳤고 generated component library는 실제 양쪽 수정 소스로 재생성.
추가 검토: 손상 JSON은 Work 귀속을 알 수 없으므로 다른 Work에 해당할 수 있는 전역 부패 건수로 scoped Manager 결과를 가리지 않고, Work만 확인되는 legacy Watch는 UNVERIFIED로 표기.
원본 PR, N40/N42 공유 파일, N36/N37 완료, UNKNOWN, 원본 미커밋, main/LIVE 보존. 실제 후계 업무 E2E/독립 승인 미완료.
