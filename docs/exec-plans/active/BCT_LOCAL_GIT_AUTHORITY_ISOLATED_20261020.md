# BCT Local Main Authority cutover

Status: CANDIDATE_TESTED / CUTOVER_IN_PROGRESS

## 결정된 운영 모델

- 공식 소스 정본은 `D:\BCT\source`의 로컬 Git `main`이다.
- 기능 작업은 `D:\BCT\worktrees`에서 수행하고 BCT의 `merge_local_main` 계약으로만 통합한다.
- GitHub `p4147691/BCT`는 게시·백업·리뷰·CI 감사용 원격이다. 원격 장애가 검증된 로컬 main과 LIVE 수락을 무효화하지 않는다.
- LIVE는 검증된 로컬 main의 정확한 SHA를 별도 immutable release로 배포한다.
- 이 결정은 이미 운영자가 확정했다. 중간 단계마다 다시 승인받지 않고, 실제 충돌·복구 불가능한 외부 장애에서만 중단한다.

## 재사용한 기존 작업

- Work: `BCT-LOCAL-GIT-AUTHORITY-INTEGRATION-ISOLATED-20261020-01`
- Worktree: `D:\BCT\worktrees\bct-local-main-integration-20261020`
- Branch: `feat/local-authority-integrated-20261020`
- 기존 후보를 최신 GitHub main `09a5db7973c7a02df68aee30c0044b4a389fd1f5` 위로 충돌 없이 리베이스했다.
- 새 Work·Worktree·중복 PR은 만들지 않는다.

## 구현 계약

- `[git_authority] mode="local"`은 정확한 repository와 canonical source root를 고정한다.
- `merge_local_main`은 clean local `main`, exact main SHA, exact feature SHA, 예측 tree, 두 부모를 검증한다.
- 공유 자원 Claim은 실제 merge 실행 구간만 보호하며 과거 결과 기록과 분리한다.
- 선택된 BCT 저장소의 `github_pr_merge`와 `github_sync_main`은 local mode에서 차단한다.
- 게시 전 원격 조회 실패는 효과가 없는 `SYNC_PENDING`, 예상 ref 불일치는 `SYNC_CONFLICT`, 동일 SHA는 `IN_SYNC`로 기록한다.
- 게시 후 상태가 불명확하면 UNKNOWN을 유지하며 자동 재전송·force push하지 않는다.
- GitHub Actions 실패는 감사 실패이며 이미 수락된 로컬/LIVE 효과를 자동 롤백하지 않는다.

## 검증 영수증

- 작업본 import 혼동을 막기 위해 모든 로컬 테스트는 `PYTHONPATH=<worktree>\src`를 명시한다.
- `tests.test_local_git_authority`, `tests.test_github_integration`, `tests.test_deployment_service`, `tests.test_development_flow`: 41 PASS.
- `python -m compileall -q src tests`: PASS.
- `git diff --check`: PASS.
- 실제 main 통합 전에는 bundle/HEAD/source clean 상태와 기존 LIVE pointer를 다시 확인한다.

## 남은 연속 실행

1. 후보를 커밋하고 기존 브랜치에 게시해 PR·CI를 통과시킨다.
2. 기존 로컬 source main을 현재 검증된 원격 main까지 일회성 fast-forward하여 전환 기준선을 맞춘다.
3. 후보 branch를 로컬 저장소에 가져와 `merge_local_main` 계약으로 통합한다.
4. 정확한 로컬 main SHA를 LIVE에 배포하고 Core READY·정책·영수증을 검증한다.
5. 로컬 main을 GitHub에 fast-forward-only로 게시하고 GitHub Actions 감사 결과를 확인한다.
6. 동일 local main에 이미 병합된 BWM 복구 버튼을 Monitor 설치본에 publish하고 same-ID reload한다.
7. 확장/RCC/Core/MCP/BC 버튼 다섯 개를 하나씩 실제 실행해 postcondition과 영수증을 확인한다.

## 보호 규칙

- source가 dirty하거나 exact SHA가 달라지면 변경을 적용하지 않고 원인을 대조한다.
- 기존 UNKNOWN·Claim·RCC 메시지를 성공으로 조작하거나 재전송하지 않는다.
- force push, destructive reset, 무관한 작업 종료, PC 재부팅을 하지 않는다.
- LIVE 배포와 Monitor publish는 각각 기존 공식 backup/rollback 경로를 사용한다.
