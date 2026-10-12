# BCT 운영 모델

## 하나의 공식 소스

BCT와 BCT가 관리하는 사용자 프로젝트의 버전 관리 대상 코드는 GitHub `main`을 유일한
공식 소스로 사용한다. `정본`이라는 단어는 대상이 불명확하므로 운영 문서에서 단독으로
사용하지 않는다.

- **공식 소스**: GitHub `main`의 검증된 commit.
- **로컬 checkout**: 공식 소스를 동기화한 작업 사본.
- **worktree**: 격리된 수정·테스트 사본.
- **배포 release**: 정확한 공식 commit으로 만든 불변 실행 파일 집합.
- **운영 상태**: 실제 PID, fingerprint, health, 현재 release SHA와 operation receipt.
- **운영 자산**: 모델 weight, 브라우저 profile, token, DB와 사용자 데이터. 소스가 아니며
  별도 manifest·접근 제어·backup으로 관리한다.

Runtime은 현재 무엇이 실행 중인지 판단하는 증거지만 소스가 아니다. Runtime에만 존재하는
코드는 정상 변경으로 승격하지 않는다. 공식 소스가 유실된 과거 구성요소를 복구할 때만
exact bytes와 SHA를 회수해 baseline commit으로 만든 뒤, 이후 변경은 다시 GitHub `main`을
통한다.

## 기본 완료 흐름

정상 개발 작업은 다음 흐름을 한 번의 완료 단위로 취급한다.

1. 격리 worktree에서 수정한다.
2. focused test와 관련 회귀 테스트를 통과한다.
3. local commit을 만든다.
4. GitHub PR·CI를 거쳐 `main`에 통합한다.
5. exact main SHA의 release를 배포한다.
6. 필요한 구성요소만 최소 재시작한다.
7. source SHA, loaded release, health와 실제 기능을 확인한다.

7단계까지 끝나지 않은 작업은 `SOURCE_COMPLETE`가 아니라 `INTEGRATION_PENDING` 또는
`LIVE_ACCEPTANCE_PENDING`이다. 사용자가 소스·로컬·Runtime 중 무엇을 기준으로 삼을지
매번 선택하지 않는다.

GitHub 또는 네트워크가 일시적으로 사용할 수 없어도 로컬 수정·테스트·commit은 계속할 수
있다. 단, 공식 통합과 운영 배포가 끝나기 전에는 완료로 표시하지 않는다.

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

## Drift 처리

공식 소스, local checkout과 Runtime이 다르면 한쪽을 조용히 덮어쓰지 않는다.

1. 세 위치의 exact SHA와 현재 process identity를 기록한다.
2. Runtime-only 변경은 별도 recovery branch로 회수하고 직접 main으로 승격하지 않는다.
3. 테스트와 PR을 거쳐 공식 소스를 결정한다.
4. exact release로 재배포하고 drift가 사라졌음을 확인한다.

이 절차는 예외 복구이며 일상적인 개발 경로가 아니다.
