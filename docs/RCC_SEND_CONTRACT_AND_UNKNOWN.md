# RCC 메시지 전송 계약과 UNKNOWN 판정

## 정본 우선순위 (실행 전 필수)
1. BCT `bct_status`의 `relay_browser_usage`를 먼저 확인한다. 이 값은 LIVE MCP의 `bct_relay_browser` 도구 설명과 같은 `_CAPABILITY_USAGE["relay_browser"]`에서 생성된다.
2. 이 채팅/플러그인에 노출된 도구 설명이 위 값과 다르면 **클라이언트의 도구 메타데이터가 오래된 것**으로 분류한다. 새 명령을 추측하거나 설명을 근거로 전송하지 않는다. BCT Control 도구 새로 고침 후 실제 MCP 목록을 재대조한다.
3. 기존 탭(빈 ChatGPT 홈 포함)에 단일 메시지: `send-to-tab` + 정확한 `instance_id/session_id/tab_id/window_id/conversation_key/text`. 빈 홈은 `conversation_key=""`를 사용한다.
4. BCT가 `create-chat-window` 또는 `create-chat-tab`으로 **방금 생성한 탭**: 기존 생성 영수증의 `create_operation_id`로 `send-to-created-tab`을 사용한다. `create-and-send`는 레거시 조합 명령이며 기존 빈 탭의 기본 선택지가 아니다.
5. 매 전송은 사용자 승인된 Work와 새 유일 Operation ID로 1회 실행한다. 같은 텍스트를 다른 Operation ID로 다시 보내지 않는다.

## 오류 분류 (원인 단정 금지)
- 클라이언트 도구 호출 차단 + BCT `OPERATION_NOT_FOUND`: BCT 실행 전 중단. 이것만으로 RCC 전송 기능 전체가 불가능하다고 말하지 않는다. 우회하지 않고 현재 정본 명령 계약을 확인한다.
- BCT `NOT_APPLIED`: 전송 이전의 동일성·권한 거부가 증명된 경우. 실제 전송 실패 및 무효화를 구분한다.
- BCT `UNKNOWN`: 전송 효과가 있었는지 아직 확정되지 않은 상태이지, 실패나 성공이 아니다. **절대로 재전송 또는 강제 APPLIED로 바꾸지 않는다.**
- 빈 탭의 첫 전송 중 `CONVERSATION_IDENTITY_CHANGED`: 홈 `/`가 새 `/c/UUID`로 바뀌는 것은 정상 과정일 수 있다. UUID만으로 성공을 추정하지 않는다. 정확히 같은 대상 탭·원본 Operation·요청 해시·단일 사용자 턴이 확인된 경우에만 제출 확인 근거로 사용한다.

## UNKNOWN 예방과 회수
- BCT 전송 전 대상 식별·idle·입력창 점유 여부를 확인한다.
- RCC는 새 대화가 라우팅되는 동안 `relay:newChatStatus`의 **읽기 전용** 증거 확인을 사용한다. 이 경로의 지연 관찰 기간은 25초이며 `relay:newChatExecute`는 재호출하지 않는다.
- 대화 UUID가 먼저 생겨도 사용자 턴이 없거나 텍스트 없는 플레이스홀더만 있으면 대기한다. 다른 사용자 턴, 여러 후보, ID 불일치, 원문 불일치는 엄격하게 거부한다.
- 기간 내 정확한 제출 증거가 없으면 원본 UNKNOWN을 그대로 보존한다. 이후 같은 탭의 `read-latest-assistant`로 실제 응답을 확인할 수 있지만, 답변 원문만으로 저장된 UNKNOWN을 임의 변경하지 않는다. 별도 정식 reconciliation 증거가 없으면 결과는 '사용자 화면 전송 관측 / 원본 영수증 UNKNOWN'으로 구분 보고한다.

## 테스트 및 운영 경계
- `test_direct_tab_send.js`: 지연 14초 제출 증명은 SUBMITTED, 미증명 25초는 UNKNOWN, 두 경우 모두 Execute 정확히 1회.
- `test_issue57_bootstrap_identity.js`: 지연 사용자 턴/플레이스홀더 허용, 다른 턴·중복 후보 금지.
- `tests/test_mcp_integration.py`: MCP live 도구 설명과 `bct_status`/`bct_capabilities`의 계약 일치.
- 운영 Chrome/RCC/LIVE를 바꾸기 전 격리 회귀, PR CI, 정식 배포 및 물리 E2E를 별도로 완료한다.
