# BCT 인수인계

## 현재 결정

- 이름: BCT. 약어 풀네임은 미정. 저장소 p4147691/BCT, private, main.
- 기능을 원격으로 끌어다 쓰는 wrapper에 머물지 않고 실제 기능 소스와 테스트를 BCT에 둔다.
- 기존 ACT 운영과 MCP/Chrome 연결을 보존하면서 기능별로 전환한다.
- core / features / integrations의 작은 단일 패키지로 시작한다.
- node_id / 표시 속성 / connection generation / authenticated principal / work ownership을 분리한다.
- 공통 정책 판단 구현은 하나, 실행 직전 대상 검사와 원격 인증은 실행 경계에서 유지한다.
- 설계의 유일한 상세 기준은 docs/DESIGN.md다.

## 이번 완료와 한계

CORE_DESIGN_COMPLETE / IMPLEMENTATION_PENDING.
코어 구조·노드 신원·권한 경계 및 동시 변경/중복 실행/인계 계약을 설계했다.
docs/CORE_DESIGN_REVIEW.md에 34개 시나리오를 정리했다. 설계 검토이며 실행 테스트 PASS가 아니다.
ACT 전체 소스 조사, feature 호환 검증, BCT 실행 코드/CI/LIVE 배포는 아직 없다.
현재 ACT live, 기존 탭/role binding, 서비스, 기존 작업과 소스는 이 설계 작업에서 수정하지 않았다.

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

## 다음 한 작업

docs/exec-plans/active/BCT_FOUNDATION.md를 따라 core + files/git/tests 첫 경로를 구현한다.
필요한 현재 source entrypoint만 읽고 disposable Git 프로젝트에서 편집·재편집·신규 파일·test·commit을 검증한다.
사용자가 모델을 변경해도 이 결정과 승인 범위를 유지한다.
