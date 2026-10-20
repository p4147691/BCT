# RCC Rebuild V1 — 3단계 content protocol 호환성

상태: VALIDATED_NO_TAB_REFRESH_REQUIRED

`test_core_shadow_protocol_v3.js`는 기존 content `relay:activityProbe`의 generating,
connection, telemetry 응답과 background의 endpoint 반영·`coreShadow` state 출력을 고정한다.
해당 경로에는 executeScript, send-to-tab, composer 입력 또는 DOM mutation이 없다.

LIVE에서는 두 고정 대화의 receiver가 새 Shadow build로 read-only probe에 정상 응답했고,
Manager·Worker의 UUID·CONNECTED 상태·count가 3회 연속 일치했다. 따라서 IDLE/composer
검사 뒤의 수동 tab refresh는 필요하지 않았고 수행하지 않았다. Native Host, binding, storage,
메시지 전송도 변경하지 않았다.

다음 4단계는 Manager→Worker 원문 한 건의 실제 전송이므로 별도 사용자 승인이 필요하다.
