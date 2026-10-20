# BCT Monitor 노드·썸네일 표시 — RCC 통합 격리 검증

상태: `NODE_NAVIGATION_SOURCE_VALIDATED / CI_AND_LIVE_RELOAD_PENDING`

## 2026-10-20 노드 카드 → 정확한 브라우저 창 상호작용

Monitor 상단 BCT/RCC 노드 카드에 두 가지 사용자 동작을 추가했다.

- 한 번 클릭하면 현재 session의 검증된 `window_id → HWND` 대조 결과와 일치하는 데스크톱
  썸네일/창 preview에만 노란 테두리를 표시한다. 같은 Chrome 창의 여러 대화 노드는 같은
  물리 창을 가리키며, 다른 창이나 탭을 추측하지 않는다.
- 더블클릭하면 Native Host에서 모든 가상 데스크톱의 실제 HWND를 다시 찾은 뒤 정확히 일치한
  데스크톱으로 전환하고 `restoreForegroundWindow`로 그 Chrome 창을 활성화한다. HWND를 찾지
  못하면 데스크톱 전환과 창 활성화를 모두 실행하지 않는다.

효과 순서는 독립 `monitor-bct-node-interaction.js` 계약으로 분리했다. focused 계약, Monitor
구조/문법, 기존 번호·최소화·SVG·backpressure·current-session HWND 회귀와 현재 LIVE의 읽기
전용 대조가 통과했다. 현재 실측은 ChatGPT 탭 3개, 물리 ChatGPT Chrome 창 1개, exact HWND
binding 1개, rejected 0개다. source base는 `0645a13839467387aa7b810d1b81593aef9efd5d`이며
아직 GitHub main, 설치 Monitor, 실행 renderer에는 이 상호작용을 적용하지 않았다.

인수인계된 PR #247 (`a03ecea468ee7bd8997d430a72b99f6ba3635137`)과 PR #251
(`94a945807053fba2378c36ef68953cf93e4eb13c`)은 각각 기존 CI SUCCESS와 현재
`MERGEABLE/CLEAN`을 읽기 전용으로 재확인했다. 둘 다 별도 병합 승인이 없으므로 OPEN 상태를
유지하며, 과거 UNKNOWN의 실제 외부 결과도 미확정 상태를 보존한다.

## 2026-10-20 통합 결함 재진단 및 source 보수

사용자 화면에서 이름 변경 실패, 열린 ChatGPT 썸네일 번호 누락, 최소화 번호 누락이 함께
재현됐다. 세 현상은 CSS 한 곳의 문제가 아니었다.

- 설치 디렉터리는 새 payload였지만 실행 renderer는 `2.0.6`이었다. 기존 배포 gate는 옛
  renderer가 새 token만 ACK해도 reload 성공으로 오판했다. 이제 버전 또는 token 변경을 본
  renderer가 실제 `monitor-reload-extension`을 요청하고, publish/check 스크립트는 exact
  manifest version + token + publish 이후의 fresh shared-runtime telemetry까지 일치해야만
  성공한다.
- BCT Monitor의 bounded RCC 조회가 한 번 timeout되면 `tabs: []`를 반환해 검증된 노드 목록과
  배지를 지웠다. 이제 마지막 검증 row의 tab identity를 `cached:true`, state
  `UNAVAILABLE/UNKNOWN`으로만 유지한다. stale 관측을 LIVE로 위장하지 않지만 표시 identity는
  보존한다.
- RCC V2 legacy prune에서 `rename-conversation` handler와 content route가 제거됐지만 Monitor
  UI는 남아 있었다. RC3는 이 한 기능만 `domain/conversation_rename_service.js`와
  `content/conversation_rename.js`로 복구한다. exact session/tab/conversation, PREPARED/terminal
  rename ledger, APPLIED/NOT_APPLIED/UNKNOWN 분류, terminal replay 금지를 사용하며 다른 legacy
  mutation은 계속 차단한다.

열린 번호는 썸네일 내부 overlay, 최소화 번호만 데스크톱 썸네일 아래 정보 행이라는 계약은
변경하지 않았다. source 회귀에서 이 계약과 재로드 검증 계약이 PASS했다. RCC RC3는 48파일,
aggregate `9ae94c72398d96ee01a6812478fce23972b76ea2bc42f783099e67b1fb73fd62`이며
RCC Node 전체 24개와 관련 Python 77개가 PASS했다. 아직 GitHub CI, BCT Core 배포, RCC/Monitor
설치본 적용과 loaded-runtime LIVE E2E는 수행 전이다. 기존 `FINISHED/UNKNOWN` rename 작업은
효과가 부정되지 않았으므로 재실행·강제 claim 해제하지 않는다.

## 범위와 기준

- 통합 기준 main: `8d7f9f57658cad855f15fcf0ee582b62f4a5ce5b`
- 반영 후보: `593e52b0e44bc76cdf69b7ff4b530d647ed41d56`
- 격리 branch: `feat/monitor-rcc-display-integration-20261020`
- 공유 source, GitHub main, 설치 Monitor, RCC, Native Host, Chrome, relay, tunnel은 변경하지 않는다.

