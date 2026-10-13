# BCT

BCT는 사용자 지시에 따라 개발·로컬 실행·브라우저·데스크톱·모델 운영을 끝까지 수행하기
위한 독립 제어 패키지다. 기존 ACT의 검증된 기능은 기능별 acceptance가 끝날 때까지 운영을
유지하면서 BCT 소스와 공통 operation receipt로 이전한다.

## 현재 상태

`BCT_PLATFORM_PACKAGE_V1=LIVE_ACCEPTED`.

BCT는 현재 파일 읽기·쓰기, 테스트, Git/GitHub, exact 배포·서비스 제어, MCP, RCC,
로컬 Python·PowerShell·argv 실행과 지속 세션, Laya 결정 모델, BCT Monitor를 자체 소스와
공통 operation receipt로 제공한다. 새 파일을 포함한 구조화 Git commit과 deployment profile의
안전한 파일 목록 진화도 실제 수용 검증을 마쳤다.

공식 소스는 GitHub `p4147691/BCT`의 `main` 하나다. `D:\BCT\source`는 그 main을
동기화한 로컬 checkout이고, `D:\BCT\runtime`은 검증된 commit으로 만든 실행본이다.
BCT core/MCP/Monitor는 `127.0.0.1:18790`에서 함께 실행되며
Monitor UI는 `http://127.0.0.1:18790/monitor`이다. BCT runtime은 ACT Python 모듈을 import하지
않는다. ACT는 기존 작업과 아직 제거하지 않은 호환 구성요소의 rollback 경로로만 보존한다.

## 구조

`사용자/인증된 MCP → core → BCT 안의 feature 구현 → 실행 결과`

- core: 작업·공통 권한 판단·변경 충돌·operation 결과.
- features: 파일·Git·테스트·실행·프로세스 진단·배포·서비스·RCC·Monitor·로컬 결정 모델의
  실제 구현과 연결 계약.
- integrations: MCP와 필요한 기간만 쓰는 ACT 호환 연결.
- 한 설정 진입점, 하나의 운영 상태 저장소. 별도 정책 서버는 만들지 않는다.

노드 ID는 안정적으로 유지하고 이름·역할·그룹·연결은 독립적으로 변경한다.
조직 역할과 기술 실행 권한은 별개다. 기존 MCP/Chrome 설치·연결 보존을 기능별 이전 검증에 포함한다.

## 시작점

1. [설계 기준](docs/DESIGN.md)
2. [설계 검토와 테스트 시나리오](docs/CORE_DESIGN_REVIEW.md)
3. [첫 구현 완료 기록](docs/exec-plans/completed/BCT_FOUNDATION.md)
4. [GitHub 통합 계약](docs/GITHUB_INTEGRATION.md)
5. [GitHub 통합 완료 기록](docs/exec-plans/completed/BCT_GITHUB_INTEGRATION.md)
6. [배포·서비스 계약](docs/DEPLOYMENT_SERVICE.md)
7. [배포·서비스 구현 기록](docs/exec-plans/completed/BCT_DEPLOYMENT_SERVICE.md)
8. [MCP 통합 계약](docs/MCP_INTEGRATION.md)
9. [MCP 구현 기록](docs/exec-plans/completed/BCT_MCP_V1.md)
10. [RCC 통합 계약](docs/RCC_INTEGRATION.md)
11. [RCC V1 완료 기록](docs/exec-plans/completed/BCT_RCC_V1.md)
12. [인수인계](PROJECT_HANDOFF.md)
13. [BCT 전체 패키지 완료 기록](docs/exec-plans/completed/BCT_PLATFORM_PACKAGE_V1.md)
14. [기능 소유권 지도](docs/CAPABILITY_OWNERSHIP.md)
15. [사용 안내](docs/USER_GUIDE.md)
16. [공식 소스·배포·운영 상태 모델](docs/OPERATING_MODEL.md)
17. [로컬 폴더 구조](docs/LOCAL_LAYOUT.md)

## 실행 기능

`bct_execute`는 shell 문자열로 몰래 우회하지 않고 실행 종류를 명시한다.

- `kind=argv`: 프로그램과 인자 배열을 직접 실행한다.
- `kind=python`: BCT가 사용하는 Python으로 프로젝트 module 또는 script를 실행한다.
- `kind=powershell`: PowerShell command 또는 프로젝트 안의 `.ps1`을 실행한다.

모든 실행은 work root, operation ID, PID/fingerprint, timeout, 종료 코드와 제한된 출력을
receipt에 연결한다. 동일 operation ID는 두 번 실행되지 않는다. Python/PowerShell 기능은
제공한다. `bct_process_session`은 같은 실행 계약으로 장시간 Python·PowerShell·argv 프로세스를
시작하고, 상태·증분 출력·표준 입력·정확한 종료를 제공한다. BCT가 직접 시작하며 기록한
PID/fingerprint만 제어하고 외부 프로세스를 세션으로 승격하지 않는다. 동일 session ID와
operation ID는 두 번째 프로세스나 입력을 만들지 않는다.

## 플랫폼 구성요소

- BCT 제품은 작은 `Core`와 독립적인 `modules/`로 구성된다.
- RCC 소스와 제어 계약은 `modules/rcc/`에 있다. RCC는 사용자 기능 이름이고 Relay는 내부 전송 계층 이름이다.
- DesktopWindow Monitor의 활성 baseline은 `modules/monitor/`에 있다.
- BDC(BCT Desktop Control)는 `modules/bdc/`가 소유하며, Core 밖의 데스크톱 자동화 기능이다.
- 읽기 전용 운영 화면은 `modules/status-ui/`에 있다.
- Laya 모델 파일은 Git 밖의 `D:\BCT\models`에, 전용 실행 dependency는
  `D:\BCT\local-llm`에 둔다.
- BCT는 모델 endpoint health, advisory inference, PID/fingerprint service receipt와
  deterministic fallback을 소유한다. 모델 추천은 인증·권한·중복 방지 결정을 대체하지 않는다.

GitHub main은 BCT의 유일한 공식 소스다. 인증정보, Chrome 프로필, 사용자 설정과 runtime DB/log는 커밋하지 않는다.

로컬 패키지 배치는 한곳으로 모은다.

- GitHub main을 따라가는 로컬 checkout: `D:\BCT\source`
- immutable 운영 release와 service receipt: `D:\BCT\runtime`
- operation/model/session 상태: `D:\BCT\data`
- Git 밖 대형 모델: `D:\BCT\models`
- 격리 개발 worktree: `D:\BCT\worktrees`

초기 `D:\PROJECTS\BCT` bootstrap checkout과 연결 worktree는
`D:\Archive\BCT-Bootstrap-20261013`에 검증 가능한 ZIP·Git bundle과 함께 보존한다.
새 변경은 `D:\BCT\worktrees`에서 만들고 PR/CI로 GitHub main에 통합한다. 통합 후
`D:\BCT\source`를 exact main SHA로 동기화하고 그 commit만 LIVE에 배포한다.

## 로컬 검증

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
```
