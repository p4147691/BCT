# BCT

BCT는 사용자 지시에 따라 개발 작업을 끝까지 수행하기 위한 작은 제어 시스템이다.
기존 ACT의 기능 구현과 테스트를 BCT 안으로 단계적으로 이전한다.

## 현재 상태

CORE_DESIGN_COMPLETE / IMPLEMENTATION_PENDING.
코어 구조·노드 신원·권한 경계 설계를 확정하고 시나리오 검토를 마쳤다.
실행 코드, 기능 이전, CI 및 LIVE 전환은 아직 수행하지 않았다. 현재 ACT는 계속 운영한다.

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
3. [다음 구현 작업](docs/exec-plans/active/BCT_FOUNDATION.md)
4. [인수인계](PROJECT_HANDOFF.md)

GitHub main은 BCT 소스 정본이다. 인증정보, Chrome 프로필, 사용자 설정과 runtime DB/log는 커밋하지 않는다.
