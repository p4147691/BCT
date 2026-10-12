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
- push는 실패/timeout 뒤 remote ref를 다시 읽는다. exact target SHA이면 적용, 이전 SHA이면 실패,
  그 외 상태이면 `UNKNOWN`으로 claim을 유지한다.
- PR create/merge 응답이 유실되면 GitHub 상태를 재조회한다. exact 결과가 증명될 때만 `APPLIED`다.
- merge는 API 응답만 신뢰하지 않고 PR의 merged state와 merge commit SHA를 다시 검증한다.
- `UNKNOWN`은 자동 재시도하지 않으며 같은 resource의 새 operation도 공통 claim이 차단한다.

## Authentication and secrets

BCT는 token을 인자, TOML, SQLite receipt 또는 로그에 저장하지 않는다. `GhCliClient`는 `gh api`를
argument vector로 호출하며 `gh`의 기존 credential store와 account selection을 그대로 사용한다.
repository permission 변경, token 발급, repository 생성은 이 기능의 범위가 아니다.

## Deliberate boundaries

- 자동 polling daemon은 없다. CI 상태는 새 read operation으로 조회한다.
- 필수 check 이름은 작업이 명시한다. GitHub plan상 branch protection을 사용할 수 없더라도 merge 전 동일 gate를 적용한다.
- deployment/service/MCP/RCC는 이 통합에 포함하지 않는다.