RCC V2가 수정한 `simple_relay_executor`, `simple_relay_service`, release manifest와 후보의 Monitor
변경 파일은 겹치지 않는다. 이 후보는 Monitor 표시·읽기 전용 관측만 다루며 Browser API 조작,
RCC relay, Wakeup Relay와 Native Host의 효과 경계를 추가하지 않는다.

## 수락 계약

1. `N1` 등의 번호는 BCT/RCC가 제공한 `node_label`만 사용한다.
2. `N?`는 `https://chatgpt.com` 또는 `https://chat.openai.com`의 RCC 관측 탭이지만 `/c/<key>`와
   등록 번호가 아직 없는 경우에만 표시한다.
3. 일반 Chrome 탭·다른 사이트·다른 앱 창은 Monitor 노드나 `N?` 대상이 아니다.
4. window ID와 HWND가 정확히 하나로 대조될 때만 썸네일에 번호를 붙인다. 대조 실패는
   썸네일 배지 생략이며 노드 목록·제목·번호를 지우는 이유가 아니다.
5. 최소화·데스크톱 위치는 Native Host 관측값만 쓴다. 두 개까지 표시하고 셋 이상은 `…`을 붙인다.
6. PROTECTED 자물쇠는 이번 후보에서 표시 상태일 뿐 실제 자동 조작 차단으로 주장하지 않는다.

## 반영한 최소 보완

후보의 `monitor-bct-shell.js`는 이전에 RCC instance의 모든 탭을 window-node로 투영했다. 이를
지원 ChatGPT host만 허용하도록 좁혔다. 따라서 YouTube 등 다른 탭은 `N?`로 표시될 수 없다.
`check_monitor_bct_shell.js`에 ChatGPT 루트 탭의 pending `N?`와 비-ChatGPT 탭 제외 회귀를 추가했다.

## 격리 검증 결과

- Monitor BCT shell, multi-tab thumbnail label, minimized `2 3 …`, capture route, thumbnail cache,
  node binding idempotence: PASS
- organization model, Monitor structure, active JS syntax, `git diff --check`: PASS
- 현재 BCT `/monitor/state`: service `OK`, RCC ChatGPT tabs 6개, 등록 `N#` labels 6개, Chrome
  window IDs 3개 확인
- 현재 등록 Native Host: `getDesktopVisualSnapshot` PASS, `getAllChromeWindowHandles` 12개 PASS

## 실제 HWND E2E가 아직 아닌 이유

현재 BCT `/monitor/state`는 RCC 탭·번호를 제공하지만 `organization.browser_nodes`와 `endpoints`의
`window_id → hwnd` 대조 데이터를 제공하지 않는다. 따라서 세 Chrome `window_id` 모두 정확한
HWND 후보가 0개였고, 배지를 억지로 표시하지 않았다. 이는 수락 계약의 안전한 degraded 상태다.

## 현재 session 대조 계약과 검증

`monitor-window-hwnd-contract.js`는 다음의 읽기 전용, memory-only 계약을 추가한다.

1. BCT/RCC의 현재 `instance_id + session_id + window_id`마다 활성 ChatGPT 탭이 정확히 하나이고
   `conversation_key`가 있어야 한다.
2. Native Host가 같은 관측 회차에 읽은 Chrome HWND의 주소창 대화 키가 정확히 하나여야 한다.
3. 하나의 HWND가 둘 이상의 RCC Chrome window 후보에 해당하면 둘 다 거부한다.
4. Native identity가 8초보다 오래되었거나 대화 키가 중복되면 거부한다.
5. 결과는 extension memory에만 유지한다. storage/BCT 등록/노드 번호/Chrome 창은 변경하지 않는다.

현재 session의 read-only Chrome/Native E2E probe는 활성 ChatGPT Chrome window 3개를 각기 고유한
HWND로 대조했고, 그중 2개가 Native Host 기준으로 이미 최소화 상태임을 확인했다. 거부된 매핑은 없었다.
`check_monitor_current_session_window_hwnd_contract.js`는 활성 탭 중복, 동일 대화가 열린 둘 이상의
Chrome 창, stale Native identity를 모두 거부하는 회귀를 통과했다. 기존 `check_monitor_bct_minimized_badges.js`는
최소화→복원시 번호 배지가 제거되는 isolated DOM 시나리오를 통과했다.

후보 payload는 설치 Monitor에 versioned publish 되었고, 설치본 manifest는 `2.0.1`이다. 변경 전 설치본은
`D:\ChromeExtensions\DesktopWindow-Monitor\backup\monitor-live-7437ef3-20261020-191940`에 file-level로 보관했다.
설치본 구조·조직 회귀 gate는 PASS했다. 최초 gate는 후보와 함께 변경된 organization checker가 설치본에는 이전판이라
fail-closed 되었고, manifest/token 변경 없이 중단됐다. 같은 후보의 checker를 맞춘 뒤에만 재실행했다.

