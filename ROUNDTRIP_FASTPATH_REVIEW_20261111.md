# BCT RCC 조회 왕복 fast path — 격리 검수 자료

## 경계
- 기준 local main: 76e5cb1c333a2a22cd0765e729af71ded10612d9
- isolated worktree: D:\BCT\worktrees\rcc-roundtrip-fastpath-20261111
- Work: bct-rcc-roundtrip-latency-isolated-20261111
- main, LIVE, RCC 설치/명령 노출/새로고침, N39/N40, 기존 UNKNOWN 및 영수증 변경 금지.

## 변경
1. SendDelayedMessageService.latest에 verified_target(동일 instance/UUID/session/tab/window) 선택 경로 추가. 없으면 기존 global discovery 유지. 불일치 시 즉시 실패, 다른 창 선택/재전송 없음.
2. 최신 응답 읽기의 discover/직접 RCC 호출/전체 경과 시간 측정 sink 추가. 서버 내부 처리 및 호스트 전송은 이 값에 합산되므로 실제 분리에는 같은 trace ID의 Core/RCC 서버 계측 연동 필요.
3. latest_many로 검증된 서로 다른 대상의 read-only 조회를 유계 ThreadPoolExecutor로 병렬 실행. 순서 유지, 중복 차단, 예외 전파, 자동 재시도 없음.

## 테스트
- 신규: test_rcc_roundtrip_fastpath.py 6 PASS (mock 계약/동시성)
- 기존: test_send_delayed_message.py 33 PASS; test_delayed_send_rcc_flow.py 13 PASS; test_rcc_response_read_contract.py 6 PASS
- compileall PASS; git diff --check PASS.
- 실환경 RCC 전송 효과는 시험하지 않았음. 실제 지연 개선량·p50/p95 및 원인 판정은 미검증.
- 기존 send/Watch 호출자가 verified_target와 timing_sink를 넘기는 통합 연결은 별도 단계. 지금은 선택 API만 제공하며 기존 기본 호출 동작을 바꾸지 않음.

## 독립 검수와 다음 단계
- 정확한 trusted Work/Task/Generation 영수증에서 identity를 추출하고 현재 instance/session 일치 여부 검증 후 선택 fastpath로 전달하는 caller 연결 검토.
- 호출 수(전역 discovery 내부 포함), 클라이언트 API 왕복, Core ASGI handler, RCC relay, UI DOM 시간을 동일 trace_id로 상관 계측.
- 동일 read-only 대상에서 baseline/fastpath 번갈아 p50/p95, 호출 수 비교; busy N39/N40 관측/전송 금지.
- executor 공유 client thread-safety 확인 후 병렬 경로 사용처 도입. 아직 production caller 연결하지 않음.
- 정확 SHA 및 독립 Supervisor 승인 전 main/LIVE 불가. guarded CI first 권장.
