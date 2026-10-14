# Monitor Module Boundaries

목적: 파일을 많이 만드는 것이 아니라, 다음 노드가 책임 경계를 추측하지 않게 한다.
`monitor.js`에서 코드를 다른 파일로 옮기는 것은 아래 상태가 `READY`일 때만 한다.

## 이미 분리된 경계

### BCT status shell — READY / EXTRACTED
- 구현: `monitor-bct-shell.js`; public `MonitorBctShell.create()`.
- 입력: exact BCT Core health/status endpoint and Chrome window API.
- 출력: BCT status windows와 exact RCC instance/session/tab/conversation에 묶인
  ChatGPT 대화 제목 변경. 제목 변경은 BCT `relay_browser` operation receipt를 사용하고
  응답 불명확 시 자동 재시도하지 않는다. Service mutation and deployment are not exposed.
- 검증: `..\tools\check_monitor_bct_shell.js`.

### BCT window-node summary — ACTIVE BCT PROJECTION
- `N<n>`은 현재 열린 RCC ChatGPT 탭의 표시 순서일 뿐 권한·역할·영구 신원이 아니다.
- 행 제목은 별도 Monitor alias가 아니라 RCC가 관측한 실제 ChatGPT 대화 제목이다.
- 우클릭 편집은 확인/Enter에서만 실제 제목을 변경한다. 취소/X/Escape/바깥 클릭은
  operation을 만들지 않는다.
- 실제 변경 authority는 RCC이고, BCT Core가 exact identity와 durable duplicate fence를
  소유한다. Monitor는 이 계약의 UI projection만 소유한다.

### Work context summary — READ-ONLY PROJECTION
- 구현: `monitor-context-resume.js`; public `MonitorContextResume.createButton`.
- 입력: 정확한 conversation key와 선택적 project/task 식별자, 기존 `actFetch`, 기존 채팅 복구 callback.
- 출력: 클릭 시 GET /handoff 결과의 결정/진행/다음 행동/누락/시점 요약. 조회 외 자동 실행/권한 이전/폴링/저장 없음.
- 대상 채팅 열기는 요약 확인 뒤 별도 클릭이며 수신/읽기를 증명하지 않는다.
- 검증: DesktopWindow `tools/monitor-context-resume/test_context_resume.cjs`, `test_browser.cjs`.

### Provider browser launch — ACTIVE INLINE
- 구현: `monitor.js`의 `configureMonitorProviderLaunchButton`
- Native 동작: `launchGoogleChatGpt` / `launchNaverChatGpt`
- 성격: provider별 ChatGPT 브라우저 창 열기만 담당
- 금지: launch queue, 자동 `기깃`, endpoint/conversation readiness, ACT node 확인 상태를 이 경계에 다시 넣지 않는다.

### Deployment token / reload ACK — READY / EXTRACTED
- 운영 도구: `..\tools\Request-MonitorDeploymentCheck.ps1`
- protocol marker: `.reload-token`, `.reload-ack`
- auto-reload 지원 runtime 의미: startup/focus deployment check에서 새 token을 감지하면 기존 `monitor-reload-extension` 경로로 열린 Monitor 전체 reload를 요청하고, 재기동 뒤 같은 token을 ACK한다.
- bootstrap 예외: 이 동작이 아직 로드되지 않은 legacy runtime은 token을 ACK만 할 수 있다. 따라서 ACK 단독은 reload 증거가 아니며, 최초 전환은 runtime build marker/instance telemetry로 확인한다.

### Sketchpad UI — ACTIVE INLINE / REVIEW
- 현재 실행 구현: `monitor.js`의 `monitorSketchpad` / `MONITOR_SKETCH_STORAGE_KEY` 계열
- 이전에 별도로 존재하던 `monitor-sketchpad.js`는 load graph에 등록되지 않은 중복 구현이라 `backup\legacy-ui\monitor-sketchpad-unloaded-20260921.js`로 격리했다.
- 구 구현용 `.monitor-side-sketchpad` / `.monitor-sketchpad-title` / `.monitor-sketchpad-actions` CSS는 active 스타일에 현재 계산 결과를 보존해 합친 뒤 제거했다. live CSS에는 active sketchpad 규칙만 남긴다.
- 향후 분리 시 새 구현을 또 만들지 말고 **현재 inline 구현을 그대로 이동**하고, `desktop.html` load graph와 structure checker를 함께 갱신한다.

## monitor.js 내부 후보

### Notes / local history — REVIEW
- 대표 anchor: `monitorNoteId`, `monitorParseNoteBundle`, `monitorUndoNote`, `monitorRedoNote`
- ACT/node authority와 개념적으로 분리돼 있지만 DOM/storage 의존성 확인이 더 필요하다.
- 아직 파일 이동 금지.

### ACT transport — READY / EXTRACTED
- 구현 파일: `monitor-act-transport.js`
- private: endpoint probe, port scan, TTL cache, retry
- public boundary: `actFetch`
- `monitor.js`의 기존 호출부는 `actFetch`만 사용한다.
- endpoint discovery 세부 구현을 다시 `monitor.js`로 복제하지 않는다.

