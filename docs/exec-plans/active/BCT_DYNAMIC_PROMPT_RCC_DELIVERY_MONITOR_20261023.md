# BCT 공통 지시문 / 기존 RCC Delivery 연결 / RCC 모니터

상태: 메시지 설정 V2 격리 보완 중. 단일 Delivery 경로 LIVE 수락과 메시지 설정 수락을 구분함.
2026-10-23 (KST). 사용자 정책: RCC의 Chrome 기본 API 우선, Browser Bridge는 독립 로컬 연결 제품, CDP #282는 범용 조작 후보.

## 변경 및 설계

- RCC Native Host → Service Worker → Chrome tabs.sendMessage → Content Script는 기존 구현을 재사용. 별도 전송 엔진을 만들지 않음.
- 기존 BCT relay_browser delivery-start에 선택적 scope_id 추가. 지정하지 않으면 원문은 기존과 동일. 지정하면 현재 ACTIVE 그룹 구성원(N 표시/UUID/역할 태그), 단일 런타임 메시지 설정, 사용자의 작업 원문, 완료/반환 지침을 정확히 하나의 메시지로 BCT에서 컴파일.
- 컴파일된 텍스트에 SHA256 적용, 기존 Core Delivery Ledger와 RCC delivery-start 계약으로 바로 전달. 그룹에서 대상이 빠지면 제출 이전 차단. 그룹/설정이 바뀌어도 동일 delivery_id로 새 텍스트를 재전송하지 못하도록 기존 해시 불변성 유지.
- 역할 태그와 현재 그룹 명단은 LLM의 협업 참고 자료이지 별도 도구 권한이 아님. 실제 BCT Work 권한과 정확한 RCC 탭/세션은 기존 방식으로 각각 검사.
- Worker 결과는 이미 구현된 delivery-status → delivery-return → delivery-manager-status 경로로 전달. RETURNED는 Manager 대화에 사용자 턴을 보냈다는 의미이지 Manager가 후속 판단을 완료했다는 의미가 아님.
- PR #289 이후 delivery-return은 Worker 결과 원문과 프로젝트 문맥·Manager 지시를 한 반환 메시지로 조합한다. 메시지 의미는 relay-message-settings.json 한곳에서 읽으며 과거 manager/worker-relay-note.txt를 자동 삽입하지 않는다. Manager는 특정 상태 단어가 아니라 자연어 판단과 실제 BCT 실행으로 다음 행동을 증명한다. 과거 Orchestration marker/schema는 현재 메시지 형식의 요구사항이 아니다.
- delivery-preview는 실제 Delivery row나 RCC/Chrome 효과 없이 Worker 전달문과 Manager 반환문을 같은 조립기로 보여 준다.

## 고정 vs. 동적 지시

고정: Work 권한/UNKNOWN 재전송 금지/응답 계약/Delivery ID/원문 해시/JSON schema.
동적: 최신 그룹 ACTIVE 멤버, 역할 태그, 사용자 작업 목표 및 완료 기준, 역할별 추가 지시와 메시지 구성 설정. Worker 메시지 확정 전과 Manager 반환 조립 전 각각 최신값을 읽고 이미 준비·제출한 메시지는 바꾸지 않음.

## RCC 모니터 간헐적 UNAVAILABLE

현행 Monitor 전용 RCC probe 초기 timeout 0.25초, 재조회 0.12초, 한번 실패하면 30초 재확인 유예. 짧은 탐침 실패 자체가 OPEN인 RCC를 UNAVAILABLE로 보이게 할 가능성이 확인됨. 실제 Native Host 연결 장애 가능성까지 배제하거나 원인을 완전히 확정하지는 못함.

기존 PR #251 (94a945807053fba2378c36ef68953cf93e4eb13c)의 이미 구현된 분류를 **재사용**해 별도 중복 수정을 통합한다. 일시적 프로브 시간 초과는 PROBE_TIMEOUT/5초 후 재조회/0.35초 재확인, 실제 파이프 불가는 UNAVAILABLE/30초 기존 재확인, 잘못된 결과는 PROBE_ERROR로 구분한다. 초기 0.25초와 실제 파이프의 0.12초 상한은 유지한다. 프로브 갯수 제한, INFLIGHT 배제, 이전 정확한 탭의 stale-only 표시도 유지한다. 이는 RCC 자체 재시작이 아니라 모니터의 판정 수정이다. 별도 PR #251은 정식 수락·정리 전까지 OPEN을 유지한다.

## CDP PR #282

CDP는 별도의 기본 브라우저 검사·조작 영역으로 다룸. PR #282의 1회 제출 방식은 정확한 페이지·UUID·해시/연결 세대 검사가 장점이지만 Worker 응답 회수와 Manager 결정 소비는 범위 밖. 따라서 RCC의 정식 영속 대화 경로로 자동 편입하거나 자동 fallback을 만들지 않음. CDP 범용 운용에 재사용할 때 공식 Chrome DevTools MCP 제공 API 우선, 불가피한 특수 안전 가드만 평가. CI PASS/PR OPEN ≠ 운영 수락.

## 수락 경계

격리: 새 tests/test_relay_prompt_delivery.py로 BCT 생성 프롬프트와 기존 delivery-start/status/return/manager-status의 단일 ID, 동적 note 변경, 명단 이탈 차단과 중복 hash fence 검증. tests/test_monitor_runtime.py로 탐침 시간/재조회/캐시 검증. 전체 연관 회귀 및 CI 필요.

LIVE: 설정 미리보기 수락 뒤 N13→N14→N13의 각 user-turn / Worker 결과 전문 / 한 번의 Manager 반환 / Manager의 자연어 판단과 실제 새 Worker 업무 실행을 각각 확인한다. 특정 출력 단어, ACK 또는 계획 문장만으로 성공 처리하지 않는다. 기존 Work / UNKNOWN은 보존하고 재전송하지 않는다.

경로: src/bct/relay_prompt.py 공통 메시지 컴파일러와 미리보기; src/bct/relay_settings.py 단일 설정·catalog·CAS 변경안; src/bct/features/rcc.py의 선택적 delivery-start와 읽기 전용 delivery-preview. Browser Bridge는 별도 프로젝트로 보존하며 CDP는 필요할 때 사용할 수 있는 범용 브라우저 제어 수단이다.