그러나 배포 marker ACK는 아직 도착하지 않았고, 실행 중 Monitor는 reload 전 `2.0.0`으로 관측된다. 따라서 실제
화면에서 새 배지가 최소화·복원에 따라 나타나고 사라지는 전환은 아직 검증하지 않았다. 확장 페이지 직접 자동 조작은
browser security policy가 차단하므로 이를 우회하지 않는다. 열려 있는 Monitor의 공식 `설치본 리로드` 버튼으로
same-ID reload가 완료된 뒤에만 E2E를 계속한다.

## 후속 정리 — 일반 Chrome 카운트다운 표시 제거

일반 Chrome 창이 ChatGPT 대화로 식별되기를 잠시 기다리는 기존 30초 grace filter는 유지하되, 이 창은 Monitor
노드가 아니므로 노란 `28s` 같은 화면 카운트다운을 만들지 않도록 변경했다. 기존 payload가 남긴 overlay는 다음
화면 동기화에서 제거한다. 이 변경은 ChatGPT 노드 번호, `N?` 규칙, 창 최소화/복원, Native Host 관측과 Chrome
창 조작을 변경하지 않는다. source 검증은 `check_monitor_non_chat_countdown_hidden.js` 및 기존 Monitor 회귀로
통과했으며, 설치본 versioned publish는 완료됐지만 same-ID reload 전까지 실행 중 Monitor에는 적용되지 않는다.

후속 source commit `4bb1c5b6f9fdcb3ac2ba6dc20211169d8ade3d46`의 `monitor.js`, `monitor.css`,
`MONITOR_JS_INDEX.md`는 설치본에 source SHA와 동일하게 반영했다. 직전 설치 세 파일은
`D:\ChromeExtensions\DesktopWindow-Monitor\backup\monitor-live-4bb1c5b-20261020-025500`에 보관했다.
공식 publish gate는 version `2.0.2`, token `a6510f50cf3547f8bf9132a5ad8da3f4`를 기록했다. ACK는 이전
token이었다가 공식 `설치본 리로드` 뒤 일치했다. 새 payload는 실행 중이지만, 실제 최소화→복원 전환 E2E는
별도로 남아 있다.

## 발견된 별도 결함 — Monitor 대화 이름 변경 UI

2026-10-20 LIVE에서 Monitor가 노출한 이름 변경 UI는 BCT `rename-conversation`을 호출하지만, 현재 활성 RCC
loader에는 그 mutation handler가 없다. 두 시도는 각각 `RCC_HOST_OUTCOME_UNVERIFIED:MISSING`으로 terminal
`UNKNOWN`이 되었고, 대상별 rename claim이 남았다. 현재 RCC state가 보고한 원래 ChatGPT 제목도 그대로여서 이
시도들이 적용됐다고 볼 증거는 없다. 이는 사용자 입력·창 식별·Monitor 재로드 문제가 아니라, optional Browser
Adapter를 active relay에 연결하지 않는 RCC V2 정책과 UI가 어긋난 계약 결함이다. 이 후보에서 legacy mutation을
되살리거나 UNKNOWN claim을 강제 해제하지 않는다. 이름 변경은 별도의 Adapter·영수증 계약·reconciliation UI
단계로 복구하며, 그 전에는 Monitor UI가 이를 지원한다고 표시해서는 안 된다.

이전에는 `ISOLATED_ACCEPTED`로 올리려면 다음 중 하나의 **읽기 전용·fresh** 대조 계약이 필요했다.

- Monitor/RCC가 현재 session의 Chrome `window_id`, `tab_id`, conversation key와 Native Host가
  관측한 HWND를 같은 session/turn으로 정확히 결합해 제공하거나,
- 이미 있는 Monitor node binding을 현재 session identity와 Native observation으로 재검증해
  stale/reused Chrome window ID를 배제한다.

과거 storage binding이나 제목만으로 대조를 추측해서는 안 된다. LIVE 수락 단계에서는 검증된 설치본을
same-ID reload한 뒤, 이 계약이 확정한 창만 대상으로 최소화→썸네일 번호 표시→복원→번호 제거를 확인한다.

## 자물쇠와 LIVE

기존 `PROTECTED`는 storage·표시만 확인됐고 Monitor/Native/RCC/BCT의 자동 effect 경계에서 실제
차단은 확인되지 않았다. 이번 표시 후보에 차단 기능을 섞지 않는다. 보호 기능은 immutable desktop
ID 기준으로 각 효과 소유자가 거부하는 별도 격리 단계다.

source branch는 GitHub `feat/monitor-rcc-display-integration-20261020`의 `7437ef3`이다. payload rollback은
위 backup 디렉터리의 file-level snapshot으로 하고, reload 전에는 새 payload를 실행 중이라고 주장하지 않는다.
