# BCT 공통 지시문 / 기존 RCC Delivery 연결 / RCC 모니터

상태: 메시지 설정과 릴레이 제어 설정 기반 구현 중. 설정 구조 수락과 실제 실행/LIVE 수락을 구분함.
2026-10-23 (KST). 현재 단계는 노드 제어가 아니라 경로·호출·인자·메시지를 런타임 설정으로 바꿀 수 있는 기반 구현이다.

## 변경 및 설계

- 현재 검증된 RCC Delivery 구현은 보존한다. CDP·Chrome API·BCT 기능도 금지하거나 자동 배제하지 않으며, 향후 명시적으로 등록한 실행 선택지 가운데 목적별 route로 고른다. 동일 메시지의 외부 효과는 한 실행 지점에서만 발생시킨다.
- 기존 BCT relay_browser delivery-start에 선택적 scope_id 추가. 지정하지 않으면 원문은 기존과 동일. 지정하면 현재 ACTIVE 그룹 구성원(N 표시/UUID/역할 태그), 단일 런타임 메시지 설정, 사용자의 작업 원문, 완료/반환 지침을 정확히 하나의 메시지로 BCT에서 컴파일.
- 컴파일된 텍스트에 SHA256 적용, 기존 Core Delivery Ledger와 RCC delivery-start 계약으로 바로 전달. 그룹에서 대상이 빠지면 제출 이전 차단. 그룹/설정이 바뀌어도 동일 delivery_id로 새 텍스트를 재전송하지 못하도록 기존 해시 불변성 유지.
- 역할 태그와 현재 그룹 명단은 LLM의 협업 참고 자료이지 별도 도구 권한이 아님. 실제 BCT Work 권한과 정확한 RCC 탭/세션은 기존 방식으로 각각 검사.
- Worker 결과는 이미 구현된 delivery-status → delivery-return → delivery-manager-status 경로로 전달. RETURNED는 Manager 대화에 사용자 턴을 보냈다는 의미이지 Manager가 후속 판단을 완료했다는 의미가 아님.
- PR #289 이후 delivery-return은 Worker 결과 원문과 프로젝트 문맥·Manager 지시를 한 반환 메시지로 조합한다. 메시지 의미는 relay-message-settings.json 한곳에서 읽으며 과거 manager/worker-relay-note.txt를 자동 삽입하지 않는다. Manager는 특정 상태 단어가 아니라 자연어 판단과 실제 BCT 실행으로 다음 행동을 증명한다. 과거 Orchestration marker/schema는 현재 메시지 형식의 요구사항이 아니다.
- delivery-preview는 실제 Delivery row나 RCC/Chrome 효과 없이 Worker 전달문과 Manager 반환문을 같은 조립기로 보여 준다.
- 과거 scope 표시명·Project Run 목표가 현재 협업 목적과 다를 수 있으므로 project_display_name과 project_goal을 메시지 설정으로 덮어쓸 수 있다. 이는 메시지 문맥만 바꾸며 scope identity와 기존 기록을 수정하지 않는다.
- 같은 운영 JSON의 선택적 `control` 구역은 재사용 함수(`driver`/`call`/effect/인자), 단계 그래프, 결과별 다음 단계, `max_steps`, 목적별 선택 route와 프로젝트 override를 표현한다. AI는 전체 파일을 다시 쓰지 않고 중첩 merge-patch 변경안과 정확한 CAS SHA를 만든다.
- 현재 V1 제어 설정은 검증·해석·미리보기만 제공한다. 실행기 연결 전에는 어떤 driver/call도 호출하지 않으며, 설정 문자열만으로 실행 권한이나 기능 존재가 생기지 않는다.

## 고정 vs. 동적 지시

고정: Work 권한/UNKNOWN 재전송 금지/응답 계약/Delivery ID/원문 해시/JSON schema.
동적: 최신 그룹 ACTIVE 멤버, 역할 태그, 사용자 작업 목표 및 완료 기준, 역할별 추가 지시와 메시지 구성, 등록 함수의 선택·호출 이름·인자, route와 단계 순서. 새 흐름 시작 전 최신값을 읽고 이미 준비·시작·제출한 흐름은 바꾸지 않음.

## RCC 모니터 간헐적 UNAVAILABLE

현행 Monitor 전용 RCC probe 초기 timeout 0.25초, 재조회 0.12초, 한번 실패하면 30초 재확인 유예. 짧은 탐침 실패 자체가 OPEN인 RCC를 UNAVAILABLE로 보이게 할 가능성이 확인됨. 실제 Native Host 연결 장애 가능성까지 배제하거나 원인을 완전히 확정하지는 못함.

기존 PR #251 (94a945807053fba2378c36ef68953cf93e4eb13c)의 이미 구현된 분류를 **재사용**해 별도 중복 수정을 통합한다. 일시적 프로브 시간 초과는 PROBE_TIMEOUT/5초 후 재조회/0.35초 재확인, 실제 파이프 불가는 UNAVAILABLE/30초 기존 재확인, 잘못된 결과는 PROBE_ERROR로 구분한다. 초기 0.25초와 실제 파이프의 0.12초 상한은 유지한다. 프로브 갯수 제한, INFLIGHT 배제, 이전 정확한 탭의 stale-only 표시도 유지한다. 이는 RCC 자체 재시작이 아니라 모니터의 판정 수정이다. 별도 PR #251은 정식 수락·정리 전까지 OPEN을 유지한다.

## CDP PR #282

PR #282의 1회 제출 방식은 정확한 페이지·UUID·해시/연결 세대 검사가 장점이지만 Worker 응답 회수와 Manager 결정 소비는 그 PR의 범위 밖이다. CDP를 제외하거나 RCC에 무조건 종속시키지 않는다. 공식 Chrome DevTools MCP 제공 기능을 등록 실행 선택지로 연결할 필요가 생기면 현재 route 설정에서 선택할 수 있게 하되, 중복 제출·UNKNOWN 재전송 방지는 실행 경계에서 유지한다. CI PASS/PR OPEN ≠ 운영 수락이다.

## 수락 경계

격리: 새 tests/test_relay_prompt_delivery.py로 BCT 생성 프롬프트와 기존 delivery-start/status/return/manager-status의 단일 ID, 동적 note 변경, 명단 이탈 차단과 중복 hash fence 검증. tests/test_monitor_runtime.py로 탐침 시간/재조회/캐시 검증. 전체 연관 회귀 및 CI 필요.

LIVE: 설정 미리보기 수락 뒤 N13→N14→N13의 각 user-turn / Worker 결과 전문 / 한 번의 Manager 반환 / Manager의 자연어 판단과 실제 새 Worker 업무 실행을 각각 확인한다. 특정 출력 단어, ACK 또는 계획 문장만으로 성공 처리하지 않는다. 기존 Work / UNKNOWN은 보존하고 재전송하지 않는다.

경로: src/bct/relay_prompt.py 공통 메시지 컴파일러와 미리보기; src/bct/relay_settings.py 단일 설정·catalog·CAS 변경안; src/bct/relay_control.py 제어 graph 검증과 resolved preview; src/bct/features/rcc.py의 기존 delivery-start와 읽기 전용 delivery-preview. 현재 설정 단계에서는 브라우저 통로나 대화 노드를 시험하지 않는다.
