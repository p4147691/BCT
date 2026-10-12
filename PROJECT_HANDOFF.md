# BCT 인수인계

## 현재 결정

- 이름: BCT. 약어 풀네임은 미정. 저장소 p4147691/BCT, private, main.
- 기능을 원격으로 끌어다 쓰는 wrapper에 머물지 않고 실제 기능 소스와 테스트를 BCT에 둔다.
- 기존 ACT 운영과 MCP/Chrome 연결을 보존하면서 기능별로 전환한다.
- core / features / integrations의 작은 단일 패키지로 시작한다.
- node_id / 표시 속성 / connection generation / authenticated principal / work ownership을 분리한다.
- 공통 정책 판단 구현은 하나, 실행 직전 대상 검사와 원격 인증은 실행 경계에서 유지한다.
- 설계의 유일한 상세 기준은 docs/DESIGN.md다.

## 완료된 구현과 현재 경계

FIRST_SLICE_COMPLETE / GITHUB_INTEGRATION_V1_ACCEPTED / DEPLOYMENT_SERVICE_V1_ACCEPTED / MCP_V1_ACCEPTED.
코어 구조·노드 신원·권한 경계 및 동시 변경/중복 실행/인계 계약을 구현했다.
파일 읽기·원자적 쓰기, Python test, expected HEAD·정확한 dirty set·new-file SHA proof 기반 Git commit을 BCT 소스로 구현했다.
13개 first-slice 로컬 테스트에서 실제 격리 Git 흐름, wrong principal, duplicate operation, UNKNOWN 중복 차단, foreign dirty, stale hash/HEAD, symlink escape 및 인계를 검증했다.
GitHub Actions run `38234844806`에서 최신 Actions major로 Windows CI가 통과했다.
ACT 전체 feature 호환, MCP/RCC, LIVE 배포는 아직 없다.
현재 ACT live, 기존 탭/role binding, 서비스, 기존 작업과 소스는 이 설계 작업에서 수정하지 않았다.

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
`D:\PROJECTS\BCT`의 명시된 파일을 `D:\BCT\runtime\releases\<source-head>`로 옮길 수 있다.
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

## 다음 이전 순서

다음 feature는 마지막 단계인 RCC다. 기존 Chrome profile/extension/native host와 production
bindings를 먼저 read-only로 식별하고, 검증된 relay 기능 소스와 테스트를 BCT에 가져온다. BCT
RCC live acceptance 전까지 기존 ACT/RCC 운영 경로와 탭을 유지한다.
