# Monitor Module Boundaries

목적: 파일을 많이 만드는 것이 아니라, 다음 노드가 책임 경계를 추측하지 않게 한다.
`monitor.js`에서 코드를 다른 파일로 옮기는 것은 아래 상태가 `READY`일 때만 한다.
전체 목표 구조와 도메인 이행 순서는 `..\MONITOR_ARCHITECTURE.md`를 따른다.

## 이미 분리된 경계

### BCT status shell — READY / EXTRACTED
- 구현: `monitor-bct-shell.js`; public `MonitorBctShell.create()`.
- 입력: exact BCT Core health/status endpoint and Chrome window API.
- 출력: BCT status windows와 exact RCC instance/session/tab/conversation에 묶인
  ChatGPT 대화 제목 변경. 제목 변경은 BCT `relay_browser` operation receipt를 사용하고
  응답 불명확 시 자동 재시도하지 않는다. Service mutation and deployment are not exposed.
- 검증: `..\tools\check_monitor_bct_shell.js`.

### BCT window-node summary — ACTIVE BCT PROJECTION
- 대화망에 등록된 대화의 `N<n>`은 BCT가 conversation key에 한 번만 부여하는 표시 전용 번호다.
  창/탭 이동, 제목 변경, 역할 태그 변경과 무관하며 재사용하지 않는다. 번호 자체는 권한·역할·라우팅·영구 신원이 아니다.
- 대화망에 아직 등록되지 않은 RCC 대화는 `N?`로 보이며, 대상 식별은 계속 exact conversation key가 맡는다.
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

### Sketchpad UI — SOURCE EXTRACTED / LIVE PENDING
- 현재 소스 구현: `features/sketch/monitor-sketch-feature.js`와 `.css`. DOM, canvas 상태, 도구, undo/redo, 이벤트와 persistence 호출의 단일 소유자다.
- `monitor.js`에는 `MonitorSketchFeature.create(...)` composition과 `layout(...)` 호출만 남으며, 그림판 구현 함수·DOM 생성·CSS는 남지 않는다.
- persistence/timer/layout은 주입 포트로만 받고, 기능 내부는 Monitor 전역이나 Chrome/Native API를 직접 읽지 않는다.
- 독립 검증: `..\tools\check_monitor_sketch_feature.js`; 구조 검사가 load order, 단일 소유권과 문법을 함께 고정한다.
- 운영 설치와 실제 펜/지우개/도형/글자/undo/redo/접기/재시작 복원 수락 전이므로 LIVE 완료로 보고하지 않는다.
- 이전에 별도로 존재하던 `monitor-sketchpad.js`는 load graph에 등록되지 않은 중복 구현이라 `backup\legacy-ui\monitor-sketchpad-unloaded-20260921.js`로 격리했다.
- 위 legacy 파일을 다시 로드하거나 두 번째 그림판 경로로 복구하지 않는다.

## monitor.js 내부 후보

### Notes / local history — SOURCE EXTRACTED / LIVE PENDING
- 현재 소스 구현: `features/notes/monitor-notes-feature.js`와 `.css`.
- 단일 소유 책임: Notes DOM, 목록/편집 상태, reorder, list/edit undo/redo, shared content/view synchronization.
- Native shared-note 요청, ACT AI organizer, Recovery trash, status와 layout은 모두 주입 포트다. Notes가 Chrome/Native/ACT 전역을 직접 읽지 않는다.
- `sketch-notes.js`에는 삭제 메모 Recovery adapter와 Sketch/Notes 배치 composition만 남는다.
- 독립 검증: `..\tools\check_monitor_notes_feature.js`; 설치 및 실제 편집/동기화/AI/복구 수락 전이므로 LIVE 완료로 보고하지 않는다.

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

### Bottom thumbnail renderer — SOURCE EXTRACTED / D1-D2 LIVE PASSED
- input: `monitor-desktop-visual-source.js`; 주입된 canonical `monitorNative` request만 사용한다.
- validation: `monitor-thumbnail-contract.js`; exact GUID와 photo/solid 증거를 검증한다.
- state/output: background와 HWND window 레이어가 각자의 DOM/CSS만 소유하고 V2 compositor가 순서와 호환 API만 소유한다.
- 금지: 썸네일 모듈의 Chrome Native 직접 호출, 별도 `sendNativeMessage`, FIFO 응답 추측, legacy wallpaper cache 접근.
- 검증: `check_monitor_thumbnail_architecture.js`, `check_monitor_thumbnail_v2_cleanroom.js`, `check_monitor_thumbnail_v2_native_ports.js`, `check_monitor_thumbnail_v2_render_ownership.js`.
- refresh lifecycle: V2가 타일별 in-flight/queued event와 배경·창의 분리된 완료 결과를 소유한다. monitor.js 호환 함수는 `renderer.refresh()`의 결합 결과만 전달한다.
- 2.0.62에서 D1 사진, D2 단색 및 왕복은 LIVE 수락됐다. 새 데스크톱 단색 상속과 큰 배경 동기화는 다음 배포에서 별도 수락한다.

