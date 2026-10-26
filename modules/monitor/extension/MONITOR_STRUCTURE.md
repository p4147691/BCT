# DesktopWindow Monitor — Runtime Structure

이 문서는 **현재 PC의 DesktopWindow Monitor 런타임 구조를 찾기 위한 로컬 정본 지도**다.
전역 정책은 `p4147691/BOOTSTRAP`이 정본이며, 이 문서는 Monitor의 실제 로컬 경로와 책임 경계만 설명한다.

## 1. 먼저 볼 곳

- Runtime root: `D:\ChromeExtensions\DesktopWindow-Monitor`
- Active extension: `D:\ChromeExtensions\DesktopWindow-Monitor\extension`
- ACT PC Bridge alias `monitor`: 위 `extension` 폴더를 직접 가리킨다.
- Agent entry: `extension\AGENTS.md`
- 이 문서: `extension\MONITOR_STRUCTURE.md`
- Organization behavior model: `extension\MONITOR_ORGANIZATION_MODEL.md`
- Code responsibility map: `extension\MONITOR_JS_MAP.md`
- Module boundary decisions: `extension\MONITOR_MODULE_BOUNDARIES.md`
- Target architecture and migration order: `..\MONITOR_ARCHITECTURE.md`
- Screen feature ownership map: `..\MONITOR_UI_FEATURE_BOUNDARIES.md`
- Extracted Sketch owner: `extension\features\sketch\monitor-sketch-feature.js` and `.css`
- Generated function index: `extension\MONITOR_JS_INDEX.md`
- Deployment observation tool: `tools\Request-MonitorDeploymentCheck.ps1`
- Versioned deployment tool: `tools\Publish-MonitorDeployment.ps1`
- Structure verifier: `tools\check_monitor_structure.py`
- Organization invariant verifier: `tools\check_monitor_organization_model.py`
- Live organization verifier (read-only): `tools\check_monitor_live_organization.py`

**`D:\AI_TOOLS\DesktopWindow-Monitor`는 현재 런타임 정본이 아니다.**
그 위치는 과거 `desktopwindow-monitor-20260905` 브랜치의 별도 Git worktree와 실험/진단 산출물이 함께 남아 있는 개발 이력이다.
현재 파일을 찾거나 배포 상태를 판단할 때 그 worktree를 런타임 소스로 사용하지 않는다.

## 2. 현재 코드/상태 authority

무엇이 **현재 실행 중인가**를 판단할 때는 deployed runtime을 먼저 본다.

- 실행 중 browser payload: `D:\ChromeExtensions\DesktopWindow-Monitor\extension`
- active Native binary: `native` manifest의 `path`
- live node/role/task truth: ACT

`p4147691/DesktopWindow`은 프로젝트/공유 Core의 GitHub 정본이지만, Monitor runtime을 교체할 때 GitHub edition이나 과거 worktree가 현재 deployed payload와 byte-identical하다고 가정하지 않는다.
배포·복원 전에 반드시 현재 runtime과 비교한다.

즉 **runtime truth와 repository history를 섞지 않는다.** 향후 Monitor 소스를 다시 Git-authoritative delivery로 통합한다면 별도 검증된 migration으로 전환한다.

## 3. 책임 경계

- ACT: live node identity, role, task, organization의 authority.
- Monitor: 관제 UI, window/thumbnail 관찰, launch/control trigger의 projection.
- ADC_NATIVE: 현재 PC의 실제 로컬 실행.
- Monitor 운영 대상 Chrome profile: **Google only**. NAVER profile은 Monitor UI/reload/recovery 대상이 아니다.

Monitor가 ACT의 node/role/task truth를 복제해서 별도 authority가 되어서는 안 된다.

Organization UI의 backend runtime은 `D:\ACT\runtime\agent-orchestrator`이며, 상세 edge/save contract는 `MONITOR_ORGANIZATION_MODEL.md`를 따른다. Monitor code는 ACT port를 직접 소유하지 않고 `monitor-act-transport.js`의 `actFetch("act:/...")`를 통해 접근한다. `GET /organization/hierarchy`가 조직 read authority이고, 전체 저장은 `POST /organization/layout-save` + `expected_generation`이 정식 commit 경로다.

