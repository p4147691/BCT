# BCT Foundation — 다음 구현

상태: CORE_DESIGN_COMPLETE / FIRST_SLICE_PENDING.

## 이번 설계 단계

완료: core 구조, node identity, authorization boundary, operation 중복/인계 계약, 설계 시나리오 검토.
미완료: 구현, 실제 테스트/CI, ACT 기능 호환, MCP/RCC LIVE 전환.
사용자는 이 설계 단계 후 SOL로 구현을 이어가기로 했다.

## 다음 작업의 범위

단일 Python 패키지와 SQLite를 사용해 docs/DESIGN.md의 core와 첫 files/git/tests 경로를 구현한다.
첫 검증 대상은 격리된 disposable Git 프로젝트다. 기존 ACT task/worktree/live 파일을 수정할 필요가 없다.

1. 현재 ACT 파일/Git/테스트 구현과 관련 테스트의 exact source commit/path/의존성 확인.
2. 필요한 구현과 테스트를 BCT 안에 가져오고 provenance/라이선스 기록. ACT 전체 gateway 영구 의존 금지.
3. core의 계약·정책·identity·store·operations 구현.
4. 실제 read → edit → re-edit → new file → test → commit 완료.
5. 설계 검토표의 관련 항목을 실제 테스트로 연결. 권한 거부/충돌/crash/duplicate도 포함.
6. GitHub CI와 결과를 저장하고 다음 feature 이전 범위를 명시.

첫 경로에서 기능마다 새로운 registry/권한 저장소/receipt engine을 만들지 않는다.
필요 없는 deploy/services/rcc 모듈은 아직 만들지 않는다.
기능이 추가될 때만 core 계약을 작게 확장한다.

## 첫 구현 acceptance

- 인증된 사용자 요청 범위의 미등록 개발 프로젝트 작업 가능.
- node 없이도 정상 로컬 작업 가능.
- name/role/group 변경 후 기존 work와 권한 유지.
- wrong principal, foreign dirty, stale hash/HEAD 및 reparse 우회 거부.
- task-owned 신규 파일과 여러 번 수정한 파일을 함께 commit.
- 동일 operation 두 번 요청해도 executor는 한 번.
- 실제 실행의 결과 유실은 UNKNOWN; 새 ID로 중복 효과 생성 금지.
- 이전 실행 없음 + terminal evidence일 때 인계 가능.
- 테스트 통과/실패가 실제 결과와 일치하며 source 완료를 LIVE 완료라고 보고하지 않음.

## 이후 기능 이전

GitHub 통합 → 배포/서비스 → MCP/RCC 순서를 기본으로 하되 실제 의존성 확인 후 조정 가능.
각 기능은 BCT에 실제 소스와 테스트를 두고 공개 계약·설치 연결을 확인한 다음 운영 전환한다.
전체 기능 보존 목록은 실제 조사로 확정한다. 이전 전 기능을 compatible로 표시하지 않는다.
현재 ACT와 BCT가 같은 물리 대상의 독립 writer가 되지 않게 한다.

## 최종 BCT 완료 기준

기능별 구현/회귀/설정 보존/복구 및 live acceptance가 모두 증명되어야 한다.
노드 이름·그룹·연결·실행자 변경이 필요한 범위에만 영향을 주는지 실제 검증한다.
현재 상태와 차단 이유를 한 경로에서 확인할 수 있어야 한다.