### Full Monitor preview background — SOURCE EXTRACTED / LIVE PENDING
- 구현: `monitor-preview-background.js`; public `MonitorPreviewBackground.create({element, contract})`.
- 입력: thumbnail V2가 exact GUID Native 응답으로 수락한 정규화 photo/solid snapshot만 받는다.
- 출력: 큰 Monitor 배경의 `backgroundImage`/`backgroundColor`와 수락 상태만 소유한다.
- 금지: Native 직접 호출, 예전 사진 cache 읽기, 실패 시 다른 데스크톱 배경 유지.
- 새 데스크톱은 Native create 응답의 source/created GUID와 inherited wallpaper 증거가 일치할 때만 원본의 수락 snapshot을 상속한다.
- 독립 검증: `..\tools\check_monitor_preview_background.js`, `..\tools\check_monitor_thumbnail_background_only_mode.js`.

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

### Sketchpad — SOURCE EXTRACTED / LIVE PENDING
- 기존 inline 구현 28개 함수와 bootstrap event/state를 새 구현을 덧붙이지 않고 `features/sketch/`로 이동했다.
- 외부에는 `create`, `element`, `layout`, `destroy`, read-only `snapshot`만 노출한다.
- `syncMonitorSideNote()`는 Sketch DOM/state를 읽지 않고 `layout({ boardCollapsed, rootRect, noteLeft })`만 호출한다.
- 다음 단계는 배포가 아니라 먼저 이번 source commit을 보존한 뒤, 별도 설치/LIVE 수락에서 실제 입력과 복원을 확인하는 것이다.

### Notes / local history — SOURCE EXTRACTED / LIVE PENDING
- 기존 DOM/global state와 29개 compatibility 함수, `shared-ui`의 history helper 6개를 독립 feature로 이동하고 옛 구현을 삭제했다.
- public API는 `element`, `layout`, `refreshContent`, `refreshView`, `restoreNote`, `titleFromText`, `destroy`, read-only `snapshot`으로 제한한다.
- Recovery는 삭제 메모 보관만 소유하고 `restoreNote(note)`로 되돌린다. ACT AI와 Native transport는 composition root의 adapter가 소유한다.
- 다음 변경에서 이 구현을 compatibility bundle로 복사하거나 raw Notes state를 다시 노출하지 않는다.

### Diagnostics / Control Center — NOT READY AS ONE MODULE
- 현재 후반 구간은 diagnostics와 structure/organization 코드가 서로 이어져 있어 한 모듈 후보로 취급하면 안 된다.
- 측정 구간에서 top-level 함수 60개 중 23개가 외부 참조를 갖는다.
- 다음 검토는 `diagnostics`와 `structure/organization`을 서로 다른 구간으로 다시 계측한 뒤 진행한다.

### Structure / Organization — PARKED / UNUSED
- 행동 정본: `MONITOR_ORGANIZATION_MODEL.md`.
- Phase A에서 Desk worker -> Desk manager 기본 `MANAGES` edge를 `monitorStructureDefaultParents()`에 추가했고, explicit reparent/detach가 default보다 우선함을 검증했다.
- `monitorStructureBuildSavePayload()`가 worker-manager edge와 detached child를 ACT payload로 직렬화하는 것도 검증했다.
- 현재 사용 계획이 없으므로 compatibility 코드를 보존한 채 active basic-feature migration에서 제외한다. 새 기능을 추가하거나 대규모 이동하지 않는다.
- 사용을 다시 결정할 때만 pure model/projection UI로 옮길지 제거할지 별도 판단한다.
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


