# BCT 사용 안내

## 평소 사용법

별도 명령 문법을 외울 필요는 없다. Codex에 원하는 결과를 평소 말로 요청하면 된다.
Codex는 BCT work와 operation을 만들고 읽기, 수정, 실행, 테스트, commit, GitHub 통합,
배포와 검증을 필요한 범위에서 이어서 수행한다.

상태 화면은 `http://127.0.0.1:18790/monitor`에서 볼 수 있다. 서비스 확인 주소는
`http://127.0.0.1:18790/health`, MCP 주소는 `http://127.0.0.1:18790/mcp`이다.

## 자동으로 가능한 일

- 프로젝트 조사와 파일 읽기
- 시스템과 프로세스 상태 확인
- Python, PowerShell, 일반 프로그램 실행
- 장시간 Python/PowerShell/프로그램 세션 시작과 상태 확인
- Monitor 상태 확인
- 현재 로그인 사용자 세션 상태와 모니터 구성을 확인
- 현재 가상 화면, 한 모니터 또는 정확한 HWND를 읽기 전용으로 캡처
- 활성 Session Lease 아래에서 정확한 EXE를 실행하고 새 PID/창에 Lease를 바인딩
- 기존 operation 결과와 GitHub PR 상태 조회

폴더 내용은 파일 읽기와 구분해 `bct_read`의 `operation: "directory_tree"`로 조회한다.
경로는 현재 work의 허용 root 안에 있어야 하며, 기본 깊이는 2, 기본 최대 항목 수는 200이다.
결과는 파일(`file`)·하위 폴더(`directory`)·따라가지 않는 링크/재분석 지점(`symlink`)을 구분한다.

같은 조사 단계에서 여러 파일이나 폴더가 필요하면 `operation: "batch"`와 `items`를 사용해
한 번에 조회한다. 각 항목에는 고유한 `id`와 절대 경로를 넣고, 폴더 항목만
`operation: "directory_tree"`, `depth`, `limit`을 추가한다. 한 batch는 최대 20개 항목이며
파일당 512 KiB, 파일 내용 합계 1 MiB, 폴더 요청 한도 합계 2,000개로 제한된다. 결과는 입력
순서를 유지하고 항목별 SHA·관측 시각·성공 또는 오류를 반환한다. receipt에는 파일 본문이
저장되지 않으므로 동일 operation을 다시 조회해도 과거 본문은 복원되지 않는다.

일반 작업에서도 안전 조건과 승인 경계가 같은 읽기·비교·상태 확인은 가능한 한 묶어서 처리한다.
이미 받은 상태나 receipt를 불필요하게 다시 조회하지 않는다. 쓰기, 승인, 병합, 배포,
UNKNOWN 처리와 정확한 SHA 확인은 각각의 안전 경계를 유지한다.

이 실행들도 BCT receipt, 정확한 작업 루트, PID/fingerprint, timeout과 중복 방지 기록을 남긴다.

## 빠른 개발 검증: VTL 우선, GitHub 최종 확인

일반 개발의 반복 확인은 매 후보마다 GitHub Actions를 시작하지 않는다. 먼저 현재 작업의 변경
범위를 판정하고, 같은 소스에서 실행 가능한 가장 싼 검증부터 사용한다.

1. 문법·정적 검사와 영향받은 unit test는 BCT의 `test`/`execute`로 로컬에서 실행한다.
2. 브라우저·GUI·Windows 통합 동작이 필요하면 깨끗하고 정확한 VTL source/runtime와 프로젝트 소유
   scenario를 사용해 VTL Fast mode로 실행하고 PASS/FAIL evidence를 작업 밖의 run 디렉터리에 남긴다.
3. 실패 후보를 GitHub에 올려 원격 CI로 디버깅하지 않는다. 로컬/VTL에서 수정과 재검증을 반복한다.
4. 로컬/VTL이 통과한 하나의 후보만 push하고, branch protection의 required check와 독립 환경 증명이
   필요한 마지막 단계에서 GitHub CI를 한 번 실행한다.
5. release/진단이나 Fast mode로 증명할 수 없는 경계에서만 VTL Full mode·전체 회귀·VM E2E를 선택한다.

