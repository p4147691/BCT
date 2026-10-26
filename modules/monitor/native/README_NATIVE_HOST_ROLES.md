# Monitor Native Messaging 호스트 역할

## 현재 고정한 운영 분리

| Native Messaging 이름 | 담당 기능 | 검증한 실행 파일 |
|---|---|---|
| `com.pas40.desktop_window_monitor` | 바탕화면 파일·아이콘 조회, 파일 작업, 파일 내 탐색 | `native/1.9.20.128-hidden-all/DesktopWindowMonitorHost.exe` |
| `com.pas40.desktop_window_monitor_control` | HWND, WGC, 가상 데스크톱 및 창 제어 | `native/1.9.20.180-thumbnail-correlated/DesktopWindowMonitorControlHost.exe` |

새 Host를 세 번째로 등록할 필요는 없습니다. 기존 두 등록의 역할이 달랐지만, 파일용 매니페스트가 제어용 컴파일 실행 파일로 바뀌면서 `list` 명령을 처리하지 못했습니다.

## 안전한 등록·배포

- Google Chrome은 `allowed_origins`의 정확한 확장 ID가 허용된 Native Host만 `connectNative`로 실행합니다. 각 Port는 Host 프로세스를 유지하며 **매니페스트의 실행 경로만 바꿔도 기존 Port는 그 즉시 바뀌지 않습니다**. 향후 공식 Monitor 확장 리로드를 1회 수행한 뒤 새 Port 연결을 확인해야 합니다.
- `Publish-MonitorDeployment.ps1`는 버전 게시 전에 `check_monitor_native_host_roles.py --probe`로 두 바이너리를 구분하고, 파일용 `list`와 제어용 `getVirtualDesktops`를 각각 읽기 전용으로 검사해야 합니다. 잘못된 연결이면 게시하지 않습니다.
- `Build-MonitorCore.ps1`는 현재 제어용 소스를 `Host.exe`와 `ControlHost.exe` 이름으로 복사합니다. **이 빌드 결과의 `Host.exe`를 파일용 매니페스트에 연결하면 안 됩니다**. 앞으로 실제 파일 Host 소스를 독립 구축하면 이 중복 빌드도 제거해야 합니다.
- `background.js`의 파일용 Native Port에서는 `event === true`인 자발적인 이벤트가 대기 중인 응답 FIFO를 소모하지 않도록 차단합니다. 실제 `ok:true/false` 명령 응답과 Port 연결 해제 계약은 유지합니다.

## 수락 범위와 부채

- 보관된 파일 Host는 바탕화면 목록·아이콘·디렉터리 목록·UTF-8/한글 읽기·파일/폴더 생성·이름 변경·이동·취소·재실행을 **사용자 파일과 무관한 일시적 시험 폴더**에서 통과했습니다. 임시 파일은 테스트 종료 후 정확히 정리했습니다.
- 프로그램 실행(`open`), 클립보드(`copyFiles`), 휴지통 이동(`deleteItems`) 같은 외부 부작용 동작은 운영 파일 보호를 위해 E2E를 수행하지 않았습니다. `DesktopWindowMonitorHost.exe` 1.9.20.128의 파일 동작 소스는 현재 저장소에서 발견되지 않아 장기적으로 **소스 정본화**가 필요합니다.
- 운영 Host의 `allowed_origins`는 단일 확장 ID로 제한해야 합니다. 파일 경로 보호(바탕화면 밖 경로/링크 거부)를 우회하지 않습니다.
- 실제 운영 적용 전 정확한 원본 매니페스트·확장 소스·버전 영수증을 백업하고, 적용 시 기존 제어용 Host·Core·RCC·Chrome 로그인 상태를 보존합니다.

공식 Chrome 문서: https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
