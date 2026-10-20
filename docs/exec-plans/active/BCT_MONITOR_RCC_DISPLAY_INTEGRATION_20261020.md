# BCT Monitor 노드·썸네일 표시 — RCC 통합 격리 검증

상태: `ISOLATED_ACCEPTED / LIVE_PAYLOAD_PUBLISHED / SAME_ID_RELOAD_PENDING`

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
