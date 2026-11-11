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
