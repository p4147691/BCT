# BCT 인수인계

## 완료 — Unicode desktop clipboard

`desktop_clipboard`의 BCT/VTL 구현, CI, exact-main 배포와 LIVE 수락시험이 끝났다.
`get`/`set` 모두 exact Session Lease와 emergency-stop fence를 요구한다. VTL Agent 2.2는
STA `UnicodeText` API를 사용해 Windows UTF-8 시스템 로캘 on/off와 독립적으로 동작하며,
set은 재읽기 exact match 전에는 성공으로 확정하지 않는다. BCT durable evidence에는
Unicode scalar/UTF-8 byte 길이와 SHA-256만 남고 원문은 최초 성공 `get` 응답에만 붙는다.
VTL PR #47과 BCT PR #228/#229가 required CI를 통과해 병합됐고, BCT Generation 141은
39개 MCP 도구에 `bct_desktop_clipboard`를 포함한다. Agent 직접 및 인증 MCP LIVE에서
한글+보조 평면 문자의 set/get/hash를 확인하고 직전 클립보드를 복원했다. 최종 Lease는
null이고 emergency stop은 false다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_CLIPBOARD_20261019.md`에 있다.

## 완료 — 로그인 세션 Desktop Agent 자동 복구

Desktop Session Agent는 boot service가 아니라 로그인 사용자의 interactive session에
존재해야 화면·창·입력을 정확히 제어할 수 있다. VTL의 `BCT Desktop Session
Supervisor`가 immutable VTL release·manifest·Agent-start source를 검증하고 동일
세션의 exact Agent만 재사용하거나, 종료된 Agent만 복구한다. old/foreign release는
임의 종료하지 않고 mismatch로 남긴다. Scheduled Task는 `LogonTrigger`,
`InteractiveToken`, `LeastPrivilege`로 실행되며, 관리 권한은 Task Scheduler 등록
갱신 때만 필요하다.

LIVE에서 활성 Lease 없음 및 emergency stop 해제 상태의 구형 Agent를 한 번 종료했고,
Supervisor가 current immutable release의 새 Agent로 자동 복구했다. 이후 BCT control
status는 interactive input desktop, null lease, clear emergency stop을 반환했다. 현재
실제 release는 VTL `current.json`, Agent endpoint와 Supervisor receipt로 확인한다.
상세는 VTL의
`docs/exec-plans/completed/bct-desktop-session-supervisor-20261019.md`에 있다.

## 완료 — bounded desktop scroll/drag

`desktop_input`은 기존 exact Window Lease 아래에서 wheel `scroll`과 좌클릭
`drag`를 제공한다. scroll delta와 drag 단계/경로가 제한되며 foreground, 비가림
좌표, Lease, 프로세스 생성 시점, Session/virtual desktop, emergency stop을 실행
직전에 다시 검증한다. VTL Agent 전체 probe와 BCT 집중/분할 CI, exact-main 배포,
인증 MCP disposable-probe 수락시험이 통과했다. 최종 Lease는 null이고 emergency
stop은 false다. 현재 SHA와 generation은 `origin/main`, 두 `runtime\current.json`,
health `release_sha`로 확인한다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_SCROLL_DRAG_20261019.md`에 있다.

## 완료 — Chrome 웹 콘텐츠 exact 제어 V1

`desktop_chrome_content_list`와 `desktop_chrome_content_action`을 LIVE 배포했다.
목록은 정확한 Chrome HWND의 한 visible `RootWebArea`에서 edit/button 메타데이터만
읽고 field value는 반환하지 않는다. 동작은 기존 Window Lease, document title,
활성 tab ordinal/full title, opaque element ID를 모두 재검증한 뒤 ValuePattern set 또는
InvokePattern invoke를 실행한다. LIVE에서 UIA ValuePattern이 background Chrome을
활성화하는 사실이 확인되어 `set_value`는 exact leased 창이 이미 foreground일 때만
허용하고 필요 시 기존 `desktop_window_activate`를 명시적으로 먼저 쓴다. InvokePattern은
foreground 불변일 때만 성공한다. foreground 변경·Lease 손실·호출 후 불명확 결과는
UNKNOWN이며 자동 재시도하지 않는다. text는 raw evidence/output에 넣지 않고 UTF-8
문자/byte 길이와 SHA-256만 남긴다.

VTL PR #37/#38/#39/#40, BCT PR #221/#222와 모든 required CI가 통과했다.
BCT full suite 789개와 focused 61개 테스트도 통과했다. 완료 당시 VTL
immutable main의 Agent 2.0.2와 BCT exact main이 배포됐다. 현재 버전은 고정 SHA
문구를 신뢰하지 않고 각 `origin/main`, VTL/BCT `runtime\current.json`, health
`release_sha`를 기계적으로 비교한다. 완료 당시 health는 READY/OK였고 MCP
catalogue는 두 새 도구를 포함한 38개였다.

인증 MCP LIVE에서 background write는 실행 전 확정 실패했고, 명시적 활성화 뒤
16자/20 UTF-8 byte marker set 및 빈 문자열 clear가 각각 matching length/hash와
`foregroundPreserved=true`로 APPLIED됐다. 후속 조회는 빈 입력을 확인했다. 전용
Chrome for Testing 창은 다시 최소화했고 원래 foreground를 복원했으며 최종 Lease는
null, emergency stop은 false다. 상세 증거는
`docs/exec-plans/completed/BCT_CHROME_CONTENT_CONTROL_20261019.md`에 있다.

## 완료 — Windows UTF-8 설정 독립 VTL 실행

Windows의 **유니코드 UTF-8 사용** 시스템 로캘은 게임/프로그램 호환을 위해 켜거나
꺼도 된다. BCT/VTL은 이 전역 설정을 바꾸거나 재부팅을 요구하지 않는다. VTL의
기계 판정은 명시적 UTF-8 JSON 파일을 사용하고, BCT는 자식 stdout/stderr를 bytes로
받은 뒤 UTF BOM, strict UTF-8, CP949, 현재 Windows ANSI/OEM 순으로 진단 로그만
해석한다. 자식 Python에는 process-local UTF-8 환경만 준다. 구현·focused test는
통과했다. VTL PR #21/#22와 BCT PR #206이 병합됐고, exact main runtime
sync/prewarm와 BCT exact-SHA 배포가 완료됐다. source `origin/main`, 로컬 source,
runtime `current.json`과 health `release_sha`는 최종 점검 때 기계적으로 비교한다.
인증된 LIVE `bct_vtl_validate`와 duplicate receipt도 PASS했다. 상세는
`docs/exec-plans/completed/BCT_VTL_DIRECT_VALIDATION_20261019.md`를 따른다.

## 완료 — 일반 ChatGPT의 직접 VTL-first 검증

목표는 일반 ChatGPT/Codex의 반복 개발 검증을 로컬 BCT + VTL Fast mode에서 끝내고,
통과한 한 후보만 GitHub에 올려 required CI를 최종 1회 수행하는 것이다. 실패 후보마다
Actions를 디버깅 루프로 사용하는 방식은 피한다. 변경 범위에 따라 정적 검사/focused test,
VTL browser/GUI scenario, Full/VM E2E 순으로 가장 싼 충분한 tier를 선택한다.

