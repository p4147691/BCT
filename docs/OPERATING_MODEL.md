# BCT 운영 모델

## 하나의 공식 소스

BCT 자체의 버전 관리 대상 코드는 `D:\BCT\source`의 로컬 Git `main`을 공식 소스로
사용한다. GitHub `p4147691/BCT`는 게시·백업·리뷰·CI 감사 원격이다. BCT가 관리하는 다른
사용자 프로젝트에는 그 프로젝트가 명시한 authority 계약을 적용한다. `정본`이라는 단어는
대상이 불명확하므로 운영 문서에서 단독으로 사용하지 않는다.

- **BCT 공식 소스**: `D:\BCT\source` 로컬 Git `main`의 검증된 commit.
- **GitHub 원격**: 정확한 로컬 main commit을 fast-forward로 게시하는 백업·리뷰·CI 감사 사본.
- **worktree**: 격리된 수정·테스트 사본.
- **배포 release**: 정확한 공식 commit으로 만든 불변 실행 파일 집합.
- **운영 상태**: 실제 PID, fingerprint, health, 현재 release SHA와 operation receipt.
- **운영 자산**: 모델 weight, 브라우저 profile, token, DB와 사용자 데이터. 소스가 아니며
  별도 manifest·접근 제어·backup으로 관리한다.

Runtime은 현재 무엇이 실행 중인지 판단하는 증거지만 소스가 아니다. Runtime에만 존재하는
코드는 정상 변경으로 승격하지 않는다. 공식 소스가 유실된 과거 구성요소를 복구할 때만
exact bytes와 SHA를 회수해 baseline commit으로 만든 뒤, 이후 변경은 다시 로컬 Git `main`
계약을 통한다.

## 기본 완료 흐름

정상 개발 작업은 다음 흐름을 한 번의 완료 단위로 취급한다.

1. 격리 worktree에서 수정한다.
2. focused test와 관련 회귀 테스트를 통과한다.
3. local commit을 만든다.
4. 로컬 main 계약으로 통합한 뒤 exact commit을 GitHub에 fast-forward 게시하고 CI를 수행한다.
5. exact main SHA의 release를 배포한다.
6. 필요한 구성요소만 최소 재시작한다.
7. source SHA, loaded release, health와 실제 기능을 확인한다.

7단계까지 끝나지 않은 작업은 `SOURCE_COMPLETE`가 아니라 `INTEGRATION_PENDING` 또는
`LIVE_ACCEPTANCE_PENDING`이다. 사용자가 소스·로컬·Runtime 중 무엇을 기준으로 삼을지
매번 선택하지 않는다.

GitHub 또는 네트워크가 일시적으로 사용할 수 없어도 로컬 수정·테스트·main 통합과, 이미
검증된 로컬 commit의 복구 가능한 표시 전용 LIVE 수락은 계속할 수 있다. 이 경우 게시 상태를
`SYNC_PENDING`으로 기록한다. Core/RCC/Native Host·프로토콜·DB/Claim·메시지 효과는 exact-head
CI 성공 뒤 배포한다.

## 자유로운 작업과 단계별 안전

인증된 사용자가 지정한 로컬 root에서는 프로젝트 사전 등록 여부와 관계없이 read, write,
test, Git, Python, PowerShell과 argv 실행을 정상 capability로 취급한다. Node name, role,
group과 connection은 독립적으로 변경할 수 있으며 표시 역할이 기술 권한을 암묵적으로
늘리거나 줄이지 않는다.

다음 조건만 fail-closed 대상으로 둔다.

- 다른 활성 작업과 실제 자원 충돌이 확인됨;
- 같은 side effect가 두 번 실행될 수 있음;
- 기존 mutation의 결과가 증거 부족으로 `UNKNOWN`임;
- 요청한 root 밖으로 나가는 canonical path 또는 reparse-point 우회;
- stale HEAD, expected hash 또는 배포 precondition;
- rollback이 불가능하거나 범위가 불명확한 파괴 작업;
- credential·인증·외부 계정처럼 별도 확인이 필요한 변경.

위험한 작업은 기능 자체를 영구 봉쇄하지 않는다. exact target, 예상 영향, backup/rollback과
operation ID를 제시한 단계별 승인을 사용한다. 승인 여부와 무관하게 precondition,
duplicate guard, effect evidence는 유지한다.

### 개인 PC 내부 신뢰 경계와 외부 ChatGPT 진입

현재 본류는 PC/스마트폰 ChatGPT → 기존 private App·MCP 터널 → BCT Core → 기존 RCC → PC 브라우저다.
인증은 디바이스 IP나 브라우저 UI가 아니라 기존 BCT MCP 토큰 및 Work/Principal/Policy 경계로 처리한다.
외부 웹페이지의 지시문은 권한이 아닌 데이터로 취급한다. 현재 개인 PC 구성에서 이미 동일 Windows
사용자·로그온 세션으로 악성 코드를 실행하는 공격자는 필수 Core↔RCC 상호 인증 범위에서 제외하며,
이 선택은 잔여 위험 수용이지 보호가 완성됐다는 증명이 아니다. 스마트폰 채팅과 BCT 읽기 경로는
접속 기기의 IP·User-Agent 때문에 차단하지 않는다.

**실행 안전성 주의:** 정상 `execute`·`process_session` 권한은 임의 Python·PowerShell·argv를
실행할 수 있다. 현재 Work cwd 검사나 별도 `delete` 승인 정책만으로 하위 프로세스의 삭제·설정
변경을 운영체제 수준에서 차단하지는 못한다. 파괴 작업은 범위와 승인·복구 증빙을 별도로 확인해야 하며,
임의 명령을 자동으로 안전하다고 분류하지 않는다. 별도 위험 실행 게이트의 구현·수락 전에는 완전한
명령 차단을 주장하지 않는다. 상세 경계: `docs/BCT_MAINLINE_TRUST_BOUNDARY.md`.

## Drift 처리

공식 소스, local checkout과 Runtime이 다르면 한쪽을 조용히 덮어쓰지 않는다.

1. 세 위치의 exact SHA와 현재 process identity를 기록한다.
2. Runtime-only 변경은 별도 recovery branch로 회수하고 직접 main으로 승격하지 않는다.
3. 테스트와 로컬 main 통합 계약을 거쳐 공식 소스를 결정한다.
4. exact release로 재배포하고 drift가 사라졌음을 확인한다.

이 절차는 예외 복구이며 일상적인 개발 경로가 아니다.
