# RCC Rebuild V2-3 — 활성 domain·content 일괄 분리

상태: `SOURCE_COMPLETE / CI_PASS / RCC_LIVE_UNCHANGED`

## 범위

V2-2에서 플랫폼 효과를 분리한 뒤 남아 있던 background 도메인과 content 활성 경로를 책임별
파일로 한 번에 옮겼다. 원문, conversation UUID 의미, storage key, native/runtime/content wire
message, Simple Relay receipt와 기존 fail-closed 오류 계약은 바꾸지 않았다.

이번 단계에서는 `D:\ChromeExtensions\RCC\extension`, Chrome, Native Host, Relay binding,
열린 탭과 대화 storage를 변경하지 않았다.

## background 구조

- `boot/platform_context.js`: 플랫폼 구현 조립과 content receiver 파일 순서
- `domain/state_service.js`: 기존 local state shape와 storage key
- `domain/endpoint_service.js`: exact conversation endpoint, presence, snapshot, receiver 확인
- `domain/simple_relay_receipts.js`: hash, intent·terminal receipt 저장과 공개 projection
- `domain/simple_relay_service.js`: bind, Manager→Worker send, Worker→Manager return
- `domain/diagnostic_support.js`: exact tab DOM recovery와 registration read support
- `domain/readonly_diagnostics.js`: 허용된 native read-only 진단과 command route
- `domain/runtime_message_service.js`: pending/state/activity runtime read route
- `boot/background_app.js`: transport와 listener 조립·시작

`background.js`는 조립된 app을 시작하는 3줄 진입점이다. domain 파일에는 직접 `chrome.*` 접근이
없으며 V2-2 platform 경계를 통해서만 효과를 사용한다.

## content 구조

- `content/conversation_dom.js`: editor, turn, assistant, generation과 connection DOM 판별
- `content/simple_relay_executor.js`: 원문 submit, exact turn 확인과 reply 원문 읽기
- `content/content_router.js`: 활성 message 다섯 종류의 단일 receiver
- `content/activity_reporter.js`: telemetry, generation/readiness/user-attention 관측

manifest와 receiver 주입은 위 파일을 같은 의존 순서로 로드하고 마지막에 3줄 `content.js`
assembly marker를 실행한다. 기존 content 구현은 책임 경계로 이동했으며 route 이름이나 반환 shape를
바꾸지 않았다.

## 구조 결과

- `background.js`: 1,969줄 → 3줄
- `content.js`: 1,780줄 → 3줄
- active bundle의 호출자 없는 named function: 0개
- active bundle의 호출자 없는 top-level 변수: 0개
- 이전·현재 native command 15개, runtime/content message 8개 집합: 동일
- storage key와 Simple Relay 원문·UUID·receipt 계약: 동일
- optional browser management Adapter: source 보존, active loader 제외 유지

## 검증

- RCC JavaScript 테스트 23개 전수: PASS
- 새 active bundle 실제 순차 로딩 시험: Native ready, endpoint snapshot, content receiver 1개 PASS
- 새 domain/content 구조·zero-caller 계약: PASS
- focused Python 계약 18개: PASS
- 전체 BCT Python 회귀 842개: PASS
- active JavaScript 30개 syntax, `python -m compileall -q src tests`, `git diff --check`: PASS

exact source commit은 `62317038bd50b848f6d49714029630c3fda03040`이며 GitHub Actions
`BCT CI` run `39393918353`의 preflight, core 4개 shard, browser-bridge가 모두 통과했다.
V2-4 통합 Release Candidate 검증 전에는 이 source payload를 LIVE RCC 설치본에 복사하거나
확장을 reload하지 않는다.