새 `vtl_validate` capability는 `D:\TOOLS\VTL\current.json`의 immutable release manifest 전체를
검증하고, work scope 안의 browser 또는 profile scenario를 background operation으로 직접 실행한다.
VTL SHA, 입력 SHA, PASS/FAIL/TIMEOUT, 외부 evidence/result 경로가 BCT receipt에 남으며 GitHub
Actions를 dispatch하지 않는다. VTL runtime installer와 외부 evidence/run-ID 계약은 VTL 저장소가
소유한다. VTL PR #18과 BCT PR #203의 exact-head/main CI가 통과했고 해당 BCT
merge가 LIVE generation 121로 배포됐다. 최종 설치 VTL PR #20 main은 한글 사용자 경로를
비대화형 Windows 코드페이지와 무관하게 처리하고, browser cold prepare/Fast selftest가
PASS한 뒤에만 runtime pointer를 공개한다. 인증된 MCP operation
`bct-vtl-direct-live-af1c4fd9-6e75ab68-browser-fast`는 이를 직접 실행해 `APPLIED / PASS`를
반환했다. 같은 operation ID의 재호출은 원 영수증을 반환했고 VTL GitHub workflow는 새로
생성되지 않았다.
일반 ChatGPT는 BCT Control이 새 catalogue를 읽은 세션에서 이 진입점을 사용할 수 있다. 상세는
`docs/exec-plans/completed/BCT_VTL_DIRECT_VALIDATION_20261019.md`를 따른다.

## 완료 — 일반 ChatGPT/Codex의 VTL Desktop Session 공동 사용 계약

일반 ChatGPT 대화도 BCT Control 연결과 현재 MCP catalogue가 실제로 제공되면
VTL Desktop Session Agent를 사용할 수 있다. 실시간 데스크톱 진입점은 BCT Control
MCP이며, GitHub Actions의 VTL workflow는 exact-SHA 검증을 남기는 별도 경로다.

읽기 전용 status/capture/window list는 병행 가능하다. 입력·창 활성화·프로그램
실행은 기존 세션당 단일 Lease가 직렬화하며, 각 대화는 고유 work ID와 짧은 Lease를
사용하고 완료 즉시 반납한다. Lease 충돌 시 대기·보고하고 타 owner의 Lease를
빼앗거나 emergency reset으로 우회하지 않는다. Emergency stop은 전역 중지이고,
UNKNOWN 효과는 무재시도 후 receipt와 화면으로 화해한다. 일반 대화에 전달할 전체
운영 절차는 `docs/USER_GUIDE.md`의 "일반 ChatGPT와 Codex가 데스크톱을 함께
사용할 때" 절에 기록했다.

## 완료 — Lease로 제한된 창 상태·위치 제어

BCT LIVE는 `desktop_window_manage`로 활성 Window Lease에 묶인 정확한 창을
복원·최소화·최대화·이동/크기 변경할 수 있다. 효과 직전에 owner/Lease ID,
HWND/PID/process birth, Session, virtual desktop 및 emergency stop을 다시
검증한다. 창 닫기는 사용자 데이터 손실 경계라 제공하지 않는다.

VTL PR #25와 BCT PR #208의 exact-head/main CI, immutable VTL Agent 1.5 배포,
BCT exact-main 배포 및 인증 MCP LIVE 수락시험이 완료됐다. LIVE 시험은 BCT로
프로브를 실행·바인딩하고 네 상태 동작과 이동/크기 변경, 활성화, 입력을 영수증으로
검증한 뒤 Lease·프로세스·임시 파일을 정리했다. 검증 wrapper는 durable receipt의
`programLaunch.pid`를 사용하고 원자적으로 교체되는 probe JSON 읽기의 일시적인
Windows 공유 오류를 재시도해야 한다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_WINDOW_MANAGE_20261019.md`에 있다.

## 완료 — 로그인 세션 프로세스·파일 진입점 탐색

BCT LIVE의 읽기 전용 `desktop_explore`는 실제 Desktop Session Agent와 같은
Session의 프로세스를 PID/process birth/실행 파일 경로/현재 가상 데스크톱 창에
연결하고, 로그인 사용자의 알려진 폴더와 준비된 드라이브를 반환한다. Lease나
foreground 변경 없이 여러 대화가 병행 조회할 수 있다.

파일 내용과 폴더 순회는 이 기능에 중복 구현하지 않았다. 발견한 경로를 Work root로
명시한 뒤 기존 `read`의 bounded `directory_tree`/file을 사용하므로 기존 scope와
reparse-point 차단이 그대로 적용된다. VTL PR #27, BCT PR #210, Agent 1.6 rollout,
exact-main 배포와 인증 MCP LIVE 조합 검증이 완료됐다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_EXPLORE_20261019.md`에 있다.

## 완료 — Chrome/Explorer 의미 기반 창 선택·바인딩

BCT LIVE의 `desktop_application_target`은 Chrome과 Explorer를 정확한 process
family와 top-level window class로 분류하고, 선택적으로 Unicode 창 제목으로
좁힌다. `list`는 읽기 전용이고, `bind`는 현재 Session/virtual desktop 후보가
정확히 하나일 때만 기존 Window Lease를 발급한다. 후보 0개·여러 개·Agent 목록
truncation은 제어 효과 전에 실패하므로 좌표나 PID 추측으로 다른 창을 잡지 않는다.