## 4. Active extension load graph

`manifest.json`
- MV3 service worker: `background.js`
- ChatGPT content script: `google-bootstrap.js`
- `Alt+M`: Monitor open/focus command

`desktop.html`의 현재 script load order:
1. `desktop.js`
2. `monitor-act-transport.js`
3. `monitor-thumbnail-service.js`
4. 독립 UI/정책 모듈들과 `monitor-native-trace.js`
5. 썸네일 계약 스택: `monitor-thumbnail-contract.js` → `monitor-desktop-visual-source.js` → `monitor-thumbnail-background-layer.js` → `monitor-thumbnail-window-layer.js` → `monitor-desktop-thumbnail-v2.js`
6. `monitor-domain-apis.js`, node generation, host identity
7. generated compatibility bundle `monitor.js`
8. `desktop-window-chrome.js`

정확한 전체 순서는 `desktop.html`과 `tools/check_monitor_structure.py`가 검증한다. 하단 썸네일의 input adapter와 각 시각 레이어는 `..\MONITOR_ARCHITECTURE.md`의 dependency direction을 따른다.

`G+` / `N+`는 `monitor.js`의 최소 provider launch trigger다. 각 버튼은 provider별 ChatGPT 브라우저 창 열기만 요청하며 launch queue, 자동 `기깃`, endpoint/ACT node 동기화 상태를 소유하지 않는다.
`monitor-act-transport.js`는 ACT endpoint 탐색/cache/retry를 소유하고, `monitor.js`에는 `actFetch` 한 경계만 노출한다.
`monitor-thumbnail-service.js`는 HWND별 snapshot coalescing, 최대 동시 실행 수, generation invalidation, LRU 결과 소유권과 dispose를 소유한다. `monitor.js`는 WGC Native adapter와 DOM projection만 담당한다.

## 5. Native Messaging authority

Native binary의 authority는 **폴더 이름이 아니라 Native Messaging manifest의 `path` 값**이다.

확인 순서:
1. `native\com.pas40.desktop_window_monitor.json`
2. `native\com.pas40.desktop_window_monitor_control.json`
3. Windows NativeMessagingHosts registry가 위 manifest JSON을 가리키는지 확인
4. 필요할 때 running process의 executable path로 교차검증

현재 Native 책임은 이름이 아니라 기능 경계로 분리한다.
- File shell host (`com.pas40.desktop_window_monitor`): `native\1.9.20.128-hidden-all\DesktopWindowMonitorHost.exe`
- Monitor host (`com.pas40.desktop_window_monitor_control`): `native\1.9.20.159-foreground-event\DesktopWindowMonitorControlHost.exe`

이 경로는 상태값이므로 native 변경 전에는 manifest를 다시 읽는다.
파일 목록·열기·이름 변경·생성·삭제는 `desktop.js` → `background.js`의 단일 persistent ordered port → File shell host로만 전달한다.
`captureWindow`는 ThumbnailService adapter → `monitorCoreNative` → Monitor host로만 전달한다. `monitorNative`와 `monitorCoreNative`는 같은 Monitor manifest를 사용하되 요청/이벤트 포트 수명은 분리한다.
배경화면은 `getDesktopVisualSnapshot` → Monitor host의 `DesktopVisualSnapshot.cs` 한 경로만 사용한다. 과거 `desktop-shell-mirror.js`와 지원되지 않는 `shellMirror*` 요청은 active load graph에서 제거했다.
실제 adapter의 transport/engine/Blob ownership 회귀 검사는 `tools\check_monitor_capture_route.js`다.
`native\live` 같은 폴더명이나 가장 높은 version 번호를 보고 active binary를 추측하지 않는다.

## 6. Reload paths

두 동작을 구분한다.

### UI self-reload
Monitor UI의 reload 동작:
`monitor.js` → message `monitor-reload-extension` → `background.js` → `chrome.runtime.reload()`

### External deployment observation
외부 자동 작업은 `tools\Request-MonitorDeploymentCheck.ps1`로 deployment marker를 발행하고 관찰할 수 있다.