VTL의 self-hosted runner를 GitHub Actions workflow로 호출하는 방식은 hosted runner를 피할 수 있지만
여전히 Actions 실행·큐·API를 사용한다. 따라서 VTL exact-SHA Actions smoke는 최종 교차 환경 증거이지
일상적인 편집 반복 경로가 아니다. GitHub required check를 VTL 결과로 통과한 것처럼 표시하거나 생략하지
않는다. required check 자체를 줄이려면 변경 범위 기반 CI와 저장소 보호 규칙을 별도로 검토한다.

전용 `bct_vtl_validate`는 GitHub Actions를 dispatch하지 않고 `D:\TOOLS\VTL\current.json`이
가리키는 immutable VTL release를 직접 실행한다. 모든 manifest 파일 해시와 VTL source SHA를
효과 직전에 다시 확인하고, 프로젝트 work root 안의 scenario/profile만 허용한다. `browser`
operation은 `mode: Fast|Full`과 browser-playwright scenario를, `profile` operation은
`virtual-test.json`과 일반 VTL scenario를 받는다. profile의 `source_path`도 같은 work scope 안에
있어야 한다.

실행은 background operation이므로 최초 응답이 `RUNNING`이면 같은 work/operation ID로
`bct_operation_get(wait_seconds=25)`를 호출해 완료 receipt를 받는다. 테스트 assertion 실패는
실행 자체가 성공한 `APPLIED` receipt의 `evidence.status: FAIL`로, 도구/manifest/result 계약 문제는
`FAILED / INFRA_ERROR`로 구분된다. `PASS`, `FAIL`, `TIMEOUT` 모두 VTL SHA, scenario/profile SHA,
return code, 실행 시간, 외부 evidence/result 경로를 남긴다. evidence는
`D:\BCT\data\vtl-evidence` 아래 operation별 디렉터리에 기록되고 immutable release에는 쓰지 않는다.

브라우저 반복 검증 예시는 다음 arguments를 사용한다.

```json
{
  "operation": "browser",
  "scenario_path": "D:\\PROJECTS\\SomeProject\\virtual-tests\\smoke.json",
  "mode": "Fast",
  "timeout_s": 300
}
```

이 경로가 직접 VTL 검증이다. VTL self-hosted runner를 사용하는 GitHub workflow는 여전히 Actions
경로이므로 최종 교차 환경 증거가 필요할 때만 별도로 실행한다.

데스크톱 조회는 먼저 `desktop_session_status` action의 work를 만들고
`bct_desktop_session_status`를 호출한다. 화면 캡처는 같은 work에 `desktop_capture`를
포함하고 `bct_desktop_capture`에서 `target_type`을 `virtual_screen`, `monitor`, `window`
중 하나로 선택한다. MCP 캡처 응답에는 해시가 검증된 PNG 이미지 블록이 포함된다.

로그인 세션의 앱과 파일 진입점을 조사할 때는 같은 work에 `desktop_explore`를
포함하고 `bct_desktop_explore`를 호출한다. `operation: "processes"`는 Agent와
같은 Session의 프로세스만 반환하며 PID, 프로세스 생성 시점, 접근 가능한 실행 파일
경로 및 현재 가상 데스크톱의 창 목록을 연결한다. `operation: "paths"`는 실제 로그인
사용자의 알려진 폴더와 준비된 드라이브를 반환한다. 둘 다 읽기 전용이라 Lease가
필요 없다. 발견된 폴더 내용을 볼 때는 그 경로를 work root에 명시하고 기존
`bct_read`의 bounded `directory_tree`를 사용한다. `desktop_explore` 자체는 폴더를
순회하거나 파일 내용을 읽지 않는다.