BCT PR #212의 exact-head/main CI, generation 128 exact-main 배포와 인증 MCP LIVE
수락시험이 완료됐다. LIVE에서는 Chrome 3개와 Explorer 0개를 분류하고 고유한
Chrome 창을 HWND/PID/process birth/Session/virtual desktop fingerprint로 bind한
뒤 활성화나 입력 없이 Lease를 즉시 반납했다. Chrome 탭/프로필 연결은 아래의 별도
increment로 완료됐다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_APPLICATION_TARGET_20261019.md`에 있다.

## 완료 — Chrome 프로필·탭 의미 기반 선택·바인딩

Agent 1.8.1은 기존 Chrome 창을 UI Automation으로 읽어 제한된 프로필 라벨,
탭 제목과 현재 선택 탭을 반환한다. URL은 반환하지 않는다. BCT의
`desktop_application_target`은 `profile_query`, `tab_title_query`,
`tab_scope`(`active`/`any`)로 좁히고, UIA 불완전·0/복수 후보·window/tab
truncation이면 bind 전에 실패한다. list/bind 모두 Chrome을 실행·종료·활성화하거나
입력하지 않는다.

초기 Agent 1.8.0 LIVE에서 helper UTF-8 stdout을 Windows 코드페이지로 해석하는
오류가 발견됐고 fail-closed했다. VTL PR #32가 strict UTF-8 자식 스트림과 강한
응답 검증을 추가했다. 정확한 완료 당시 SHA는 아래 완료 증거 문서에 보존하고,
현재 상태는 각 `origin/main`, runtime `current.json`, health `release_sha`를 기계적으로
비교해 판정한다.
인증 MCP LIVE는 Chrome 4개 중 Unicode 프로필+현재 탭 조합으로 1개를 bind/release했고,
기존 Chrome PID/process birth/HWND는 모두 보존됐으며 최종 Lease는 null,
emergency stop은 false였다. 상세는
`docs/exec-plans/completed/BCT_CHROME_SEMANTIC_TARGET_20261019.md`에 있다.

## 완료 — foreground를 보존하는 Chrome exact-tab 전환

BCT LIVE의 `desktop_chrome_tab_select`은 기존 Chrome Window Lease와 정확한
HWND/PID/process birth/Session/virtual desktop, ordinal 및 방금 관측한 전체 탭
제목에 묶여 한 탭만 전환한다. VTL Agent는 UIA 선택 호출 대신 exact client HWND에
제한된 window message를 보내며 전후 foreground가 같음을 확인한다. 탭을 열거나
닫거나 이동하지 않고 URL도 다루지 않는다.

초기 UIA 구현이 background 창을 foreground로 올린 실제 결함은 UNKNOWN으로
차단됐고, 원래 탭과 foreground를 별도 보상했다. 새
`desktop_chrome_tab_reconcile`은 동일 work/principal의 정확한 changed-foreground
UNKNOWN에 한해 no-Lease/no-stop, exact foreground/window/active-tab 상태를 읽기
전용으로 증명한 뒤 그 claim만 해제한다. 과거 Work는 새 action을 추가할 수 없으므로
원래 `desktop_chrome_tab_select` 권한에서만 이 좁은 화해 권한을 파생한다.

Chrome 접근성 제목의 메모리 수치는 변하므로 전체 제목은 fresh inventory 직후
소비한다. 활성 탭을 바꾸면 top-level 창 제목도 바뀌므로 복구 조회에 이전 창 제목
필터를 유지하지 않는다. exact-main CI/배포, 과거 UNKNOWN 화해, background 실제
전환과 원복, foreground/프로세스 보존 및 최종 무Lease/무래치 상태까지 완료했다.
상세와 정확한 완료 증거는
`docs/exec-plans/completed/BCT_CHROME_TAB_SELECT_20261019.md`에 있다.

## 완료 — Explorer 실제 폴더 경로 선택·바인딩

`desktop_application_target`의 Explorer 경로는 기존 로컬 폴더의 절대
`folder_path`를 받아 Agent 1.7의 Shell 위치와 정확한 HWND/PID/process birth/
Session/current virtual desktop fingerprint를 결합한다. 상대 경로·없는 폴더는
거부하고 가상 Shell 위치는 로컬 경로로 추측하지 않는다. 목록은 읽기 전용이며
bind는 후보가 정확히 하나일 때만 기존 Window Lease를 발급한다.

VTL PR #29와 BCT PR #214, 양쪽 CI, exact-main immutable VTL runtime/Agent 1.7,
BCT generation 130 배포 및 인증 MCP LIVE exact-list/bind/release 수락시험이
완료됐다. 최종 제어 상태에는 Lease와 emergency-stop latch가 없다. Chrome
탭/프로필 식별도 위 별도 increment로 완료됐다. 상세는
`docs/exec-plans/completed/BCT_EXPLORER_PATH_TARGET_20261019.md`에 있다.

## 완료 — Adaptive CI와 VTL exact-SHA 데스크톱 스모크

BCT PR #199는 보수적 변경 범위 판정, 정확 중복 unittest 제거, 네 개의 결정적
가중 샤드, 독립 browser-bridge gate를 추가했다. 알 수 없는 실행 경로는 core와
browser 전체 검사로 fail closed하며 문서-only 변경만 경량화한다. 발견된 751개
인스턴스 중 같은 test ID·class·method·instance state인 import 재노출 184개만
제거했고, 567개 고유 테스트를 정확히 한 번씩 실행한다.

검증된 BCT 구현 commit `f9b299d`는 CI run
`39169773634`에서 scope/preflight/core 4-shard/browser Windows E2E를 모두
통과했다. 전체 벽시계는 211초로 이전 직렬 workflow 약 674초보다 약 69%
줄었다. VTL repo의 Session 1 runner는 같은 BCT SHA를 별도 checkout하여 run
`39169787101`에서 status/capture/monitor/windows read-only smoke를 18초에
통과했다. launcher fail-fast build 산출물은 package-purity 검사 전에 launcher
root 아래 `bin/obj`만 bounded cleanup하고 Windows E2E 전에 재빌드한다.

BCT에는 self-hosted runner나 cross-repo Actions credential이 없으므로 VTL 검증의
자동 dispatch는 아직 하지 않는다. 현재는 VTL 소유 수동 exact-SHA workflow가
GitHub 증거를 남긴다. 자동화하려면 사용자 승인 아래 별도 BCT Session 1 runner
등록 또는 최소 권한 GitHub App/fine-grained token 중 하나를 선택해야 한다.
런너 identity나 credential을 임의 변경하지 않는다. 상세 증거는
`docs/exec-plans/completed/BCT_ADAPTIVE_CI_V1_20261019.md`에 있다.

## 완료 — 제한된 프로그램 실행과 새 PID 창 바인딩

BCT LIVE는 인증된 `desktop_program_launch`를 제공한다.
활성 `session` Lease 아래에서 존재하는 절대 비-reparse `.exe`와 bounded
문자열 인수 배열만 `UseShellExecute=false`로 실행한다. 새 PID/process birth/
Session을 기록하고 그 PID가 현재 가상 데스크톱에 만든 보이는 최상위 창을
입증할 때만 같은 Lease를 정확한 창 fingerprint로 원자적으로 승격한다.

창 대기 중 전역 control lock을 잡지 않아 긴급정지는 독립적으로 호출할 수
있고, 나머지 Lease 효과는 transition marker로 차단된다. 실행 뒤 transport가
불명확하면 UNKNOWN으로 남기며 재시도하지 않는다. 새 PID 소유 창이 없으면
실행은 APPLIED이지만 unbound로 반환한다. Chrome singleton처럼 기존 프로세스로
넘기는 앱을 임의로 바인딩하지 않는다.

VTL PR #14와 BCT PR #197의 CI, Agent 1.4 exact-source rollout, BCT exact-main
배포와 인증 MCP LIVE E2E가 통과했다. LIVE E2E는 다른 work 거부, 활성화,
한글 입력 실제 관측, 긴급중지/리셋 및 최종 무리스/무래치 상태까지 확인했고
프로브와 임시 파일을 제거했다. 완료 증거는
`docs/exec-plans/completed/BCT_DESKTOP_PROGRAM_LAUNCH_20261019.md`에 있다.

다음 데스크톱 parity 경계는 프로세스·파일 탐색, Chrome/Explorer의 상위 수준
workflow, 창 닫기 또는 Chrome의 process-family/profile-aware 바인딩 중 하나로
별도 설계한다. 이번 경계에 임의 shell, 자동 로그인이나 Scheduled Task를 섞지
않는다.

## 완료 — 현재 세션 정확한 창 목록·활성화

BCT LIVE는 현재 가상 데스크톱의 보이는 최상위 창을 exact fingerprint로
조회하고, 활성 `window` Lease에 묶인 숨김/최소화되지 않은 정확한 창만
foreground로 활성화할 수 있다. owner/lease, HWND/PID/process start, Session,
virtual desktop, 긴급정지를 효과 직전에 재검증하며 UNKNOWN은 재시도하지
않는다. 프로그램 실행과 창 상태·위치 제어도 이후 별도 완료됐다.
완료 증거는
`docs/exec-plans/completed/BCT_DESKTOP_WINDOW_CONTROL_20261019.md`에 있다.

## 현재 작업 — 신뢰된 다중 ChatGPT 협업 정상화

보호 경로 이전보다 실제 Manager → Worker 협업을 우선한다. 운영 기준은 계속
`D:\BCT`이며 `%LOCALAPPDATA%` 또는 `BCT-Protected` 이전은 협업의 선행 조건이
아니다. 기존 보호 경로 소스와 영수증은 보존하지만 현재 본류에서는 보류한다.

- 기존 Principal/Work/Policy는 프로젝트 범위와 사용자 목표를 한 번 묶는 경계로
  유지한다. 현재 Policy의 일반 개발 작업은 이미 반복 승인 대상이 아니다.
- epoch/lease/Claim, exact attachment, ACK/receipt, UNKNOWN 무재전송은 충돌·중복·
  잘못된 대화 전달을 막는 정합성 계약이므로 유지한다.
- 정적 Schema 2 Work allowlist는 새 Work마다 설정·배포를 요구하는 실제 병목이라
  제거한다. 전역 스위치는 비상 정지용으로 유지하고, ON 이후 새로 시작한 세션만
  `RCC_RESULT_POLL_V1`로 SQLite에 고정한다. 기존 세션은 migration 기본값
  `LEGACY_RETURN_V1`을 유지하여 과거 Wake/UNKNOWN을 재해석하지 않는다.
- Worker assignment는 `read` 전용에서 프로젝트 범위의 일반 개발 작업으로 넓힌다.
  deploy/service control/credential/delete/브라우저 제어 같은 고위험 작업은 자동
  Worker 범위에 포함하지 않는다.
- 최종 완료 판정은 PR/CI가 아니라 새 격리 Work에서 Manager 1 + Worker 2의 실제
  결과 영속화, 종합, FOLLOW_UP, COMPLETE, ACK, 중복 방지 및 Manager 교체 복구가
  성공한 뒤에만 내린다. LIVE 변경과 Chrome 메시지 전송은 묶은 운영 승인 후 한다.

세부 계약은
`docs/exec-plans/active/BCT_TRUSTED_COLLABORATION_NORMALIZATION_20261017.md`를 따른다.

## 중단 작업 — 보호된 운영 경로 이전

사용자 결정으로 `%LOCALAPPDATA%\BCT`/`BCT-Protected` 이전과 추가 ACL 강화는
중단했다. 운영 정본은 `D:\BCT` 하나이며 `bct.toml`에서도 보호 runtime을 활성
배포 프로필로 제공하지 않는다. 이미 만든 일반화된 보호 경로 코드·격리 테스트,
독립 worktree와 기존 영수증은 감사 자료로 보존하지만 협업 활성화의 선행 조건이나
현재 실행 계획으로 사용하지 않는다. LIVE·Registry·ACL·RCC/Chrome에는 역이전이나
추가 변경을 수행하지 않는다.

## 현재 작업 — Durable Orchestration PR C (DRAFT 준비, 운영 비활성)

PR A #149와 PR B #150이 병합된 최신 검증 main에서 독립 worktree로 PR C를 구현했다.
PR B의 영속 `orchestration_dispatch_outbox`를 기존 RCC Worker 전송·PR2 상태
계약에 연결하고, 결과 커밋 뒤 생성되는 Manager Wake도 같은 단일 dispatcher가
이벤트 우선/2초 bounded polling으로 전달한다.

- Worker 전송은 exact attachment/epoch/generation/Policy/lease를 실제 pipe write
  직전에 재검증한다. write 호출이 시작된 뒤 오류는 항상 UNKNOWN이며 재전송하지 않는다.
- RCC 제출 ACK, Worker `RESULT_PERSISTED`, PR2 최종 ACK, RCC result-ack은 서로
  다른 상태다. exact receipt와 JS/Python resultHash 일치 뒤에만 Assignment 완료,
  Manager Wake, PR2 ACK를 한 SQLite transaction으로 확정한다.
- Manager Wake는 pipe-open 전에는 PENDING이다. 실제 write 직전 callback에서만
  Work/Manager epoch/lease/attachment/dispatcher fence를 검증하고 DELIVERING으로
  claim한다. UNKNOWN Wake는 결과 조회만 하며 재전송하지 않는다.
- Outbox와 Wake는 한 dispatcher lease의 독립 keyset cursor로 공정하게 순환한다.
  앞선 8개 RCC 장애가 9번째 Wake를 굶기지 않는 회귀를 포함한다.
- 격리 focused 82 PASS, 전체 558 PASS, compileall/diff check PASS,
  pre-commit 독립 감사 P0/P1/P2 없음. 정확한 Draft PR/CI는 push 후 기록한다.
- RCC RESULT_PERSISTED의 신뢰된 즉시 push는 아직 없다. 이벤트는 Core 내부 commit
  signal이고, RCC 결과 발견은 bounded polling 복구 경계다.
- RCC Named Pipe의 실제 Windows DACL/서비스 주체 제한은 아직 실증되지 않았다.
  따라서 `DEPLOYMENT_BLOCKED`; Schema 2 기본 OFF, LIVE/서비스/RCC/Chrome 변경 금지다.
- 공유 `D:\BCT\source`, PR3-o 미커밋 작업, stash, Issue #111,
  기존 UNKNOWN/Claim/consumed_at과 과거 영수증은 건드리지 않았다.

상세 계약과 테스트 행렬은
`docs/exec-plans/active/BCT_DURABLE_ORCHESTRATION_PR_C_20261016.md`를 따른다.

## 현재 작업 — Issue #111 manager wakeback (LIVE_DEPLOYED, hosted E2E ACCEPTED)

Manager wakeback V1은 PR #112로 main에 병합되어 exact-SHA LIVE 배포까지 완료했다.
이후 BCT Control을 새로고침해 hosted `bct_orchestrate` 가용성도 확인했다. 첫 신규
manager→worker→manager wake E2E는 기존 LIVE나 기존 UNKNOWN/claim을 변경하지 않고
시도했으나, 공유 RCC instance fence 때문에 새 assignment나 browser delivery 전에
안전하게 중단했다.

- 알려진 terminal worker result와 같은 SQLite transaction에 immutable manager-wake
  intent를 저장한다. RCC 전송 실패가 worker result를 재실행하거나 지우지 않는다.
- wake는 manager epoch, exact attachment generation, RCC instance/session, tab,
  conversation, relay role, binding receipt 및 deterministic delivery ID로 fence한다.
- manager takeover 시 이전 `PENDING` wake는 `STALE`로 남고, 새 manager attachment로
  별도 epoch event만 생성한다. `DELIVERING`/`UNKNOWN`은 외부 효과가 불명확하므로
  자동 재통지하지 않는다.
- RCC `send-wakeback`은 더 이상 `returnTo`를 `WORKER`로 바꾸지 않고 호출자가 준
  exact manager role을 보존한다. RCC candidate는 1.0.20 / build
  `2026-10-15-rcc-manager-wakeback-v13`이다.
- Local gates: `python -m unittest discover -s tests -v` **193 PASS**,
  `python -m compileall -q src tests`, `git diff --check`, RCC source/Node
  regression all PASS. PR #112 passed BCT CI run `38616742752` and its merged
  source is the generation-85 LIVE Core release.  Verify current source/runtime
  identity through `origin/main`, local `HEAD`, `current.json.source_head`, and
  `/health.release_sha`; do not treat this handoff as a live SHA authority.

새 무해한 target에서의 단일 worker 결과 → durable manager wake는 검증됐다.
`issue111-wake-e2e-86ea3a2-01`은 fresh exact attachments에서 worker
`APPLIED`, manager wake `DELIVERED`를 기록했다. 기존 UNKNOWN은 재전송하지
않았다. 다만 최초 post-refresh preflight는 ACTIVE `BCT-ISSUE111-LIVE-20261015`와 UNKNOWN
`rcc-localbridge-rename-tab594833023-20261015-02`가 같은
`rcc-instance:6174664e1c1b4e6db1d4729c841db3c9` resource를 점유한 것을 확인했다.
새 E2E의 node-sync도 이 shared resource를 claim하므로, 충돌 상태에서 실행하지
않았다. 이 UNKNOWN/claim 또는 ACTIVE work를 재전송·해제·takeover·재사용하지 말고,
read-only evidence와 canonical reconciliation이 안전한 fresh target을 허용할 때만
재개한다.

## 현재 검증 상태

Durable Orchestration is not yet LIVE accepted. Follow the current-gate section
of `docs/exec-plans/active/BCT_DURABLE_ORCHESTRATION_V1.md`: freeze features;
single roundtrip -> durable recovery -> one manager/worker -> multi-worker and
manager takeover. Preserve historical UNKNOWN/claims. PR #105 fixed retirement
of an already-persisted submitted bootstrap record at the real next-dispatch
entry path. Exact-head/main CI, deployment, one existing-tab roundtrip and
post-reload durable receipt retrieval passed. The next single manager/worker
attempt submitted once but ended UNKNOWN during response capture.

READ-only DOM evidence identifies a concrete routed-turn matching defect:
the collapsed long user-message wrapper adds an aria-hidden ellipsis outside
the actual message body. RCC includes it in textContent, so the exact 1,244-char
prompt becomes 1,245 chars and ROUTE_TURN_NOT_RESOLVED follows. The worker's
matching result is visible, but is not promoted to an accepted receipt. The
separate net::ERR_ABORTED signal's origin is not established. Repeated-failure
policy stopped speculative patches, deployment and chained E2E. On explicit
continuation, an isolated tree/selector fixture reproduced the failure in both
real normal and injected direct-recovery entry paths. RCC 1.0.19 excludes only
the exact hidden ellipsis sibling of data-search-result-target; literal text
and unknown shapes stay unchanged. Regression coverage includes collapsed and
expanded messages, Unicode/newlines/code, nested wrappers, ambiguous/wrong
turns and conversation identity. Promotion and a fresh single-manager gate are
still pending. Do not resend/release the quarantined attempt or rerun successful
earlier gates. CLI #106 and monitor follow-ups remain outside this correction.

Latest user clarification authorizes this correction through PR/CI/main and
exact-SHA deployment plus RCC reload. This supersedes the brief LIVE hold.
It does not authorize CLI updates, Chrome restart or historical UNKNOWN/claim
changes. Resume staged acceptance only on fresh, unclaimed targets after the
exact payload/build checks; stop another repeated failure for evidence review.

Aggregate RCC status versus direct state, presence freshness, and stale
GENERATING/probe fallback are separate follow-ups in GitHub #82, not proven
causes of this response-capture failure. Do not infer full-chain completion
from component acceptance.

왕복 절감 후속 구현은 `docs/exec-plans/completed/BCT_BOUNDED_VERIFICATION_20261014.md`에서
추적한다. verify, bounded CI wait, compact status와 durable result wait는 PR #81과
Windows 129개 테스트, main CI 및 LIVE/hosted connector E2E를 통과했다. 같은 7개 작업의
호스팅 호출을 2회로 줄인 연속 비교에서 7.692초 → 2.097초였다. 작은 표본이며 로컬 자체의
처리속도 향상이나 모델 추론시간 개선으로 해석하지 않는다. 사용 계약은 `docs/VERIFICATION.md`다.
별도 개선 원장 대신 기존 GitHub Issues를 사용하며 비차단 후속 병목은 #82에 기록했다.

`BCT_PLATFORM_PACKAGE_V1=LIVE_ACCEPTED`; `BCT_CORE_RELEASE_BOUNDARY=LIVE_ACCEPTED`.

- GitHub `p4147691/BCT`의 `main`이 유일한 공식 소스이며 `D:\BCT\source`는 그 main의
  깨끗한 로컬 checkout이다. 현재 정합성은 문서에 금방 낡는 SHA를 복사하지 않고
  `origin/main`, 로컬 `HEAD`, `D:\BCT\runtime\current.json`의 `source_head`, `/health`의
  `release_sha`가 모두 같은지 기계적으로 비교해 판정한다.
- 운영 release는 `D:\BCT\runtime`, receipt와 session 상태는 `D:\BCT\data`에 있다.
- BCT core, MCP, health와 BCT Monitor가 한 서비스/한 release에서 실행된다.
- 파일·Git·GitHub·배포·서비스·RCC·Python/PowerShell/argv 실행과 지속 세션은
  BCT 구현과 공통 operation receipt를 사용한다.
- Python과 PowerShell은 일반 개발 실행으로 사용할 수 있다. 지속 mutation, 배포, 서비스 및
  브라우저 변경은 별도의 주의 경계를 유지한다.
- BCT runtime은 ACT 모듈을 import하지 않는다. 초기 `D:\PROJECTS\BCT` checkout과 연결
  worktree는 `D:\Archive\BCT-Bootstrap-20261013`에 rollback/bootstrap 증거로 보존했고,
  활성 BCT 소스 정본은 `D:\BCT\source` 하나뿐이다. ACT 외부 연동의 잔여 의존성은
  완전 전환 전까지 별도로 추적한다.
- 기능별 정확한 소유권은 `docs/CAPABILITY_OWNERSHIP.md`, 사용법은 `docs/USER_GUIDE.md`를 따른다.
- Core release에는 Core 실행 코드와 읽기 전용 status UI만 들어간다. Monitor, RCC, BDC의
  유지 소스는 `modules/`에 있지만 Core runtime에 복사되지 않는다.
- ChatGPT App은 기존 App ID와 연결을 유지한 채 `BCT Control` 1.0.0으로 이름·설명을
  변경했다. 원격 터널도 `BCT Control Private`로 정리했고, 로컬 인증 호출과 ChatGPT의 도구
  새로 고침에서 BCT MCP 22개 도구가 확인됐다.
- `bct_read`는 기존 파일 읽기를 유지하면서 `operation: "directory_tree"`로 제한된 폴더
  목록을 제공한다. 조회 결과는 file/directory/symlink를 구분하고 work root 밖 및 link/reparse
  point 추적을 막는다. 이 기능은 GitHub CI와 LIVE MCP의 실제 `D:\BCT` 조회로 검증했다.
- BCT RCC, BCT ChatGPT New Tab, BCT Auto Proxy는 각각 독립 설치 모듈로
  `D:\ChromeExtensions`에서 실행된다. Proxy helper/wireproxy의 실행 backend는
  `D:\BCT\runtime\modules\chrome-auto-proxy`이며 더 이상 ACT runtime을 사용하지 않는다.
- 구형 ACT MCP(18769)와 ADC agent(18766)는 exact PID·시작시각·명령줄 fence와 durable
  receipt로 퇴역했다. BCT Core(18790), RCC, Monitor Native Host와 Proxy는
  전환 후에도 정상이다.
- 과거 staging/verify 사본은 `docs/LOCAL_LAYOUT.md`에 기록한 SHA-manifested Archive로 이동했다.
  실행 중인 도구와 project 후보는 이동하지 않았다.

## 현재 결정

- 이름: BCT. 약어 풀네임은 미정. 저장소 p4147691/BCT, private, main.
- 기능을 원격으로 끌어다 쓰는 wrapper에 머물지 않고 실제 기능 소스와 테스트를 BCT에 둔다.
- 기존 ACT 운영과 MCP/Chrome 연결을 보존하면서 기능별로 전환한다.
- core / features / integrations의 작은 단일 패키지로 시작한다.
- node_id / 표시 속성 / connection generation / authenticated principal / work ownership을 분리한다.
- 공통 정책 판단 구현은 하나, 실행 직전 대상 검사와 원격 인증은 실행 경계에서 유지한다.
- 설계의 유일한 상세 기준은 docs/DESIGN.md다.

## 완료된 구현과 현재 경계

FIRST_SLICE_COMPLETE / GITHUB_INTEGRATION_V1_ACCEPTED / DEPLOYMENT_SERVICE_V1_ACCEPTED / MCP_V1_ACCEPTED / RCC_V1_ACCEPTED.
코어 구조·노드 신원·권한 경계 및 동시 변경/중복 실행/인계 계약을 구현했다.
파일 읽기·원자적 쓰기, Python test, expected HEAD·정확한 dirty set·new-file SHA proof 기반 Git commit을 BCT 소스로 구현했다.
13개 first-slice 로컬 테스트에서 실제 격리 Git 흐름, wrong principal, duplicate operation, UNKNOWN 중복 차단, foreign dirty, stale hash/HEAD, symlink escape 및 인계를 검증했다.
GitHub Actions run `38234844806`에서 최신 Actions major로 Windows CI가 통과했다.
ACT 전체 legacy feature 호환을 목표로 하지 않는다. BCT의 core, 개발 흐름, GitHub,
배포·서비스, MCP, bounded RCC 제어가 각각 live acceptance를 통과했다.
기존 RCC 탭/role binding은 계속 보존된다. 활성 GitHub Runner 네 개는 GitHub의 같은
runner ID·이름·label을 유지한 채 `D:\BCT\runtime\runners\github`로 이동했고 모두
`online / busy=false`가 확인됐다. 이동 receipt는 `D:\BCT\data\migrations`에 보존한다.

GitHub integration V1은 BCT 소스로 구현되었다. exact-SHA branch push, deterministic request marker를
사용한 PR 생성 중복 방지, required-check 조회, exact-head merge 및 verified `main` fast-forward를
공통 operation receipt와 resource claim으로 실행한다. 인증은 공식 `gh`의 기존 credential store를
사용하고 token은 BCT 상태에 저장하지 않는다. Git commit의 실행 전 확정 실패가 HEAD와 dirty set을
보존한 경우 claim을 안전하게 해제하는 회귀까지 포함해 전체 19개 로컬 테스트,
PR #2 Windows CI run `38241115179`, merge commit `9140bc07d7e0fac9b809a208818a20f6bf094653`,
merge-main push CI run `38241278661`이 통과했다. 동일 operation 및 새 operation ID의 중복
push/PR/merge가 실제로 추가 효과를 만들지 않는 것을 확인했다. 상세 계약은
`docs/GITHUB_INTEGRATION.md`, 증거는 `docs/exec-plans/completed/BCT_GITHUB_INTEGRATION.md`를 따른다.

실사용 중 발견한 commit-failure claim 문제는 PR #4, merge
`c770eb5595856776db63fbb085ea148f731bdb92`로 수정·CI 검증했다. 중앙 BOOTSTRAP의 BCT 상태도
PR #23, merge `f478d5e75c57e4e8455914b503d1c5f5fee41546`으로 갱신했다.

Deployment/service V1은 source checkout과 runtime을 분리한다. `bct_runtime_v1` named profile만
`D:\BCT\source`의 명시된 파일을 `D:\BCT\runtime\releases\<source-head>`로 옮길 수 있다.
clean main/exact commit, file SHA manifest, atomic current pointer, durable deployment receipt,
exact PID/executable/creation fingerprint/generation/instance health, duplicate operation fencing,
stop/restart 검증 및 failed-readiness 전체 rollback을 구현했다. focused 4개와 전체 23개 테스트,
compile 및 diff 검사를 통과했다. 상세 계약은 `docs/DEPLOYMENT_SERVICE.md`를 따른다.

PR #6의 exact head `a3e8cddcf3a1293741a14408a5ac9f5129e43147`은 Windows CI run
`38244408181` 통과 후 merge `5ac41fd61636a5c6a4486d84702ba22069c65c96`로 통합됐다.
해당 merge를 최초 운영 release로 배포해 manifest
`ae95acec3d830e19d6392e4676a03212c13e9bdeba744f969fb46854680d745a`와 모든 source/runtime
파일 해시 일치를 확인했다. service는 최초 PID 10672에서 정확히 한 번 restart되어 PID 19344,
generation 2가 되었고 health `OK`, duplicate deploy/restart 재호출에서 추가 process가 생기지 않았다.
ACT/MCP/RCC/Chrome은 이 acceptance에서 변경하지 않았다.

MCP V1은 별도 정책·receipt·service를 만들지 않고 BCT core service에 Streamable HTTP `/mcp`를
탑재한다. 실제 `OperationCoordinator.capabilities`에서 `bct_<capability>` 도구를 생성하므로
미구현 도구가 catalogue에 남을 수 없다. loopback endpoint는 별도 durable bearer token으로
인증되며 모든 실행은 기존 work owner, operation ID, resource claim 및 outcome 경로를 그대로
사용한다. focused test에서 무인증 401, initialize/list, exact 14-tool catalogue, work create/recover,
실제 read, duplicate receipt, conflicting work 거부를 검증했다. 상세는 `docs/MCP_INTEGRATION.md`다.

MCP source는 PR #8로 통합되었고, 실제 upgrade preflight에서 발견한 두 호환성 문제도 남기지
않았다. PR #9는 이전 release를 자기 manifest로 검증하면서 새 release는 새 profile과 exact match하게
했고 Windows restart 전 exclusive port release fence를 추가했다. PR #10은 health contract version을
도입해 V1 service는 V1 증거로 정확히 검사한 뒤 업그레이드할 수 있고, 새 V2 service는 MCP readiness를
반드시 증명하게 했다. 최종 live release는 `5d18519e9a0d3b68ef60ab7ee3c3551d741628ab`,
manifest `2f5b31d3340991429b162aff4c18ca3268b66d60b09a477d5ad06707f8486387`, PID 35428,
generation 4, health contract 2다. 표준 MCP protocol `2025-11-25`에서 무인증 401, 14개 exact tool,
실제 work/read/duplicate receipt를 확인했다. Codex global server `bct`를 stable endpoint에 등록하고,
새 Codex 프로세스가 BCT work 생성과 read를 실제 수행했다. 기존 ACT MCP 설정은 변경하지 않았다.

## 모델 전환

사용자는 Astra로 코어 구조·노드 신원·권한 경계 설계까지 마친 뒤 SOL로 구현을 이어가기를 선택했다.
이 문서는 SOL 인수인계 기준이다. 문서 작성이 앱 모델 설정 변경을 의미하지 않는다.
새 작업을 중복 생성하거나 초기 구조 토론을 반복하지 말고 첫 구현을 진행한다.

## 반복 금지

- ACT 데이터/운영 폴더 초기화, 기존 UNKNOWN operation 재실행 금지.
- ID/역할/프로필 이름만으로 기술 권한 부여 금지.
- 만료 lease만으로 살아 있는 실행을 takeover하지 않음.
- 동일 operation을 실패/timeout 후 자동 재실행하지 않음.
- source/설계 완료와 LIVE acceptance를 혼동하지 않음.
- 구현체를 BCT로 가져오기 전에 라이선스·의존성과 현재 계약을 확인.
- 기능 이전을 이유로 사용자의 기존 MCP/Chrome 설정을 임의 초기화하지 않음.

RCC V1은 현재 운영 확장 22개 파일과 Native Host source/manifest를 exact SHA 기준선으로 BCT에
보존했다. `relay_browser`는 exact instance만 사용하며 BCT operation ID를 Native Host와 확장의
mutation operation ID로 재사용한다. pre-dispatch 실패는 확정 실패로, dispatch 이후 응답 유실은
UNKNOWN으로 기록해 자동 재실행하지 않는다. state 응답의 token/secret/authorization은 BCT
receipt에 들어오기 전에 제거한다.

PR #13 head `72b50d391d5fd901696b732ac3d2779d1903112a`는 CI run `38254069968` 통과 후
merge `15f8ce551e7360ab77266c331758c0e249706d85`로 통합됐다. main CI run
`38254397056`도 통과했다. 전체 38개 테스트, compile, diff 검사가 통과했다. live release는
동일 SHA, manifest `35f4c8e2ccaa517e37b8449e888bce64f03003845abbf93e40dd6003f26288c6`,
PID 38252, generation 7이며 source/runtime mismatch는 0이다. MCP catalogue는 15개 도구를
노출하고 `bct_relay_browser` read-only state 호출과 duplicate receipt가 실제 RCC instance
`b91fe69d935f4e3893caa30836e4b13c`에서 통과했다. 기존 보호 탭 `594832035`와 다른 열린 탭,
bindings, pending 상태는 변경하지 않았다.

## 다음 작업

제어 경로와 브라우저 모듈의 ACT runtime 퇴역 및 활성 GitHub Runner 경로 이동은 완료됐다.
DesktopWindow Monitor 2.0은 Native HWND/thumbnail을 창의 정본으로 유지하고, 노드·조직
정보를 창 존재 판정에서 분리하며, 구형 ACT startup/focus 호출을 기본 비활성화했다. 기본 화면은
RCC가 실제 관측한 Chrome window/tab ID와 OPEN·active·generating 상태만 읽기 전용으로
보여준다. 이 `N1`, `N2` 표시는 순번일 뿐 역할·권한·소유권·물리 HWND를 만들지 않는다. PR #43,
merge `f00510b9c6411b4d6ee8dd5636594f4957f08cc6`과 main CI 통과 후 exact 6-file 설치 배포와
Chrome reload가 완료됐다. 같은 extension ID에서 새 Native Host 연결, BCT/Laya health와 RCC
보존까지 확인했다. 남은 순서는 SHA manifest를 남긴 구형 runner 백업/비활성 서비스 정리다. 이후 작업도 새 관리
계층을 추가하지 않고 같은 work/operation/receipt → GitHub main → exact deploy → live
acceptance 흐름으로 진행한다.

## Batch read 및 왕복 절감 완료

`bct_read`는 기존 file/directory-tree 계약을 유지하면서 최대 20개의 bounded read를 한
operation으로 처리한다. 모든 요청을 선검증하고 resource claim을 원자적으로 잡으며, 파일당
512 KiB·파일 합계 1 MiB·directory entry 합계 2,000 제한을 적용한다. receipt에는 content를
저장하지 않고 SHA와 메타데이터만 남긴다. 부분 실행 실패도 operation을 `FAILED`로 종결하고
claim을 해제한다.

PR #72는 CI 통과 후 merge `212623809a5cff60efa5543b90d531ed7512b90f`로 통합됐고 동일 SHA가
LIVE Core에 배포됐다. 전체 111개 테스트, compile, diff 검사가 통과했다. LIVE direct-MCP에서
5개 개별 read 165 ms 대비 한 batch 41 ms였고 모든 SHA가 일치했다. Hosted ChatGPT E2E의
`bct-batch-read-chatgpt-e2e-op-01` 영수증은 `FINISHED / APPLIED`, 5/5 OK, 27,751 bytes이며
ChatGPT가 관찰한 batch tool call은 4.930초였다. 서로 다른 경로의 수치는 직접 차감하지 않는다.

속도 우선 원칙은 같은 안전·승인 경계의 독립 read를 가능한 한 한 batch로 묶는 것이다. write,
배포, 서비스 제어, 브라우저 mutation의 승인 경계나 operation ID 멱등성, atomic claim,
UNKNOWN no-retry, exact-SHA 배포 조건은 완화하지 않는다.

## Tunnel health 및 MCP 지연 종결

### 2026-10-18 강제 재시작 후 복구 상태 — 외부 MCP ingress BLOCKED

강제 Windows 재시작 뒤의 read-only 점검에서 Core는 자동 복구됐다. `BCT Core
Supervisor`가 14:49 KST에 시작해 generation 104 / PID 16248로 `RUNNING`이며,
인증된 `/health`와 `/monitor/state`는 `200 OK`, MCP 22개 도구 ready를 반환한다.
AI-CODE-TEAM의 `ACT-GLOBAL-01`과 `ACT-WORKER-01` GitHub Runner도 online / idle이다.

하지만 tunnel supervisor에는 boot/logon trigger가 없고 터널 프로세스는 재기동되지
않았다. `runtimes status act-control`에는 재시작 전 PID 3424만 남아 있고, health
URL의 loopback probe (`127.0.0.1:50293`)는 connection refused다. 따라서 Core local
MCP (`127.0.0.1:18790/mcp`)는 정상이나 ChatGPT App의 private tunnel ingress는
현재 사용할 수 없다. 이 상태에서 기존 operation/claim을 재실행·해제하거나 터널을
중복 connect하지 않는다. 다음 작업은 exact tunnel supervisor의 안전한 boot/logon
복구 경로를 구현·검증한 뒤 단일 connect 및 health/MCP E2E로 확인하는 것이다.

Tunnel health metadata 복구는 PR #74로 완료됐다. merge
`3418bfa9b6eee46d488682bc34fad431e883a8a2`와 main CI가 통과했고 동일 SHA가 LIVE Core에
배포됐다. supervisor는 exact tunnel process가 살아 있을 때 중복 connect하지 않으며, 누락된
health URL 파일은 exact PID 소유의 유일한 live/ready loopback listener로만 복구한다. 현재 tunnel
PID와 시작시각은 유지됐고 `runtimes status`는 `healthy=true`, `ready=true`, `runtime_state=ready`,
`stale=false`다. 완료 증거는
`docs/exec-plans/completed/BCT_TUNNEL_HEALTH_RECONCILIATION_20261014.md`를 따른다.

Hosted ChatGPT의 단일 `bct_read` E2E는 1.816초였지만, 같은 exact request의 BCT tool handler는
15.517 ms, BCT ASGI 전체는 21.706 ms였다. tunnel poll 수신부터 local MCP 응답은 23.057 ms,
그 뒤 OpenAI control-plane response POST 완료까지 397.753 ms였다. 로컬 poll-to-post 합계는
420.810 ms이며 나머지 약 1.395초는 로컬 tunnel span 밖이어서 현재 설치된 tunnel-client
0.0.14로 더 분할할 수 없다. 공개 최신 v0.0.15에도 `resp_timing`/`trace_context`가 없으므로
미출시 master 기능을 위해 운영 binary를 교체하지 않는다. BCT Core 결함은 재현되지 않았고
추가 코드·LIVE 변경 대신 기존 bounded batch read를 같은 안전 경계의 read 왕복 절감 수단으로
유지한다. 상세 근거는 `docs/exec-plans/completed/BCT_MCP_TUNNEL_LATENCY_20261014.md`다.

후속 최신 확인: 공식 tunnel-client v0.0.16 release는 `resp_timing`과 opt-in trace context를
제공한다(공식 게시일 2026-10-06). 앞선 최신 릴리스 확인은 불완전했고 v0.0.15가 최신이라는
판단을 정정한다. 설치 버전 업그레이드 및 hosted 구간 재계측은 GitHub #82에서 추적하며,
기능 존재를 지연 해소로 간주하지 않는다.

## Deploy shutdown 및 UNKNOWN reconciliation 완료

터널의 지속 Streamable HTTP 연결이 열린 상태에서 Core shutdown listener는 닫혔지만 Uvicorn
process가 controller의 10초 검증 창 안에 종료되지 않는 운영 결함을 확인했다. 최초 배포
operation은 `DEPLOYMENT_ROLLBACK_UNVERIFIED` UNKNOWN으로 보존했고 재실행하거나 DB에서 claim을
직접 지우지 않았다.

PR #76은 Uvicorn graceful shutdown을 5초로 제한하고, 정확한 원본 UNKNOWN operation과 동일한
rollback receipt 파일·immutable release manifest·current pointer·running service release/manifest를
모두 확인하는 deploy reconciliation을 추가했다. reconciliation은 별도 resource에서 실행되고
검증 성공 시 store transaction 안에서만 원본 claim을 해제한다. Windows short/long path 차이는
문자열이 아니라 파일 identity로 비교한다.

PR #76의 request-drain timeout만으로는 FastMCP lifespan shutdown이 제한되지 않는다는 후속
LIVE 증거가 나왔다. 두 번째 배포도 UNKNOWN으로 보존했고 exact LIVE 복구 후 별도 reconciliation로
claim만 원자적으로 해제했다. PR #79는 authenticated shutdown에서 `should_exit`와 `force_exit`를
함께 설정해 5초 request drain 뒤 무기한 lifespan 대기를 건너뛴다.

로컬 focused 11개와 전체 116개 테스트, PR #79 Windows CI run `38494897550`, merge
`84a65e9dd0c85f0441e024f002f717ddccbcb0cb`, main CI run `38495142459`가 통과했다. 해당 release를
bootstrap한 뒤 persistent tunnel이 실제 `ready`인 상태에서 Core restart가 APPLIED였고 같은 tunnel
process가 다시 `healthy/ready`, runtime `ready`, non-stale 상태가 됐다. 후속 local MCP read도 예상
SHA로 통과했다. 상세 증거는
`docs/exec-plans/completed/BCT_DEPLOY_SHUTDOWN_RECONCILIATION_20261014.md`와
`docs/exec-plans/completed/BCT_DEPLOY_FORCE_EXIT_20261014.md`를 따른다.

## Generic desktop UI Automation 완료

BCT는 인증된 MCP에서 일반 Windows UIA 요소 조회와 `set_value`, `invoke`,
`toggle`, `select`, `expand`, `collapse`를 exact HWND 및 Window Lease에 묶어
제공한다. 원문 control name과 입력값은 durable evidence에 남기지 않으며,
텍스트는 OS locale과 무관한 UTF-8/ASCII-envelope 경계로 전달한다.

PR #231은 기본 UIA 경로를, PR #232는 사라진 exact target을 읽기 전용으로
증명한 뒤 기존 activation UNKNOWN은 보존하고 그 Claim만 해제하는
`desktop_window_activate_reconcile`을 추가했다. PR #232 merge
`ea7b9f84207ca1fed4f97a7f39b1e344cb13ea5d`는 PR/main CI를 통과했고 Core
generation 144에 READY/OK로 배포됐다. VTL Agent 2.3.2와의 authenticated LIVE
canary에서 10개 요소 조회와 다섯 semantic action의 실제 앱 postcondition,
Lease 해제, 기존 Chrome 9개 최상위 창 identity 보존을 확인했다. 상세 계약과
완료 증거는 `docs/exec-plans/completed/BCT_DESKTOP_UIA_CONTROL_20261019.md`를
따른다.