이 도구는 **pre-reload fail-closed gate**다. token을 쓰기 전에 `tools\check_monitor_structure.py`를 실행하며, verifier는 active load graph의 모든 JavaScript에 `node --check`를 수행한다. syntax/structure/index/organization 검증 중 하나라도 실패하면 `.reload-token`을 변경하지 않고 종료한다. 코드 배포를 위해 `.reload-token`을 직접 쓰는 우회 경로를 만들지 않는다.

gate가 PASS한 뒤에만 `extension\.reload-token`을 갱신한다. auto-reload 지원 Monitor가 startup/focus deployment check에서 새 token을 보면 기존 `monitor-reload-extension` 경로를 호출하고, `background.js`가 열린 Monitor 페이지들을 보존한 채 `chrome.runtime.reload()`를 수행한다. 재기동된 Monitor는 같은 token을 초기값으로 읽고 `ackExtensionReload`를 호출해 `extension\.reload-ack`을 갱신한다.
단, auto-reload 코드가 아직 로드되지 않은 **legacy/초기 bootstrap runtime은 token을 관찰하고 ACK만 할 수 있다.** 따라서 ACK 단독은 여전히 actual reload의 충분조건으로 취급하지 않는다. 최초 전환 뒤에는 runtime instance telemetry와 함께 post-reload 상태를 확인한다.
두 dot-file은 runtime protocol marker이며 소스 파일이 아니다.

UI self-reload와 deployment-token reload는 둘 다 같은 `monitor-reload-extension → background.js → chrome.runtime.reload()` 경로를 사용한다. routine 작업에서 `chrome://extensions`를 열지 않는다.

### Versioned code deployment

일반 UI reload와 deployment observation은 `manifest.json`의 version을 바꾸지 않는다.
실제 Monitor 코드 반영에는 `tools\Publish-MonitorDeployment.ps1`만 사용한다. 이 도구는
구조 gate를 통과한 payload에 한해 네 자리 manifest version의 마지막 build component를
정확히 1 증가시키고, 원자적으로 manifest를 교체한 뒤 새 `.reload-token`을 발행한다.

- `-WhatIf`는 다음 version만 보여주며 파일을 바꾸지 않는다.
- 기본 실행은 `PUBLISHED`와 `PENDING`을 출력한다. 이 상태는 Chrome 실행 인스턴스가 아직
  reload되지 않았음을 명시한다.
- `-WaitForObservation`은 새 token ACK만 확인한다. ACK 단독은 actual UI reload 증명이 아니며,
  버전과 실제 화면 흐름은 별도 확인한다.
- build component가 Chrome 한계(65535)에 도달하면 wrap/reset하지 않고 중단한다.
- DesktopWindow 본체나 native binary version을 Monitor extension version에 복사하지 않는다.

## 6.1 Recovery semantics

`이어가기`는 ChatGPT 목록과 닫힌 대화 목록에서 작업 기록 요약을 연다.
`monitor-context-resume.js`는 monitor.js 전에 로드되며 기존 `actFetch`로
해당 conversation의 handoff만 조회한다. 기록 부족/충돌/조회 실패와 대상 수신
미확인을 명시한다. 기존 `복구`/`승인` 버튼 의미와 노드/역할 권한은 바꾸지 않는다.

두 동작은 절대 합치지 않는다.

- **같은 탭의 챗 변경**: 기존 body attachment의 `tab_id`가 유지된 채 `conversation_key`가 바뀐 경우다. 목록 행 오른쪽에 주황 `복구`와 초록 `승인`을 표시하며, 사용자 승인 전에는 새 대화를 기존 대화의 작업·역할·맥락에 자동 연결하지 않는다. 현재 deployed storage는 이 관측을 legacy `tab_id + conversation_key` key로 표현하므로, approval semantics 변경은 별도 migration과 focused test가 필요하다.
- **개별 닫힌 대화 복구**: 사용자가 닫힌 대화를 골라 새 Chrome 탭으로 다시 여는 동작이다. 새 탭은 기존 대화 C-Node의 새 body attachment다. 현재 projection에서는 새 `tab_id + conversation_key` 관측이 생기지만, 과거 역할·조직 연결·승인 이력을 복사하지 않는다. 같은 대화가 이미 정확히 하나 열려 있으면 중복 탭을 만들지 않는다.

