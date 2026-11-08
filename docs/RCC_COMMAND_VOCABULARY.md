# RCC 공개 명령 어휘

이 문서는 BCT가 공개하는 RCC 명령의 표시 이름을 정리한다. `rcc_`는 Chrome
확장에 구현된 직접 동작이고, `bct_`는 Work·Operation·영수증·결과 판정을
조합하는 BCT 절차다. 두 접두사는 권한 등급이 아니라 구현 위치를 나타낸다.

공개 이름은 `<origin>_<verb>_<target>[_to_<destination>]` 규칙을 따른다.
기존 `rcc_<옛 이름>` 및 하이픈 wire 이름은 이미 저장된 영수증과 설치된 확장을
위해 호환 별칭으로만 유지한다. 새 호출과 레시피는 아래의 정식 이름을 사용한다.

## 상태와 대상

- `rcc_get_extension_state` — 확장 상태를 읽는다.
- `rcc_get_extension_connection` — 확장이 지금 한 번 응답하는지 확인한다.
- `rcc_get_target_availability` — 지정 대상의 현재 가용 정보를 읽는다.
- `rcc_check_target_tab_response` — 지정 탭이 지금 응답하는지 확인한다.
- `rcc_check_chat_tab_responses` — 열린 ChatGPT 탭들의 응답을 일괄 확인한다.
- `rcc_get_tab`, `rcc_list_windows`, `rcc_get_window` — 정확한 탭·창을 읽는다.
- `rcc_list_tab_groups`, `rcc_get_tab_group` — 탭 그룹을 읽는다.
- `rcc_get_operation_result` — 하나의 기존 Operation 영수증 결과를 읽는다.
- `bct_discover_target` — BCT가 다음 조합 단계에 쓸 불투명 대상 참조를 찾는다.

## 진단과 대화 읽기

- `rcc_get_conversation_activity` — 생성·활동 상태를 읽는다.
- `rcc_get_composer_state` — 입력창 상태를 읽는다.
- `rcc_get_conversation_ui_diagnostics` — 대화 UI 진단 정보를 읽는다.
- `rcc_get_conversation_api_response` — API 응답 진단 정보를 읽는다.
- `rcc_get_conversation_capture` — 이미 수집된 대화 캡처를 읽는다.
- `rcc_get_latest_assistant_message` — 정확한 UUID 대화의 마지막 AI 답변만 읽는다.

## Chrome 배치와 대화 표시

- `rcc_create_chat_tab`, `rcc_create_chat_window` — 새 ChatGPT 탭 또는 창을 만든다.
- `rcc_move_tab_to_window`, `rcc_move_tab_group_to_window` — 탭 또는 그룹을 창으로 옮긴다.
- `rcc_create_tab_group_from_tabs` — 지정 탭들로 그룹을 만든다.
- `rcc_move_tab_to_group`, `rcc_move_tab_from_group` — 탭을 그룹에 넣거나 밖으로 옮긴다. 탭을 삭제하지 않는다.
- `rcc_update_tab_group`, `rcc_close_conversation_tab`, `rcc_reload_extension` — 그룹·대화 탭·설치된 확장을 정비한다.
- `rcc_bind_conversation_to_node` — 정확한 대화 UUID를 논리 노드 메타데이터에 연결한다.
- `rcc_rename_conversation`, `rcc_get_conversation_rename_evidence`, `rcc_update_conversation_favicon` — 대화 이름·이름 변경 증빙·탭 파비콘을 다룬다.

## 메시지와 새 대화

- `rcc_send_message` — RCC 직접 메시지 전송이다.
- `rcc_send_message_to_tab` — 정확한 기존 탭으로 보낸다.
- `rcc_send_message_to_created_tab` — 이미 만든 탭으로 첫 메시지를 보낸다.
- `rcc_create_chat_and_send_message` — 새 대화를 만들고 첫 메시지를 보낸다.
- `bct_send_message` — 정확한 Work·Operation·대상·영수증과 함께 보낸다.
- `bct_create_chat_and_send_message` — BCT 절차로 새 대화 생성과 첫 전송을 묶는다.
- `bct_send_message_to_self`, `bct_continue_node_message` — 현재 노드의 자기 메시지·연속 실행 절차다.

## 전달 프로세스

- `rcc_start_delivery_to_worker` — Manager에서 Worker로 하나의 전달을 시작한다.
- `rcc_get_delivery_evidence` — 해당 전달의 현재 증빙과 상태를 읽고 영수증에 반영한다.
- `rcc_get_delivery_response` — Worker 응답 원문과 해시를 읽는다.
- `rcc_return_delivery_to_manager` — Worker 결과를 Manager로 반환한다.
- `rcc_get_delivery_manager_response` — 반환 후 Manager의 다음 응답을 읽는다.
- `bct_get_delivery_result` — 영수증을 결합해 `APPLIED`, `NOT_APPLIED`, `UNKNOWN`, `PENDING`을 판정한다. `UNKNOWN`을 재전송하지 않는다.
- `rcc_cancel_delivery`, `rcc_get_delivery_recovery_evidence`, `bct_preview_delivery_message` — 제출 전 취소, 복구 증빙, 전송 전 미리보기다.

## 복구와 정비

- `bct_reconcile_message_send`, `bct_reconcile_created_chat_message_send`, `bct_reconcile_created_chat_and_send` — 같은 원래 Operation 영수증을 재확인한다. 새 전송을 만들지 않는다.
- `bct_get_created_chat_send_result` — 생성·전송 Operation의 결과를 읽는다.
- `bct_get_conversation_rename_evidence`, `bct_reconcile_conversation_rename`, `bct_reclassify_rename_claim`, `bct_quarantine_legacy_rename_claim` — 과거 이름 변경 영수증을 안전하게 정리한다.
- `rcc_retire_delivery_draft`, `rcc_retire_recovered_delivery_execution` — 확인된 고아 초안·복구 실행만 정리한다.

## 호환: 이전 Simple Relay

- `rcc_bind_simple_relay`
- `rcc_send_simple_relay_message`
- `rcc_return_simple_relay_response`

이는 고정된 Manager–Worker 한 쌍을 저장하는 V0 호환 방식이다. 새 작업의 표준
레시피에는 넣지 않으며, 기존 기록을 읽고 복구하기 위해서만 유지한다.