Chrome 또는 Explorer 창을 좌표나 PID 추측 없이 고를 때는
`desktop_application_target`을 사용한다. `operation: "list"`는 정확한 process
family와 top-level window class를 기준으로 현재 데스크톱의 후보를 읽기 전용으로
반환한다. `operation: "bind"`는 선택 조건에 맞는 후보가 정확히 하나일 때만 그
HWND의 Window Lease를 발급한다. 0개, 여러 개 또는 Agent 목록이 잘린 경우에는
어떤 창도 제어하지 않는다. 반환된 Lease는 기존 `desktop_window_activate`,
`desktop_input`, `desktop_window_manage`에 사용하고 완료 즉시 release한다.
Explorer는 선택적으로 기존 로컬 폴더의 절대 경로를 `folder_path`에 지정할 수 있다.
Agent가 Shell 위치를 실제 HWND와 연결하므로 같은 제목의 Explorer 창이 여럿이어도
정확한 폴더 창만 선택한다. 상대 경로와 존재하지 않는 폴더는 거부하며, 가상 Shell
위치는 로컬 폴더로 추측하지 않는다. Chrome에는 `folder_path`를 사용할 수 없다.
Chrome은 선택적으로 `profile_query`, `tab_title_query`, `tab_scope`(`active` 기본값
또는 `any`)를 사용할 수 있다. Agent는 기존 Chrome 창의 프로필 라벨과 제한된 탭
제목/선택 상태만 UI Automation으로 읽으며 URL은 반환하지 않는다. 이 조회는 Chrome을
실행·종료·활성화하거나 입력하지 않는다. UI Automation이 불완전하거나 응답이 잘리면
`bind`는 실패하여 다른 창을 추측하지 않는다. Explorer에는 이 Chrome 선택자를 사용할
수 없다.

이 첫 구현은 현재 로그인되어 있고 잠기지 않은 사용자 세션에서 수동 실행한 VTL Desktop
Session Agent를 필요로 한다. Agent가 없거나 다른 세션이거나 Pipe 소유자/DACL이 일치하지
않으면 요청은 화면을 추측하지 않고 실패한다.

후속 제어 기능을 위한 조정 경계는 `desktop_control_lease`와
`desktop_emergency_stop` action으로 제공한다. Lease는 현재 Session 또는 정확한 HWND/PID/프로세스
생성 시점에 묶이고, 한 세션에 하나만 존재하며 2~120초 안에서 자동 만료된다. 획득한 work만 정확한
lease ID로 갱신·반납할 수 있다. 긴급정지는 일반 Lease claim과 독립적으로 호출되어 현재 Lease를
즉시 폐기하고 래치되며, 반환된 stop generation과 정확히 일치하는 명시적 reset 전에는 새 Lease를
거부한다.

정확한 HWND를 대상으로 `window` Lease를 획득한 뒤 같은 work와 lease ID로 `desktop_input`을
호출하면 마우스 이동·좌/우/가운데 클릭, 제한된 키 입력, UTF-16 Unicode 텍스트 입력을 실행할 수
있다. 마우스 좌표는 Lease 창 또는 그 자식 컨트롤 위여야 한다. 키와 텍스트는 Lease 창이 이미
foreground일 때만 허용되므로, 필요하면 그 창 내부의 정확한 좌표를 먼저 클릭한다. 각 효과 직전에
Lease owner/ID, HWND/PID/프로세스 생성 시점, 입력 데스크톱과 긴급정지를 다시 확인한다. 부분 입력처럼
실행 여부가 불명확한 결과는 `UNKNOWN`으로 남기고 자동 재시도하지 않는다. 텍스트 인자는 감사용
operation 기록에 남으므로 비밀번호·토큰 같은 민감정보 입력에는 사용하지 않는다.

현재 가상 데스크톱의 창을 고를 때는 읽기 전용 `desktop_window_list`를 호출한다. 반환값은 보이는
제목 있는 최상위 창만 포함하며 HWND, PID, 프로세스 생성 시점, Session ID, 가상 데스크톱 ID,
제목, 클래스, 위치와 foreground/minimized 상태를 함께 준다. 선택한 HWND로 `window` Lease를 획득한
뒤 같은 work와 lease ID로 `desktop_window_activate`를 호출하면 숨겨지거나 최소화되지 않은 그 창만
foreground로 활성화한다. 활성화 직전에 Lease와 전체 창 fingerprint 및 긴급정지를 다시 확인하며,
Windows API 결과와 실제 foreground가 모순되면 `UNKNOWN`으로 남기고 자동 재시도하지 않는다.

