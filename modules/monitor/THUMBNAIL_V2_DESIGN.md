# Monitor 썸네일 V2 — 입력/출력 단일 경계 (격리 후보)

## 현재 수락 단계: background-only

현재 운영 구성은 `MonitorThumbnailLayerPolicy`의 `background-only` 모드를 사용한다. 이는 별도 폴백 렌더러가 아니라 정식 V2 합성기의 단계별 수락 정책이다.

- `background`: 활성. 정확한 데스크톱 GUID에 대응하는 Native 사진 또는 Windows 단색 근거만 렌더링한다.
- `windows`: 임시 비활성. HWND 캡처와 상태 장식을 호출하지 않는다.
- `semantic`: 임시 비활성. 노드/탭 의미 배지를 렌더링하지 않는다.
- `summary`: 임시 비활성. 최소화 노드 요약을 렌더링하지 않는다.

배경 읽기가 일시적으로 실패하면 실패 상태와 이유는 그대로 기록하되, 이미 수락한 마지막 사진/단색 픽셀은 회색 기본색으로 지우지 않는다. 새 카드 생성 경로는 canonical/lightweight 어느 쪽이든 모든 카드의 동일한 `refreshBackground` 포트를 호출한다. 다음 레이어는 배경 LIVE 수락 뒤 정책만 확장하고, 배경 소유권이나 별도 우회 경로를 추가하지 않는다.

배경 레이어의 권한은 타일의 정확한 데스크톱 GUID로 결정한다. Monitor 팝업 HWND가 어느 가상 데스크톱에 속하는지는 창 캡처 레이어의 조건일 뿐이며, 배경 요청을 막는 조건으로 사용하지 않는다.

## 책임
- `monitor-desktop-thumbnail-v2.js`가 **하단 D1/D2 타일의 갱신 생명주기와 시각 렌더링**을 소유한다. 상단/큰 미리보기, 노드 의미·클릭·드래그·대화 송수신은 변경하지 않는다.
- `monitor.js`의 `refreshDesktopThumb(visual, GUID)`는 V2의 단일 `refresh()` 결과만 전달한다. Native `desktopWallpaperChanged`는 V2의 background refresh event만 요청한다. 기존 `reconcileFrame`은 큰 미리보기용으로만 남는다.

## 배경 — 단 하나의 진실
1. 레지스트리 `VirtualDesktopIDs` 순서의 GUID를 타일 `dataset.desktopId`와 정확히 비교한다.
2. `monitor-desktop-visual-source.js`가 주입받은 **하나의 requestId 상관관계 Native Control 포트**에서 `getDesktopVisualSnapshot({desktopId: GUID})`를 요청한다. 썸네일 모듈은 Chrome Native API를 직접 호출하지 않는다.
3. `reply.ok===true`, `reply.desktopId===GUID`이며, 진짜 JPEG/PNG/WEBP 데이터 또는 Windows가 증명한 `mode:solid` + `#RRGGBB`가 만족될 때만 배경 레이어를 설정한다.
4. 같은 타일의 일반 재렌더는 이미 확인한 사진을 반복해서 다시 읽지 않는다. 최초 조회와 **Windows 실제 배경 변경 이벤트**만 재조회. 세대(generation) 검사로 늦은 이전 응답 차단.
5. 일반 캐시(`monitorWallpaperActuals`, `monitorWallpaperCache`), `chrome.storage.session`의 이전 팝업 `wallpaperDataUri`, Progman/WGC 캡처는 배경 출처로 사용하지 않는다.
6. 같은 타일의 일반 중복 요청은 한 promise로 합치며, 실제 Windows 배경 변경 이벤트가 진행 중 요청과 겹치면 후속 읽기 한 건으로 합친다.

## 창 레이어 — 배경과 절대 혼합 금지
- 기존 Native HWND 목록의 `frame.meta.desktopId===GUID`와 실제 영역(virtualLeft,Top,Width,Height)을 확인한 후 창 위치와 Z순서 유지.
- `captureState=captured`, 최근 15초 이내 촬영, `cloaked=0`, 물리적인 이미지 데이터, `physicalSource!=monitor-frozen`일 때만 창 픽셀 표시.
- CLOAKED, 오래된/보존 캡처, 파일 없는 프레임 또는 복원본은 이미지 소스 제거 → 투명한 창 윤곽 + 원인 표시. 정상 화면처럼 대체 SVG 사용 금지.
- 노드 번호·상태 표시·포커스·드래그는 기존 `syncMonitorDesktopNumberBadge`, `syncMonitorThumbnailTabBadges`, 원래 이벤트 함수로 연결하므로 의미 데이터는 중복 보관하지 않는다.

## 제거된 과거 경로와 남긴 경계
- 기존 썸네일 `refreshDesktopThumb -> reconcileFrame`, 별도 `MonitorWallpaperEventRefresh` 렌더러 사용 중단/삭제.
- 기존 `monitor.js`의 커다란 `reconcileFrame` 함수는 선택한 **큰 미리보기**에서 사용되므로 당장 삭제하지 않는다. 다른 역할을 침범하는 전역 코드 삭제는 별도 수락 전까지 금지.
- Chrome/RCC/Core, 기타 원본 파일은 변경하지 않고 격리 worktree에만 구현한다.

