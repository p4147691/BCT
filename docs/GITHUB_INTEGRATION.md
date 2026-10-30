# GitHub integration V1

## Purpose

BCT의 로컬 개발 결과를 GitHub 공식 소스에 안전하게 통합한다. 별도 workflow engine이나
credential store를 만들지 않고 기존 BCT operation/ownership/receipt와 공식 `git`/`gh` 실행기를 사용한다.

## Capabilities

| Capability | Effect | Required fence |
| --- | --- | --- |
| `github_push` | 현재 branch의 exact commit을 같은 이름의 원격 branch로 push | clean tree, exact local HEAD, exact current remote SHA/absence, matching repository remote, fast-forward only |
| `github_pr_create` | exact head/base PR을 한 번 생성 | exact remote head SHA, deterministic BCT request marker, conflicting open head rejection |
| `github_pr_status` | PR과 required checks 조회 | exact PR head SHA and named required checks |
| `github_pr_merge` | required checks가 성공한 exact head PR merge | exact PR/head, open state, every named check successful, post-merge SHA verification |
| `github_sync_main` | clean local `main`을 verified remote SHA로 fast-forward | exact local HEAD, exact remote main SHA, clean tree, `main`, ff-only |

## Idempotency and uncertain responses

- 공통 BCT operation ID는 같은 요청의 executor 재진입을 막는다.
- 새 operation ID로 같은 PR 요청이 들어와도 deterministic marker가 같은 PR을 반환한다.
- GitHub PR/CI/status **조회**가 실패하거나 시간이 초과돼도 그 측정은 `MEASUREMENT_UNVERIFIED`로 분류한다. 조회 실패는 GitHub PR 자체의 실패 증거가 아니며 Claim을 만들거나 정상 개발을 막지 않는다.
- push/merge 같은 **실제 변경**은 GitHub ref·PR state와 exact SHA를 독립 조회해 결정한다. 불완전한 첫 조회만으로 실패/성공/새 작업 차단을 결정하지 않고, 조회 경로를 고친다.
- 일반 상태 관측은 필요할 때 새 관측으로 다시 확인할 수 있다. 변경 작업의 동일 Operation ID 및 exact-SHA 보호는 유지하되, 과거 계측 UNKNOWN이나 Claim을 전역 작업 정지 근거로 사용하지 않는다.
- 현재 운영 원칙은 `docs/MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md`를 따른다.

## Authentication and secrets

BCT는 token을 인자, TOML, SQLite receipt 또는 로그에 저장하지 않는다. `GhCliClient`는 `gh api`를
argument vector로 호출하며 `gh`의 기존 credential store와 account selection을 그대로 사용한다.
repository permission 변경, token 발급, repository 생성은 이 기능의 범위가 아니다.

## Deliberate boundaries

- 자동 polling daemon은 없다. CI 상태는 새 read operation으로 조회한다. 선택적인
  `wait_seconds`(최대 300초)는 해당 operation 안에서만 5초 간격으로 대기하며, MCP에서는
  기존 one-shot worker가 처리한다. 완료 영수증은 재실행 없이 회수한다.
- 필수 check 이름은 작업이 명시한다. GitHub plan상 branch protection을 사용할 수 없더라도 merge 전 동일 gate를 적용한다.
- deployment/service/MCP/RCC는 이 통합에 포함하지 않는다.