같은 `window` Lease로 `desktop_window_manage`를 호출하면 그 정확한 창만 `restore`, `minimize`,
`maximize`, `move_resize`할 수 있다. 이동·크기 변경은 복원된 창과 현재 가상 화면 안의 bounded
사각형만 허용한다. Agent는 효과 뒤 최소화/최대화 상태 또는 정확한 위치·크기를 다시 확인하며,
시도했지만 결과를 입증하지 못하면 `UNKNOWN`으로 남겨 자동 재시도를 막는다. 창 닫기와 가상
데스크톱 이동은 이 기능에 포함하지 않는다.

프로그램을 새로 열 때는 먼저 `session` Lease를 획득하고 같은 work와 lease ID로
`desktop_program_launch`를 호출한다. 실행 파일은 존재하는 절대 `.exe` 경로여야 하며,
인수는 셸 문자열이 아닌 문자열 배열로 전달한다. Agent는 `UseShellExecute=false`로 정확한
파일만 실행하고 새 PID, 프로세스 생성 시점과 Session ID를 기록한다. 그 PID가 제한 시간 안에
현재 가상 데스크톱에 보이는 최상위 창을 만든 경우 같은 Lease가 해당 창 fingerprint로 원자적으로
바뀌므로 곧바로 활성화와 입력에 사용할 수 있다. 이미 실행 중인 프로세스로 요청을 넘기는 Chrome
같은 앱은 새 PID 소유 창을 입증할 수 없어 실행은 `APPLIED`이지만 `WINDOW_NOT_OBSERVED`로 남을 수
있다. 이 경우 자동 재실행하지 않는다. 실행 인수는 operation 기록에 남으므로 비밀번호·토큰을
전달하지 않는다.

아직 자동 로그인과 창 닫기 기능은 제공하지 않는다.

## 일반 ChatGPT와 Codex가 데스크톱을 함께 사용할 때

일반 ChatGPT 대화도 해당 대화에 **BCT Control 연결이 실제로 활성화되어 있고**
`bct_capabilities`에 데스크톱 도구가 보이면 같은 VTL Desktop Session Agent를 사용할 수 있다.
VTL 저장소나 GitHub Actions가 모든 대화에 직접 노출되는 것은 아니다. 대화 중 실제 화면을
조회·제어하는 진입점은 BCT Control MCP이고, GitHub Actions의 VTL workflow는 exact-SHA 검증을
남기는 별도 진입점이다.

이 데스크톱 세션 경로는 화면 조작 기능이며, 위의 VTL 우선 개발 검증 방침을 대신하지 않는다.
GUI 검증은 가능하면 격리된 VTL browser/VM scenario로 실행하고, 실제 로그인 데스크톱 제어는
실사용 확인이나 격리 환경으로 증명할 수 없는 경계에만 사용한다.

읽기 전용 `desktop_session_status`, `desktop_capture`, `desktop_window_list`,
`desktop_explore`는 여러 대화가
동시에 호출해도 상태를 바꾸지 않는다. 다만 캡처 중 사용자나 다른 대화가 화면을 바꾸면 서로 다른
시점의 화면을 볼 수 있으므로, 캡처 결과를 제어 성공의 원자적 증거로 간주하지 않는다.

입력·창 활성화·프로그램 실행은 다음 공용 규칙을 지킨다.

1. 대화마다 충돌하지 않는 새 work ID를 만들고, 먼저 `desktop_control_lease`의 `status`를 조회한다.
2. 실제 효과 직전에 필요한 정확한 Session 또는 HWND fingerprint로 짧은 Lease를 획득한다.
3. 한 로그인 세션에는 활성 Lease가 하나뿐이다. 다른 owner의 Lease가 있으면 기다리거나 사용자에게
   점유 상태를 알리고, 빼앗기·강제 reset·새 work ID를 이용한 우회를 하지 않는다.
4. 작업이 끝나면 같은 work와 정확한 lease ID로 즉시 반납한다. 만료만으로 다른 실행이 끝났다고
   추정하지 않는다.
5. `UNKNOWN` 효과는 자동 재시도하지 않는다. 화면과 operation receipt를 읽어 실제 결과를 먼저
   화해한다.
