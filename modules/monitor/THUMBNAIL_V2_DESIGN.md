# Monitor 썸네일 V2 — 입력/출력 단일 경계 (격리 후보)

## 책임
- `monitor-desktop-thumbnail-v2.js`가 **하단 D1/D2 타일의 시각 렌더링만** 소유한다. 상단/큰 미리보기, 노드 의미·클릭·드래그·대화 송수신은 변경하지 않는다.
- `monitor.js`의 `refreshDesktopThumb(visual, GUID)` 및 Native `desktopWallpaperChanged` 분기에서 V2 호출. 기존 `reconcileFrame`은 큰 미리보기용으로만 남는다.

## 배경 — 단 하나의 진실
1. 레지스트리 `VirtualDesktopIDs` 순서의 GUID를 타일 `dataset.desktopId`와 정확히 비교한다.
2. Native Control Host `getDesktopVisualSnapshot({desktopId: GUID})`를 **동일한 이벤트 수신 가능 Native 포트**에서 요청한다.
3. `reply.ok===true`, `reply.desktopId===GUID`, 진짜 JPEG/PNG/WEBP 데이터가 모두 만족할 때만 CSS backgroundImage 설정.
4. 같은 타일의 일반 재렌더는 이미 확인한 사진을 반복해서 다시 읽지 않는다. 최초 조회와 **Windows 실제 배경 변경 이벤트**만 재조회. 세대(generation) 검사로 늦은 이전 응답 차단.
5. 일반 캐시(`monitorWallpaperActuals`, `monitorWallpaperCache`), `chrome.storage.session`의 이전 팝업 `wallpaperDataUri`, Progman/WGC 캡처는 배경 출처로 사용하지 않는다.

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
- `check_monitor_thumbnail_v2_cleanroom.js`: GUID 오매핑 거부, 비동기 구세대 응답 차단, Native 이벤트에서만 재조회, 정상 HWND/노드/Z/기하 유지, CLOAKED·stale·source 오류 투명 처리, F5 새 DOM에서 레거시 픽셀 소거.
- 구버전 Minimized/노드/배경 이벤트 계약 수정·검증. 모든 Monitor JS 34 PASS, 공식 구조 검사 PASS, 함수 SHA 인덱스 일치.
- **실제 Windows D1/D2 스크린샷과 Monitor 타일 픽셀 비교는 미실시**. LIVE 설치 성공과 화면 수락으로 보고하지 않는다.

## 적용 전 필수
- 운영 설치본 SHA·백업/제어 Host/파일 Host/기존 RCC 상태 확인.
- cleanroom 별도 브랜치 CI PASS 후 기존 설치본 고유 변경을 유지한 딱 네 경로: `monitor-desktop-thumbnail-v2.js`, `monitor.js` 썸네일 분기, `desktop.html`의 단일 스크립트, `monitor-ui-layout.css`; 기존 레거시 스크립트 제외와 index도 정확히 반영.
- 한 번의 설치·한 번의 리로드·실제 D1/D2 변경 시험. 검증 실패 시 기존 파일을 정확한 해시로 복원. 중복 UNKNOWN 재시도 없음.