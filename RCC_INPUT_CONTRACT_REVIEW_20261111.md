# RCC 전송 인수 오류 재발 방지 — 격리 검수 보고서

## 확인된 사실
- 현재 공개 호출 경로는 bct_browser(work_id, operation_id, arguments:{command,...}); MCP arguments는 generic object.
- RCC 카탈로그는 공개 명령명/개요는 제공하나 기존에는 명령별 필수 인수가 빠져 있음.
- 별개 capabilities(tool_name='rcc_send_message_to_created_tab') 호출은 이 런타임에서 NOT_FOUND/TOOL_NOT_EXPOSED_BY_THIS_RUNTIME. 공개 명령을 각각 별도 MCP 도구로 오인하면 안 됨.
- 소스 src/bct/features/rcc.py 의 send-to-created-tab에서는 instance_id, session_id, tab_id, window_id, create_operation_id, text가 필수이고 timeout_s는 선택이다. creation_receipt/message는 해당 계약이 아님.
- 특정 기존 전송 Work dot-bct-roundtrip-speed-20261111, operation speed-first-send-01의 최신 BCT 영수증은 FINISHED/UNKNOWN (RCC_RESPONSE_TIMEOUT_AFTER_DISPATCH). 사용자 외부 관측은 도착 증거이나 기록상의 UNKNOWN을 강제 APPLIED로 재분류할 근거는 아님. 재전송 금지.
- RCC 자체 버그나 네트워크 병목 원인은 아직 확인되지 않음.

## 구현
- src/bct/features/rcc.py: rcc_send_message_to_created_tab 카탈로그 항목에 input_contract(필수/선택/금지/자료형/원래 영수증 규칙/호출 문법)를 추가함.
- validate_created_tab_send_input: 부작용 없는 사전 입력 검증 결과(누락·알 수 없는 키)를 반환함.
- BrowserFeature.prepare: create-bound send 대상에서 실제 instance 검증/효과 예약 이전에 해당 입력 오류를 구체적으로 반환함. 기존 전송/재조정 의미 변경 없음.
- 기존 roundtrip-fastpath commit 99a1b35 기능 유지.
- 계약 검증 범위는 이번 오류가 발생한 특정 명령에 한정. 다른 명령의 필수 스키마는 검토하지 않은 채 채워 넣지 않음.

## 적용 대상 구분
| 구성요소 | 이 후보 코드 변경 | 후속 실제 적용·확인 |
|---|---|---|
| BCT Core Python 명령 카탈로그/입력 사전 검증 | 변경함 | 정확 SHA 검수 후 Core 반영·재기동/표면 확인 (요청자 담당) |
| MCP 도구 수·개별 도구 스키마 | 변경하지 않음 | bct_browser generic object 유지. 별도 MCP 도구 노출은 별도 설계 결정이 필요하며 이 후보는 요구하지 않음 |
| RCC 확장 명령 wire/설치 | 변경하지 않음 | 이 코드 변경만으로 확장 업데이트는 불필요하나 실제 설치/명령 확인은 요청자 담당 |
| 공용 AGENTS/선언·가이드 | 변경하지 않음 | 문서 반영 위치 결정/적용은 요청자 담당. 이 보고서의 명령 계약을 참고 |
| MCP 도구 refresh/클라이언트 재연결 | 변경하지 않음 | 현재 노출 중인 도구와 카탈로그 갱신 확인은 요청자 담당 |

## 지연 분리
1. 발견: 카탈로그 조회 시작/응답 (Core 처리, 전송 별도 추적 필요)
2. 인수 검증: 순수 validate_created_tab_send_input 및 BrowserFeature.prepare (실측 계측 아직 미연결)
3. 전송: Core claim 예약, RCC relay dispatch, UI 처리, RCC 응답 (공통 trace ID 요구)
4. 결과: Operation 영수증 상태 read-only 조회/비용 (UNKNOWN은 중복 발송 불가)
기존 read fastpath는 discovery_ms/rcc_roundtrip_ms/total_ms 계측을 추가했지만 완전한 end-to-end 구간 계측은 아님. 사용자 관측 31초/25.6초/5.3초/0.202초는 원인 추정에 사용하지 않음.

## 테스트와 미완료
- 신규 test_rcc_created_tab_input_contract.py: 카탈로그 필수 인수·잘못된 키·Core prepare 조기 거절 및 독립 MCP 오인 방지 회귀 테스트.
- 기존 test_monitor_rcc_command_catalog.py, test_browser_capability_migration.py와 roundtrip fastpath 단위 테스트 정상.
- 실제 운영/설치/새로고침/물리 RCC 전송 테스트를 수행하지 않음.
- 모든 명령 스키마 전수화, discovery→receipt 공통 trace 계측, p50/p95 실측, 독립 Supervisor 검수는 별도 미완료.
- 정확 SHA 승인 전 main/LIVE 배포 금지.