6. 긴급정지는 세션 전체에 적용되어 다른 대화의 Lease도 폐기한다. 실제 중지 요청이나 안전 문제가
   있을 때만 사용하며, 제어권 획득 수단으로 사용하지 않는다.
7. 실행 인수와 입력 텍스트는 감사 기록에 남으므로 비밀번호·토큰을 넣지 않는다.

사람이 같은 데스크톱을 직접 사용하는 동안에도 기술적으로 제어할 수 있지만 포커스와 입력이 서로
간섭할 수 있다. 이 경우 짧은 Lease, 정확한 창 fingerprint, 효과 직전 상태 재확인으로 충돌 범위를
최소화하고, 사람이 조작 중임을 알면 입력 전에 협의한다.

## 여러 노드로 이어서 작업하기

Durable orchestration은 한 BCT work 안에서 하나의 목표와 완료 조건을 저장하고, 열려 있는
RCC 대화를 매니저·작업 노드로 연결한다. 매니저는 두 개 이상의 제한된 작업을 배정하고 결과를
수집한 뒤 다른 노드에 종합을 요청할 수 있다. 브라우저 탭의 표시 이름이나 역할은 권한이 아니며,
assignment 범위는 원래 work보다 좁게 검증되며 V1 노드 작업은 읽기 기반 증거 생성만 허용한다.
노드 응답은 권한이나 실행 영수증이 아니라 신뢰되지 않은 분석 증거다. 쓰기·테스트·배포 같은 실제
효과는 매니저가 별도 BCT operation으로 수행하고 기존 정책과 승인을 그대로 통과해야 한다.

매니저 창이 바뀌면 manager epoch를 증가시켜 이전 매니저의 새 배정을 차단한다. 워커가 전송 전에
사라진 경우에는 미전송 영수증이 있을 때만 다른 워커로 교체한다. 전송 여부가 불명확한 UNKNOWN은
자동 재실행하지 않고 해당 작업만 격리한다. 모든 결과는 mailbox와 assignment generation에 남아
Core 재시작 후에도 status에서 같은 증거를 다시 읽을 수 있다.
단일 작업의 전송 후 결과 회수는 `reconcile`, 체인 전체 복구는 `chain-resume`을 사용한다.
전송 예약조차 없었음을 SQLite로 입증할 수 있을 때만 `recover-not-dispatched`가 기존 잠금을
종결한다. 체인의 일부만 화해해 전체 잠금을 푸는 동작과 미해결 결과를 제외한 조기 종합은 거부한다.

## 주의 메시지가 필요한 일

파일 변경, 프로젝트 코드 테스트, Git commit, GitHub push/merge, LIVE 배포, 서비스 재시작,
Chrome/RCC mutation처럼 지속되는 부작용이 있는 단계에서는 Codex가 대상과 영향을 보여줄 수
있다. 이 경고는 도구가 없어서 멈추는 것이 아니라 실제 변경 직전의 안전 경계다.

## 위치

- 공식 소스: GitHub `p4147691/BCT`의 `main`
- 로컬 main checkout: `D:\BCT\source`
- 운영 release: `D:\BCT\runtime`
- 상태와 receipt: `D:\BCT\data`
- 모델: `D:\BCT\models`
- 로컬 LLM dependency: `D:\BCT\local-llm`
- 격리 worktree: `D:\BCT\worktrees`

초기 `D:\PROJECTS\BCT` bootstrap 복구본과 연결 worktree는
`D:\Archive\BCT-Bootstrap-20261013`에 보존되어 있다. 새 격리 작업은
`D:\BCT\worktrees` 아래에 만들고, GitHub main 통합 후 `D:\BCT\source`를 동기화한다.

## 문제가 생겼을 때

먼저 Monitor와 health를 확인한다. 같은 operation ID를 임의로 다시 실행하지 말고 기존 receipt를
조회한다. BCT의 배포와 서비스 작업은 exact SHA, backup, health, rollback 증거를 사용한다.
ACT를 먼저 종료하거나 Chrome profile/binding을 초기화할 필요는 없다.
