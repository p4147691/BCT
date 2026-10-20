# RCC Rebuild V2-2 — 플랫폼 경계 일괄 분리

상태: `SOURCE_COMPLETE / LOCAL_VERIFIED / RCC_LIVE_UNCHANGED`

## 범위

V2-1에서 남긴 활성 background의 Chrome 효과를 API 하나씩이 아니라 책임 단위 다섯 개로
한 번에 분리했다. Simple Relay V0, read-only state/probe/diagnostics, 기존 fail-closed 오류,
storage key, native command와 content message 이름은 바꾸지 않았다.

이번 단계에서는 `D:\ChromeExtensions\RCC\extension`, Chrome, Native Host, Relay binding,
열린 탭과 대화 storage를 변경하지 않았다.

## 플랫폼 모듈

- `platform/chrome_state_repository.js`: local/session storage의 유일한 background 접근 경계
- `platform/browser_gateway.js`: ChatGPT tab 조회, exact tab ID 조회, window 조회, content message,
  script 실행, receiver 상태 확인·한 번 주입·한 번 재시도
- `platform/native_transport.js`: Native Messaging 연결, port, 수신, disconnect와 bounded reconnect
- `platform/observation_gateway.js`: tab created/updated/removed listener 등록
- `platform/lifecycle.js`: runtime message, startup/installed, explicit reload 경계

`background_loader.js`는 위 다섯 모듈을 `background.js`보다 먼저 로드한다. 기존
`browser/read_adapter.js`와 tab/window mutation Adapter·영수증 계약은 source에 보존했지만
active loader에서는 불러오지 않는다.

## 구조 결과

- `background.js` 직접 `chrome.*` 호출: 24곳 → 0곳
- `background.js`: 2,080줄 → 1,969줄
- named function 및 top-level 변수의 선언 단독 참조: 0개
- receiver 주입 payload: 활성 manifest와 동일한 `relay_core.js`, `content.js`
- content script의 runtime transport는 V2-3 content 분리 대상으로 유지

background는 아직 도메인 service와 큰 native command route를 포함한다. 이를 이번 플랫폼
단계에서 억지로 나누지 않고 V2-3의 endpoint/Simple Relay/receipt/diagnostics 및 content router
분리 대상으로 남긴다.

## 검증

- 남은 RCC JavaScript 테스트 21개 전수: PASS
- 새 플랫폼 행위 테스트: storage/session, exact tab, receiver 1회 주입·1회 재시도,
  Native Messaging, observation listener, lifecycle 모두 PASS
- RCC focused Python 계약 18개: PASS
- `node --check` active/platform JavaScript: PASS
- `python -m compileall -q src tests`: PASS
- `git diff --check`: PASS

원격 CI 결과와 exact source commit은 commit 이후 추가한다. V2-4 이전에는 이 source payload를
LIVE RCC 설치본에 복사하거나 확장을 reload하지 않는다.