## 2026-10-26 source ownership transition (in progress, NOT full API modularization)
- Editable Monitor source now lives in 10 ordered source-parts/*.js files plus already-extracted dedicated modules.
- tools/build_monitor_bundle.py deterministically assembles extension/monitor.js for Chrome. This runtime file is GENERATED; do not edit it directly.
- source-parts/SOURCE_FUNCTION_INDEX.md maps function names to source files; inspect this instead of manually searching a monolith.
- check_monitor_structure.py rejects a generated runtime/source mismatch, missing part syntax or an outdated index.
- Ordered source-parts still share top-level lexical variables, Native request adapters and UI state; file separation ALONE does not prove domain-level isolation. Per-domain authority/API extraction remains open and must be honestly counted as outstanding.
- Before merging other Monitor changes, preserve any installed-only differences in the editable source; rebuilding from stale main is forbidden.


## Domain-owned editable function implementations (2026-10-26)
- All 588 top-level function declarations have one human-editable owner in 10 classified domains/*.js source files. Domain owners are compiled back at exact original byte positions using placeholders in source-parts/*.js.
- tools/build_monitor_bundle.py reconstructs the exact runtime byte sequence, checks unique definitions/markers, and updates SOURCE_FUNCTION_INDEX.md. Running HTML and global classic-script variables remain unchanged.
- Pure source extraction changes ZERO runtime bytes. The local structure checker enforces source synchronization and domain JS syntax.
- CRITICAL: Function ownership is NOT full API encapsulation. Implementations still share global lexical state with the app. State migration to independent interfaces needs additional behavioral acceptance.
- extension/monitor.js is derived output. Never hand-edit its 15k lines or revert to earlier 80k formatting.


## Isolated domain runtime APIs (2026-10-26)
- 43 state-independent functions in conversations, node-identity, organization and shared-ui are executed inside standalone monitor-domain-apis.js IIFE, loaded before monitor.js by desktop.html.
- Frozen globalThis.MonitorDomainAPIs namespaces export exact functions. The old function names remain thin compatibility shims in compiled Monitor, keeping existing call sites and DOM identities stable.
- The core runs without Monitor lexical globals or DOM in isolation. check_monitor_domain_pure_api.js verifies immutable namespaces, 43 routed functions and independent VM behavior; structure checker enforces script order and the manifest.
- Historical integration tests requiring direct standalone functions remain on their former source contract until equivalent executable tests are introduced.
- CRITICAL: This is a genuinely independent subset, NOT independently injectable runtime APIs for the remaining 516 functions or shared mutable state. Scope is still OPEN.


## Node generation and attention state with injected read-only storage (2026-10-26)
- monitor-node-generation-state.js exports frozen MonitorNodeGenerationState.create({readTab,readConversation,ttlMs}).
- It owns direct per-tab generation/TTL interpretation, event-driven userAttention precedence and metadata generation fallback. NO ambient Monitor globals or DOM. The actual event-owned record maps remain in monitor.js; the domain source injects only two immutable reader closures.
- Six original function names remain compatibility wrappers; source-parts/02-node-identity.js establishes the state service after original Map and TTL constants.
- check_monitor_node_generation_state.js tests isolated VM/no DOM, exact precedence, stale generation TTL, attention persistence, and script load order. Structural check enforces module load order/test existence.
- Additional mutable state and other domain functions still share classic-script globals. Do not claim full API independence.

- Direct conversation generation and HWND generation also use the exact injected readers. This covers six stateful compatibility functions: per-tab status, user attention, endpoint metadata fallback, per-conversation status, conversation activity and HWND activity.


## Exact Monitor host/window identity after extension reload
- monitor-host-window-identity.js owns a narrow stateless resolver for host HWND recovery; the primary getVirtualDesktops request stays in the desktop-lifecycle domain.
- A mismatch between extension document title and OS window title no longer permanently prevents initial desktop-thumbnail rendering. On unresolved host identity, try title-only then exact window-bounds Native lookup with empty hostTitle.
- Fallback only accepts ok, unambiguous exact HWND, a matching desktop GUID and validated Monitor-only OS title. No cross-desktop guessing, cache fallback, Chrome tab enumeration or polling added.
- check_monitor_host_window_identity.js verifies the contract, with check_monitor_structure.py enforcing its existence. Actual live D1/D2 acceptance remains required.

## 2026-10-29 Header provider launch source boundary (N70)
- Owner: `extension/monitor-provider-launch-feature.js`; public `MonitorProviderLaunchFeature.bind({button,provider,ports}) -> {destroy()}`.
- Owns: exact G+/N+ button labels, click event binding and one active handler per button (WeakMap).
- Injected ports: `launch({type})` for existing Native launch route, `fail(message)` for existing status reporting. No direct Native, Chrome, ACT or BCT calls.
- The generated `monitor.js` retains only `configureMonitorProviderLaunchButton` adapter and injects the two ports. No duplicate launch orchestration, endpoint polling or fallback dispatch is introduced.
- Independent verification: `tools/check_monitor_provider_launch_feature.js`; generated bundle and structure gate. LIVE UI acceptance remains the supervisor's separate responsibility.
