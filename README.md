# BCT

BCT는 사용자 지시에 따라 개발 작업을 끝까지 수행하기 위한 작은 제어 시스템이다.
기존 ACT의 기능 구현과 테스트를 BCT 안으로 단계적으로 이전한다.

## 현재 상태

FIRST_SLICE_COMPLETE / GITHUB_INTEGRATION_V1_ACCEPTED / DEPLOYMENT_SERVICE_V1_ACCEPTED / MCP_V1_TESTED.
코어 구조와 파일 읽기·쓰기, Python 테스트, 정확한 Git commit의 첫 구현을 마쳤다.
격리된 Git 프로젝트에서 읽기 → 수정 → 재수정 → 새 파일 → 테스트 → commit을 실제 검증했다.

GitHub 통합은 exact-SHA branch push, 요청 표식 기반 PR 중복 방지, required-check 확인,
exact-head merge, verified `main`의 clean fast-forward 동기화를 BCT 기능으로 제공한다.
GitHub 인증정보는 저장하지 않고 공식 `gh` CLI의 기존 credential store를 사용한다.
이 기능 자체를 사용해 PR #2를 생성·중복 검증·CI gate·1회 merge하고 로컬 `main`을
merge SHA로 동기화하는 실제 수용 검증을 완료했다.
배포·서비스 V1은 exact named profile, immutable release, process fingerprint ownership,
health 확인, 중복 방지와 rollback을 구현하고 전체 회귀 및 `D:\BCT\runtime` 운영 acceptance를
통과했다. BCT core service는 포트 18790에서 독립 실행된다. MCP V1은 같은 서비스 안의
인증된 표준 Streamable HTTP endpoint와 capability 기반 catalogue를 구현하고 focused test를
통과했다. RCC 전환은 아직 수행하지 않았다. 현재 ACT는 계속 운영한다.

## 구조

`사용자/인증된 MCP → core → BCT 안의 feature 구현 → 실행 결과`

- core: 작업·공통 권한 판단·변경 충돌·operation 결과.
- features: 파일·Git·테스트·배포·서비스·RCC의 실제 구현과 연결 계약.
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
10. [인수인계](PROJECT_HANDOFF.md)

GitHub main은 BCT 소스 정본이다. 인증정보, Chrome 프로필, 사용자 설정과 runtime DB/log는 커밋하지 않는다.

## 로컬 검증

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src tests
```
