# RCC Rebuild V1 — 1단계 source-only Core 분리

상태: STAGE_1_COMPLETED_NO_LIVE_PAYLOAD_CHANGE

기록 시각: 2026-10-20 09:49 KST

## 변경 범위

새 Core 후보를 source의 modules/rcc/extension/core 아래에만 추가했다. manifest,
background_loader.js, background.js, content.js, Native Host, Chrome storage, Relay binding은
변경하지 않았다.

| 모듈 | 책임 | 변경 효과 |
| --- | --- | --- |
| core/identity.js | ChatGPT URL에서 conversation UUID 해석, exact tab 후보 판정 | 없음. 순수 함수 |
| core/state.js | exact tab/endpoint를 CONNECTED, MISSING, AMBIGUOUS, BUSY 등으로 판정 | 없음. 순수 함수 |
| core/conversation.js | 제출 intent, ACK, 새 응답 read 결과 계약 | 없음. 순수 함수 |
| core/transport.js | read-only state 요청 모양, 전송 결과와 재시도 경계 | 없음. 순수 함수 |

모든 Core 모듈은 chrome API, DOM, storage, pipe write, tab injection, reload를 호출하지 않는다.
특히 UNKNOWN은 자동 재시도를 허용하지 않고, NOT_APPLIED도 새 operation 및 새 precondition 확인
없이는 다시 보낼 수 없게 계약을 분리했다.

## 기존 동작과의 관계

현재 실행 경로는 그대로다.

~~~text
background_loader
  → relay_core / simple_relay_v0 / act_bridge
  → background
  → 기존 content scripts
~~~

새 Core는 위 경로에 import되지 않는다. 기존 selector, Native Messaging wire protocol, Simple Relay
receipt 형식, existing content.js DOM adapter를 바꾸지 않았다. 다음 단계에서 read-only Shadow로
연결하기 전까지 Core는 test 대상일 뿐 실행 대상이 아니다.

## 검증

- test_rcc_core_v1.js: PASS
- test_simple_relay_v0.js: PASS
- test_relay_core.js: PASS
- test_relay_lightweight_identity.js: PASS
- test_window_state_presence.js: PASS
- test_durable_execution_retirement.js: PASS
- test_identity_guard.js: PASS
- test_full_result_capture.js: PASS
- test_route_turn_deduplication.js: PASS
- Node syntax check, git diff --check: PASS

추가로 LIVE 설치 경로에는 core 디렉터리가 존재하지 않음을 확인했고, 변경하지 않은 active
content.js의 source/LIVE SHA-256이 같음을 확인했다.

## 다음 경계

2단계는 새 Core 파일을 설치 payload에 후보로 배치하고, same-ID extension reload 뒤 read-only
Shadow를 실행해야 한다. 따라서 이 단계는 현재 source-only 승인 범위를 넘어선다. 2단계에서는
전송·storage migration·tab navigation을 하지 않지만 installed payload 변경과 extension reload는
명시적으로 수행해야 한다.