## 수락
- `check_monitor_thumbnail_architecture.js`와 `check_monitor_thumbnail_v2_cleanroom.js`: 포트/계약/레이어 분리, GUID 오매핑 거부, 비동기 구세대 응답 차단, Native 이벤트에서만 재조회, 정상 HWND/노드/Z/기하 유지, CLOAKED·stale·source 오류 투명 처리, F5 새 DOM에서 레거시 픽셀 소거.
- 구버전 Minimized/노드/배경 이벤트 계약 수정·검증. 모든 Monitor JS 34 PASS, 공식 구조 검사 PASS, 함수 SHA 인덱스 일치.
- **실제 Windows D1/D2 스크린샷과 Monitor 타일 픽셀 비교는 미실시**. LIVE 설치 성공과 화면 수락으로 보고하지 않는다.

## 적용 전 필수
- 운영 설치본 SHA·백업/제어 Host/파일 Host/기존 RCC 상태 확인.
- cleanroom 별도 브랜치 CI PASS 후 기존 설치본 고유 변경을 유지한 딱 네 경로: `monitor-desktop-thumbnail-v2.js`, `monitor.js` 썸네일 분기, `desktop.html`의 단일 스크립트, `monitor-ui-layout.css`; 기존 레거시 스크립트 제외와 index도 정확히 반영.
- 한 번의 설치·한 번의 리로드·실제 D1/D2 변경 시험. 검증 실패 시 기존 파일을 정확한 해시로 복원. 중복 UNKNOWN 재시도 없음.

## 시험 실행 구분
- **이식 가능한 자동 회귀시험:** `modules/monitor/tools/check_monitor*.js` — 별도 Chrome/Edge, Native Host 설치를 가정하지 않음.
- **현장 전용 화면 시험:** `node modules/monitor/tools/physical_monitor_thumbnail_v2_edge_visual.js` — 별도 헤드리스 Edge에서 CSS, 위치, 실패 표시를 확인하며 운영 Chrome에 연결하지 않음.
- **현장 전용 Native→화면 시험:** `node modules/monitor/tools/physical_monitor_thumbnail_v2_native_edge.js` — 설치된 Native Host가 반환한 실제 D1/D2 이미지를 별도 헤드리스 Edge에서 GUID별로 대조. 이미지를 저장하거나 외부로 전송하지 않음.
- 현장 시험은 격리 Windows 환경에서 실제 실행해 두 건 PASS. 일반 CI에서는 물리 장치·개인 경로를 요구하지 않으므로 의도적으로 자동 검색 대상에서 제외.

## 운영 격리 경계: V2 레이어 소유 (2026-10-26 추가)
- 하단 \`.monitor-desktop-thumb-visual\`의 CSS 배경은 **monitor-thumbnail-background-layer.js**, 하단 \`.monitor-desktop-thumb-window\`의 이미지 src/geometry/실패 표시는 **monitor-thumbnail-window-layer.js**, 결합 순서와 호환 API는 **monitor-desktop-thumbnail-v2.js**가 소유한다.
- monitor.js는 Native 이벤트와 GUID/HWND 식별 및 역할·상태·드래그 의미를 전달한다. 이벤트가 직접 이미지 DOM을 생성/수정하거나 wallpaperDataUri, monitorWallpaperActuals, monitorWallpaperCache, Progman, SVG/이전 프레임을 대입하면 안 된다.
- legacy window lifecycle handler의 직접 이미지 생성(upsertMonitorEventThumbWindow), old source-set, 직접 이동/크기 반영은 폐기하고 \`scheduleMonitorV2WindowRefresh\`(V2 Native 재조회) 및 \`removeMonitorV2Window\`(V2 소유 하위창 제거)로 전환한다.
- 비동기 capture가 역순 완료되어 과거 프레임을 다시 그리는 경우를 막도록 V2 frameGeneration을 검증한다. 이 방어는 wallpaper 세대(generation)와 독립적이다.
- V2는 `wallpaperReady`, `frameReady`, 결합 `ok`를 따로 반환한다. 창 프레임 성공으로 배경 실패를 숨기거나 초기 완료로 기록하지 않는다.
- 새 데스크톱 생성 후 기존 getObservedWallpaper는 **선택한 큰 미리보기**에 한해 계속 사용될 수 있지만 하단 배경은 V2 Native GUID 조회만 가능하다.
- 옛 getObservedWallpaper, cache map, popup restore, freeze thumbnail, reconcileFrame는 노트·복구·큰 미리보기·기타 UI에 필요하므로 무작정 삭제하지 않는다. 단, 신규 하단 썸네일 코드에서 이들을 호출하면 회귀다.
- tests/check_monitor_thumbnail_v2_render_ownership.js가 이 경계의 직접 writer 재도입을 CI/로컬 검사에서 탐지한다. 기능 테스트는 check_monitor_thumbnail_v2_cleanroom.js를 계속 사용한다.
- 격리는 **하단 썸네일 렌더링** 기준이며 8만 줄 monitor.js 전체 기능의 독립 모듈화가 아니다. 전체 모듈화와 별개로 보고한다.


## Windows API color provenance, isolated acceptance pending
- Photo and solid must be identified by Windows desktop truth, not a stale remembered per-desktop wallpaper filename or merely the global RGB color.
- DesktopSolidColorSource.cs first requires the exact current virtual-desktop GUID. It asks read-only IDesktopWallpaper for all physical monitor wallpaper paths; for an actual solid-color presentation these paths are empty, and COM GetBackgroundColor provides the RGB value.
- If the COM interface is unavailable it uses exact-current-desktop Windows BackgroundType or distributed exposed-screen-color evidence. It never attributes current color to another desktop.
- The current PC was in picture mode during isolated E2E; a true solid-color presentation was not present and must be physically retested before claiming LIVE_SOLID_ACCEPTED. This is not a reason to fabricate a successful check.
- check_monitor_solid_native_contract.py compiles the pure GUID decision harness on Windows and asserts six false-positive/positive behaviors without changing user wallpaper.
