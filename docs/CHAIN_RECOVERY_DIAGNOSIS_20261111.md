# BCT Chain Recipe 자동 복구 — 영수증 우선 진단·계속 계획
기준일: 2026-11-11 KST
정본 Work: bct-supervisor-resilient-chain-20261110
격리 소스 기준: f8402f58bba2d48764c43628b9101f706ab8bc7c
계획 상태: DIAGNOSED / PARTIAL IMPLEMENTATION / LIVE HOLD

## 증거 (검증됨)
- 운영 Core: OK, release 76e5cb1, main clean; 후보 코드 운영 미배포.
- N36 Manager = 6af1bfb1-2d8c-83ee-8ee1-bcd1c9136501, N37 Worker = 6af1dcc2-f474-83ee-8a6d-691e265e8892.
- 원래 E2E Work = chain-recipe-live-e2e-20261109-01; Direction = direction-f87768b9673b3ce997f2a699; Task = chain-recipe-live-e2e-final-1; Generation = 1.
- Watch = RETURNED_TO_MANAGER, 결과 응답 SHA = 2591deba4186faf55a29e0c66eb72dd2f722bf63ef3dee0bfc5bc29200e0d435.
- 최초 송신/Watch APPLIED, 최종 Manager 반환 Operation delayed-manager-c779ccf9de4b27c023b5b6d1 APPLIED.
- 2026-11-11 최신 RCC/Monitor에서 두 노드 모두 CONFIRMED/IDLE/연결 정상, 정확한 RCC session/tab/window 확인.
- N37 마지막 AI 반환 = CHAIN_RECIPE_LIVE_E2E_PASS + NEXT TASK — MANAGER; N36 마지막 AI 응답 = CHAIN_RECIPE_LIVE_E2E_PASS.
- 해당 Work의 Recovery inbox는 비어 있음; 새 Manager 승계나 노드 Replace가 요구된 증거 없음.
- Direction projection은 여전히 IN_PROGRESS/WAIT_FOR_RETURN: 실제 완료 Watch와 불일치. 최종 실행 계획 점검은 PLAN_MISSING/PROGRESS_MISSING (해당 테스트는 노드에게 도구 사용하지 말도록 명시했으므로 결함 여부 분리).
- 초기 과거 Operation worker-8eee4069989954ed2060-send 는 UNKNOWN(RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH); reconcile은 FAILED(INSUFFICIENT). 절대 재전송 금지.

## 실행 계획
1. [완료] 기존 Work·Direction·Task·Watch·Operation·Recovery Inbox와 RCC 마지막 AI 응답 대조.
2. [완료] N36/N37 장애 아님, 마지막 반환 실제 전달 완료; 노드 교체·E2E 재전송 불필요.
3. [진행] Direction/Watch 완료 상태 불일치의 원인, 원본 영수증만으로 안전하게 close 가능한 범위 코드·회귀 검토. 기존 DB 및 역사 영수증 직접 수정하지 않음.
4. [대기] 자동 복구 후보 f8402f5를 별도 격리 worktree에서 원 탭/RCC identity absence, 활성 Manager Epoch, 후계 SELF/MANAGER 실제 재개 영수증 보완.
5. [의존] N40 동일 UUID 두번째 전송 RELAY_EDITOR_FOCUS_OR_CARET_INVALID 수정 완료 전 해당 RCC 전송 경로 E2E 재실행 금지. N40/N42 공유 파일 및 미커밋 덮어쓰기 금지.
6. [대기] 장애 주입 격리 Windows E2E, 독립 detached review, exact-SHA GitHub CI. 승인 전 main/LIVE/운영 DB 무변경.

## 정책/복구 원칙
자동 복구가 기본, 수동 사용자 지시는 실패 시 재진입 경로.
같은 UUID 재연결 우선. 정확한 Work/Task/Generation/Watch/Operation/role/Epoch 보존.
UNKNOWN은 기존 Operation에서 대조하고 새 ID로 반복 전송하지 않음.
일반 Worker/전역 S의 임의 Manager 승격 금지. 새로운 사용자 권한·단계·ID 입력 장벽 금지.
완료·미완료·차단과 실제 영수증을 각각 보고.

## 격리 진행 보완 — 2026-11-11
- 정확한 N36/N37 마지막 RCC 답변 재확인: 둘 다 CONFIRMED·IDLE; N36 마지막 CHAIN_RECIPE_LIVE_E2E_PASS, N37 마지막 반환 PASS.
- bct_chain_branch(action=tree)는 최종 Work의 RETURNED_TO_MANAGER를 WAITING_INPUT/MANAGER_REENTER_CHAIN_RECIPE로 이미 정확히 표시.
- 개별 bct_get_direction만 저장된 IN_PROGRESS/WAIT_FOR_RETURN을 보여준 조회 불일치. 원본 DB 영수증은 수정하지 않고, exact Work+Task의 durable Watch에서 읽기 전용 projection을 계산하도록 격리 수정.
- 최초 N36/N37 E2E는 정상 완료로 관찰되므로 노드 Check/Replace/전송 필요 없음. 이전 UNKNOWN 원본 영수증은 계속 보존.
- 옛 탭 부재 대비: 기존 RECHECK의 NEW_CHAT_REQUIRED가 정확히 확인된 경우만 동일 Work+대화망의 FRESH/CONFIRMED RCC peer 창을 유일하게 식별하고 재사용; 다른 Work·여러 창·신원 미확인이면 효과 없이 보류.
- N40 동일 UUID 두 번째 전송 RELAY_EDITOR_FOCUS_OR_CARET_INVALID 경로는 여전히 의존 차단. Windows 실사용 신규 발송·후계 재개 E2E 재실행하지 않음.
- 다음 단계: 회귀·독립 검수·정확 SHA CI 후 미완료 Manager Epoch/실제 후계 작업 재개 E2E를 별도 확인; main/LIVE 불변.
