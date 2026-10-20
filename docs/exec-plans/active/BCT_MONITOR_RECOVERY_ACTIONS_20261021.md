# BWM 복구 버튼 연결 — 2026-10-21

상태: `SOURCE_TESTED / LIVE_NOT_APPLIED`

## 목적

BWM 상단의 기존 비활성 버튼을 임의 shell/UI 자동화 없이 검증 가능한 공식 경계에 연결한다.

## 구현 계약

- `RCC 리로드`: Monitor origin만 허용하는 BCT route가 현재의 정확한 RCC instance 하나에
  기존 `relay_browser / reload-extension` 명령을 보내고 durable receipt의 `APPLIED`를 확인한다.
- `BCT 시작·복구`: Monitor Native Host가 고정된 `BCT Core Supervisor` 예약 작업만 실행하며,
  실행 전후 `127.0.0.1:18790/health`의 service/ready를 확인한다.
- `MCP 터널 복구`: Monitor Native Host가 고정된 `BCT Tunnel Supervisor` 예약 작업만 실행하며,
  사용자 프로필의 공식 health URL 포인터가 가리키는 loopback endpoint의 health/ready를 확인한다.
- `BC 도구 새로고침`: 사용자가 선택한 정확한 ChatGPT conversation/tab/window를 다시 대조한 뒤
  그 탭만 `chrome.tabs.reload`한다. 생성 중인 대화, 대화 키 누락, 식별 불일치는 거부한다.
- 사용자 제공 command/path를 실행하지 않으며 `cmd.exe`, 임의 PowerShell, Chrome UI 클릭을 사용하지 않는다.

## 변경 범위

- Core: `src/bct/runtime_server.py`
- Monitor shell/UI/background: `modules/monitor/extension/*`
- exact BC tab adapter: `modules/monitor/extension/browser/bc-tool-refresh-adapter.js`
- Native Host: `modules/monitor/native/src/MonitorDesktopHost.cs`
- 계약/회귀 검사와 Python tests

## 검증

- exact BC tab adapter: PASS
- BCT shell/Monitor recovery action/thumbnail label 계약: PASS
- Monitor 관련 source-only 회귀: PASS
- Python Monitor runtime/integration/conversation tests: 20 PASS
- Native Host .NET Framework compile: PASS
- `git diff --check`: PASS

`check_monitor_desktop_visual.js`는 격리 worktree에 prebuilt Native payload가 없어 실행하지 못했다.
`check_monitor_ncodex_rdp_route.js`는 현재 main에도 없는 레거시 문자열을 요구하는 기존 checker 문제로
이번 변경과 무관하게 실패했다. 기능 성공으로 숨기지 않는다.

## 운영 제한

이 단계에서는 설치본, Chrome, Native Host binding, BCT Core, RCC, MCP 터널을 변경하거나
재시작하지 않는다. 실제 버튼 클릭 수락시험은 exact main 반영과 명시적인 LIVE 배포 단계 뒤에 수행한다.