### Window thumbnail service — READY / EXTRACTED
- 구현 파일: `monitor-thumbnail-service.js`
- public boundary: `MonitorThumbnailService.create()`가 반환하는 `requestSnapshot`, `invalidate`, `dispose`, `disposeAll`, `getCached`, `stats`
- 소유 책임: HWND별 요청 coalescing, 최대 동시 capture 2, generation invalidation, LRU cache, 결과 dispose
- `monitor.js` 책임: Native WGC adapter, Blob URL 생성, DOM projection, 실제 Windows 이벤트에서의 호출
- 독립 검증: `..\tools\check_monitor_thumbnail_service.js`
- 규칙: `monitor.js`에 별도 capture queue/cache/inflight map을 다시 만들거나 Native `captureWindow` 호출을 분산하지 않는다.

### Node identity / endpoint projection — KEEP TOGETHER FOR NOW
- 기본 목록은 ACT node authority를 사용하지 않고 RCC의 exact instance/session/tab/conversation을
  BCT 상태에서 읽는다. physical HWND/desktop 표기는 Native Host 관측이 연결된 뒤에만 추가한다.
- 이전 조직 projection은 compatibility-only이며 기본 목록의 신원이나 권한을 결정하지 않는다.

### Shared state / selection — KEEP TOGETHER FOR NOW
- profile-local state와 Native shared state의 경계를 잘못 나누면 재동기화 버그가 생길 수 있다.

### Native messaging / capture / move / recovery — KEEP TOGETHER FOR NOW
- physical mutation과 HWND identity 검증이 얽혀 있어 작은 helper만 보고 분리하지 않는다.

## 2026-09-21 추가 감사 / 모듈화 후보 판정

### Dead-code 상태
- 이름 기준 전체 live JS/HTML 역참조에서 top-level 함수의 **정의-only(1회) 함수는 0개**까지 정리했다.
- 이어서 정의 외 참조가 전혀 없던 단순 top-level 선언 16개(옛 URL 상수, 미사용 poll 상수, legacy storage key, 미사용 structure/workplace/thumb 상태 등)를 제거했다.
- 이 판정은 정적 이름 참조 감사이므로 이후 큰 변경 뒤 다시 실행한다. 동적 문자열 호출 가능성이 있는 코드에는 자동 삭제 규칙으로 쓰지 않는다.

### Sketchpad — REVIEW / NEAR READY
- 측정 구간 약 251줄, top-level 함수 7개 중 5개는 구간 내부 전용이고 2개가 외부에서 참조된다.
- canvas 저장/복원/펜/지우개 자체는 독립성이 높다.
- 다만 현재 element/collapse 상태가 Monitor 배치와 `syncMonitorSideNote()`, panel/switcher layout에 직접 연결돼 있다.
- **현재 UI 조정이 끝나기 전에는 파일 이동 금지.**
- READY 조건: 생성/저장/그리기 책임과 외부 layout callback을 분리하고, 외부에는 element/collapse/layout-change 정도의 좁은 API만 남긴다. 새 구현을 만들지 말고 현재 inline 구현을 그대로 이동한다.

### Notes / local history — NOT READY
- 측정 구간 약 5,051줄, top-level 함수 34개 중 15개가 구간 밖에서 직접 참조된다.
- DOM, local history/undo, Native note 저장, shared note refresh, AI 정리가 한 덩어리에 섞여 있다.
- 파일을 먼저 나누면 public API가 너무 넓어지므로 **현재는 분리하지 않는다.**
- 먼저 storage/native adapter와 UI/editor state의 책임 경계를 문서화한 뒤 재검토한다.

### Diagnostics / Control Center — NOT READY AS ONE MODULE
- 현재 후반 구간은 diagnostics와 structure/organization 코드가 서로 이어져 있어 한 모듈 후보로 취급하면 안 된다.
- 측정 구간에서 top-level 함수 60개 중 23개가 외부 참조를 갖는다.
- 다음 검토는 `diagnostics`와 `structure/organization`을 서로 다른 구간으로 다시 계측한 뒤 진행한다.

### Structure / Organization — MODEL DEFINED / IMPLEMENTATION IN PROGRESS
- 행동 정본: `MONITOR_ORGANIZATION_MODEL.md`.
- Phase A에서 Desk worker -> Desk manager 기본 `MANAGES` edge를 `monitorStructureDefaultParents()`에 추가했고, explicit reparent/detach가 default보다 우선함을 검증했다.
- `monitorStructureBuildSavePayload()`가 worker-manager edge와 detached child를 ACT payload로 직렬화하는 것도 검증했다.
- 아직 organization 코드를 별도 모듈로 대규모 이동하지 않는다. manager/desk/node UI와 ACT round-trip이 안정화된 뒤 pure model과 projection UI 경계를 다시 잰다.
- Node identity / endpoint projection / Shared state / Native mutation 경계는 기존 KEEP TOGETHER 판정을 유지한다.


## READY 판정 조건

다음 다섯 가지가 문서와 테스트로 설명될 때만 READY다.
1. authority
2. 입력 상태
3. 출력/side effect
4. public call boundary
5. 독립 검증 방법

READY가 아니면 먼저 `MONITOR_JS_MAP.md`와 `MONITOR_JS_INDEX.md`를 보강한다.
파일 크기 자체는 분리 사유가 아니다.
