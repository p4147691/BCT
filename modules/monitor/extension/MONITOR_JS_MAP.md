# Monitor JS Responsibility Map

목적: 실행용 생성 파일을 직접 편집하지 않는다. 편집 정본은 `source-parts/*.js`이며, `source-parts/SOURCE_FUNCTION_INDEX.md`에서 함수의 실제 원본 파일을 찾는다. 변경 후 `python tools/build_monitor_bundle.py`로 출력 파일을 재생성한다. 기존 기능 간 공유 전역 상태가 남아 있으므로 소스 파일 분리만으로 독립 API 구축이 끝났다고 주장하지 않는다.

목적: 큰 `monitor.js`에서 다음 노드가 어디를 봐야 하는지 먼저 찾게 하는 지도다.
정확한 함수 위치는 `MONITOR_JS_INDEX.md`를 사용하고 line number보다 함수/anchor 이름을 우선 검색한다.

## Authority
- ACT: node identity / number / role / task / organization
- Windows Native Host: HWND existence / desktop / geometry / Z-order / captured pixels
- Monitor: presentation, selection, recovery UI, launch/control trigger
- profile-local storage는 system-wide authority가 아니다.

## 주요 책임과 검색 anchor

### ACT transport / bootstrap / health
transport implementation: `monitor-act-transport.js`
public boundary used by `monitor.js`: `actFetch`
Monitor orchestration anchors: `refreshActHealth`, `refreshAiMonitor`
ACT transport failure와 Monitor synchronization failure를 구분한다.

### Notes / local UI history
`monitorNoteId`, `monitorParseNoteBundle`, `monitorUndoNote`, `monitorRedoNote`
node/role authority와 분리해서 본다.

### Node identity / endpoint / slot projection
`monitorStableNodeSlot`, `monitorBrowserDisplaySlots`, `monitorWorkersForState`, `monitorResolvedWorkerHwnd`, `endpointRegistryIsAuthoritative`
Monitor가 node number를 새로 할당하거나 physical placement로 추론하지 않는다.

### Completion / attention / post-work
`monitorCreateChatCompletionAlert`, `monitorSyncAuthoritativeCompletionAlerts`, `monitorSyncChatCompletionTransitions`, `monitorAcknowledgePostWork`
stale/누락 보고가 유효한 attention 상태를 임의로 지우지 않게 한다.

### Shared state / selection
`monitorPublishSharedRuntime`, `monitorSyncSharedRuntime`, `publishMonitorSharedSelection`, `applyMonitorSharedSelection`, `syncMonitorSharedSelection`
system-wide 값은 profile-local copy를 authority로 삼지 않는다.

### Titles / ghost / lifecycle / recovery
`monitorContextTitleRecord`, `refreshMonitorContextTitle`, `requestMonitorConversationRename`, `monitorGhostPersist`, `renderMonitorClosedConversationRecoveryPanel`
live identity와 recovery record identity를 섞지 않는다.

### Provider launch
`configureMonitorProviderLaunchButton`, `monitorNativeLaunchIsolated`
`G+` / `N+`는 provider별 native browser launch만 호출한다. queue/readiness/bootstrap/ACT node 확인 상태머신은 이 경계에 두지 않는다.

### Worker order / list rendering
`monitorPersistWorkerOrder`, `monitorReorderWorkerKey`, `renderWorkers`
표시 순서가 ACT identity나 physical placement authority가 되지 않는다.

### Native messaging / recovery actions
`monitorNative`, `monitorNativeWithTimeout`, `approveMonitorNodeChatChange`, `restoreMonitorNodeChatChange`, `restoreMonitorAllRecovery`, `restoreMonitorRebootSnapshot`
mutation 전 exact target identity를 확인한다.

### Wallpaper / capture / thumbnail / Z-order
`getObservedWallpaper`, `captureDesktopFrame`, `reconcileFrame`, `syncMonitorThumbnailTabBadges`, `syncMonitorNativeZOrder`
capture 실패가 HWND 존재 여부나 node identity를 결정하면 안 된다.
Wallpaper pixels는 Core Native의 `getDesktopVisualSnapshot` 한 계약이 소유하며, Native 구현은 `native/src/DesktopVisualSnapshot.cs`다.
개별 창 snapshot의 queue/cache/generation/dispose authority는 `monitor-thumbnail-service.js`의 `MonitorThumbnailService`다. `monitor.js`에서 별도 capture queue나 HWND cache를 다시 만들지 않는다.

### Window move / drag / trash / desktop recovery
`moveMonitorWindowSet`, `performMonitorWindowDrop`, `trashMonitorConversationKeys`, `restoreMonitorTrashRecord`, `beginMonitorWindowPointerDrag`, `finishMonitorWindowPointerDrag`, `beginMonitorDesktopPointerDrag`
physical mutation은 exact HWND/desktop 기준으로 검증한다.

### Polling / event-driven refresh
`scheduleMonitorExternalWindowPoll` 및 startup/focus/shared-selection refresh 계열
평상시 불필요한 resource/ACT liveness polling을 다시 추가하지 않는다.

## 모듈화 판단 규칙
다른 파일로 옮기기 전에 authority, 입력 상태, 출력/side effect, public boundary, 독립 검증 방법이 모두 명확해야 한다.
불명확하면 먼저 map/index를 보강하고 파일 이동은 하지 않는다.