조직도 동기화 여부는 위 두 동작과 별개다. 목록 행의 맨 왼쪽 동기화 표식만 바꾸며, 노드 ID·번호·승인 복구 UI를 바꾸지 않는다.

### 6.2 Continuity state

ChatGPT가 새 채팅을 요구하거나 재시도·연결 오류를 표시하면, 이는 C-Node
identity가 아니라 현재 body attachment에서 작업을 계속할 수 있는지의 상태다.
Monitor는 `READY`, `BUSY`, `RETRY_REQUIRED`, `NEW_CHAT_REQUIRED`,
`RECOVERY_REQUIRED`, `UNKNOWN`을 구분한다. 오류 텍스트만으로 맥락이 사라졌거나
작업이 완료됐다고 판단하지 않는다.

`NEW_CHAT_REQUIRED`에서는 원래 대화의 마지막 검증된 handoff 요약과 누락 항목을
보이고, 새 채팅에 붙여 넣을 continuation packet을 복사할 수 있게 한다. 새 탭이나
새 채팅이 열렸다는 사실만으로 인수인계 완료가 되지는 않는다. `RETRY_REQUIRED`는
관찰한 이유와 시각을 보존하고 기존의 제한된 재시도 경로만 사용한다. 임의의 새
poller, background chat scraping, 자동 mutation retry는 추가하지 않는다.

### 6.3 Continuity guardian

사용자가 새로고침·과거 텍스트 복사·노드 번호 확인으로 복구하지 않게, Monitor가
기존 endpoint/visible-state event에서 continuity guardian을 실행한다. non-ready
상태가 확인되면 affected attachment의 새 dispatch를 멈추고 last-known-good
conversation, endpoint, 관찰 시각, handoff revision을 보존한다. 오류 화면으로 그
기록을 덮어쓰지 않는다.

guardian은 인식 가능한 work-blocking signal만 처리한다. `RETRY_REQUIRED`에는 기존
action identity를 유지하고 non-idempotent prompt나 mutation을 자동 재전송하지 않는다.
`NEW_CHAT_REQUIRED`와 `RECOVERY_REQUIRED`에는 최신 verified handoff에서만
continuation packet을 만들며, 충분한 기록이 없으면 누락을 표시한다. packet은
Monitor와 clipboard에서 즉시 쓸 수 있게 준비하되 새 채팅에 자동 입력·전송하거나
수신 완료로 표시하지 않는다. 새 대상의 read/ack가 확인될 때만 handoff 상태를
received로 바꾼다.

### 6.4 Recovery controller

동일 `conversation_key`의 F5·reconnect·탭 재열기는 새 endpoint를 exact 검증한 뒤
같은 C-Node에 자동 reattach한다. 이 경우 ACT에 남아 있는 역할·task·조직 binding을
새로 만들거나 복사하지 않고 re-read하여 Monitor 조직도에 다시 투영한다.

마지막 body attachment가 닫혔지만 대화가 남아 있으면, 등록된 browser launch path가
실제로 가능한 경우에만 정확한 conversation을 다시 열고 endpoint를 확인한다. 새
채팅은 별도 C-Node다. handoff 수신과 source unavailable/NEW_CHAT_REQUIRED, 동일
project/workstream, exact target endpoint, active lease 충돌 없음, current binding
generation을 모두 확인한 replacement policy가 있을 때만 ACT의 한 transaction으로
역할·전달 가능한 task·조직 binding을 교체한다. source/destination이 동시에 live거나
모호하면 `RECOVERY_REQUIRED`로 멈추며 local cache만으로 조직도를 수정하지 않는다.

반복 오류의 상태·원인은 compact incident로 남기고 focused fix와 검증을 제안할 수
있다. 그러나 Monitor가 오류를 이유로 production code, 역할, task ownership,
브라우저 profile, 조직 layout을 자체적으로 임의 수정하는 self-modification은 금지다.

