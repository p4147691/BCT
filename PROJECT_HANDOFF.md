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

FIRST_SLICE_COMPLETE / GITHUB_INTEGRATION_V1_ACCEPTED.
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

다음 feature는 배포·서비스다. BCT 실행 코드를 소스 checkout과 분리된 안정된 설치/서비스로
운영하고, exact source/runtime SHA·backup·atomic replace·rollback·최소 restart·health verification을
한 계약으로 구현한다. 그 다음 MCP, 마지막으로 RCC를 이전한다. 각 기능은 전환 acceptance 전까지
기존 ACT 운영 경로를 유지한다.