### 6.5 Desk hygiene controller

Monitor는 C-Node body attachment의 화면 위치를 정돈할 수 있지만, 이는 presentation
controller다. context, role, task, project, handoff, ACT organization binding을
변경하지 않는다. overlap/off-screen/과다 active window 또는 사용자가 지정한 preset에서
clutter를 판단하고, exact HWND·desktop·attachment를 읽은 뒤 기존 geometry/order를
rollback snapshot으로 저장한다. 이동 후 모든 예상 창의 존재·도달 가능성을 검증하며,
하나라도 실패하면 저장된 geometry로 되돌리고 실패 HWND를 표시한다.

첫 preset은 **four-pane focus**다: Monitor/status, primary active C-Node, secondary
active C-Node, reference/overflow. pane 배치는 선택된 작업과 현재 attachment의
projection일 뿐 task claim이 아니다. 남는 창은 visible overflow에 남기며 자동으로
닫지 않는다. Chrome tab hygiene는 known project/C-Node로 목록·그룹·focus view를
지원할 수 있지만 tab close/reload/profile 이동/ChatGPT tab merge는 자동 실행하지
않는다. 동일 conversation의 여러 tab은 삭제 대상이 아니라 여러 body attachment다.

자동 window 이동은 managed로 지정한 desktop에서만 가능하며, drag, modal recovery,
active user input, uncertain window identity 중 하나라도 있으면 recommendation만 보이고
실행하지 않는다.

### 6.6 Per-desktop management mode

각 virtual desktop은 temporary D-number가 아니라 immutable desktop id 기준의 local
Monitor policy를 가진다. 이 값은 ACT organization/C-Node/task data와 별개다.

- **관리(MANAGED):** 승인된 layout preset과 bounded same-conversation recovery를 실행할 수 있다.
- **보기만(OBSERVE_ONLY):** 상태·attachment·추천만 표시하고 geometry/tab/reopen action은 실행하지 않는다. 기본값이다.
- **보호(PROTECTED):** 자동 recovery, layout, tab hygiene, launch에서 제외한다. 개인 데스크의 창은 자동 layout 후보나 작업 추천에 넣지 않고, window detail도 노출하지 않는다.

desktop thumbnail header의 shield/menu에서 `관리 · 보기만 · 보호`를 한 번에 고르게
하고 현재 mode를 compact icon으로 표시한다. mode 변경은 desktop id, 이전 mode, 시각을
local rollback record에 남기지만 창·역할·task를 바꾸지 않는다. desktop을 삭제해도
그 policy를 다른 desktop id에 자동 승계하지 않는다.

## 7. History / backup rule

- `backup\`: history only. runtime authority가 아니다.
- `backup\native-history\`: active manifest/process/reference가 없음을 확인한 옛 Native build 격리 위치다.
- `native\live`를 authority 이름으로 다시 만들지 않는다. active binary는 항상 manifest `path`로 판정한다.
- `D:\ACT\runtime\monitor-ui-cleanup\`: 최근 구조 정리 rollback snapshot.
- active `extension\` 안에 `.bak`, 임시 patch script, 수동 사본을 두지 않는다.
- historical source를 복원할 때는 active 파일에 바로 덮지 말고 diff/검증 후 적용한다.

## 8. Safe change rule

다음 노드도 같은 순서를 사용한다.

1. 이 파일로 active path와 authority를 확정한다.
2. 변경 대상의 현재 hash/reference를 확인한다.
3. 같은 physical target에 다른 writer가 있으면 쓰지 않는다.
4. 최소 범위만 변경한다.
5. `tools\check_monitor_structure.py`와 JS syntax / CSS structure / HTML script reference 같은 가장 싼 검증부터 수행한다.
6. 필요한 경우 canonical reload tool을 사용하고 ACK를 확인한다.
7. reload ACK 또는 실제 runtime evidence가 없으면 “적용 완료”라고 단정하지 않는다.

큰 `monitor.js`를 단지 크다는 이유만으로 분할하지 않는다. 독립 책임과 검증 경계가 확인된 기능만 단계적으로 분리한다.
