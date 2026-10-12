# BCT Core V1 — 구현 기준

상태: CORE_V1_IMPLEMENTED / GITHUB_INTEGRATION_V1_ACCEPTED.
범위: 코어 구조, 노드 신원, 권한 경계와 첫 구현 계약.
이 문서는 설계 결정이다. 구현 테스트, ACT 전체 감사, 기능 호환 및 LIVE acceptance의 증거가 아니다.

## 1. 확정 방향

사용자는 BCT 안에 실제 기능 소스를 두고, 노드와 설정을 쉽게 변경할 수 있기를 원한다.
ACT 전체를 영구적으로 호출하는 wrapper는 최종 구조로 삼지 않는다.
검증된 구현과 테스트를 기능 단위로 가져오며, 이전된 기능의 소스 정본은 BCT main 한곳이다.

기존 ACT는 기능별 전환이 검증될 때까지 운영한다.
현재 Chrome/MCP 설정을 다시 만들지 않고 이어 쓰는 것을 이전 acceptance에 포함한다.
코드 위치 변경과 설치/연결 설정 변경은 별개다. 설정 보존 가능 여부는 실제 설치 증거로 확인한다.

## 2. 최소 구조와 의존 방향

예정 코드 배치:

    src/bct/
      core/
        models.py       # 아래 공통 계약과 enum
        identity.py     # node 속성, 연결 교체, 인계의 신원 검증
        policy.py       # 권한/추가 승인 판단의 유일한 구현
        operations.py   # 작업·operation 실행 조정, 중복/충돌/복구
        store.py        # SQLite 원자적 상태 변경
      features/             # thin capability adapters; not separate authorities
        files/          # BCT가 소유하는 실제 파일 구현 + adapter
        git/
        tests/
        deploy/
        services/
    modules/
      bdc/                  # BCT Desktop Control
      rcc/                  # browser relay product and native host source
      monitor/              # DesktopWindow Monitor source
      decision/             # local model lifecycle boundary
      github/               # GitHub/runner operating contract
      status-ui/            # read-only BCT operational screen
      integrations/
        mcp/            # 인증된 요청 변환과 공개 도구 계약
        act_compat/     # 필요한 기능에만 적용하는 임시 이전 연결

최초 구현은 core와 files/git/tests만 만든다. 빈 기능 모듈이나 범용 plugin loader를 미리 만들지 않는다.
MCP는 transport이고 기능 실행의 필수 전제는 아니다. 초기 검증은 같은 core의 로컬 entrypoint로 가능하다.
RCC 확장·Native Host처럼 별도 프로세스가 필요한 기존 구성은 유지할 수 있다.
BCT 제어부는 단일 Python 프로세스·단일 패키지로 시작한다. 정책 서버, 별도 스케줄러, 메시지 브로커는 추가하지 않는다.

의존 방향:
- integrations → core.operations
- core.operations → core.policy / core.identity / core.store / 명시적으로 등록된 feature 계약
- features → 공통 models. 다른 feature 내부나 구형 gateway를 암묵적으로 호출하지 않는다.
- core는 Chrome tab, MANAGER/EXEC 같은 역할 이름, 특정 모델 이름에 의존하지 않는다.

기능 목록은 실행 함수·입출력·효과 종류·대상 해석 함수·evidence 조회 지원 여부를 등록한다.
MCP catalogue도 이 목록에서 생성/검사하여 공개만 되고 실행기가 없는 도구를 방지한다.
복잡한 자동 discovery나 별도 registry service를 만들지 않는다.

## 3. 설정과 운영 상태의 정본

소스 전달 단계의 용어는 고정한다. GitHub main이 유일한 공식 소스다. 로컬 checkout과
worktree는 개발 사본이며, runtime과 Chrome extension 폴더는 특정 commit에서 배포한
설치·실행 사본이다. 이 관계는 BCT 자체와 BCT가 다루는 사용자 프로젝트에 동일하게
적용한다. 운영 DB, receipt, 모델 weight와 Chrome profile은 소스가 아니라 상태/자산이다.

- bct.toml: 사람이 관리하는 정책/위험 기본값/기능 설정. 명시한 사용자 요청 안의 일반 개발 작업은 기본 허용.
- state.sqlite: node, connection, work, operation, resource_claim, event 및 적용 revision.
- OS credential store/기존 안전한 인증 저장소: 비밀정보. TOML/Git/receipt에는 비밀 값 저장 금지.
- GitHub main: 소스와 설계. 현재 task/연결의 live truth가 아니다.

설정과 노드의 관리 entrypoint는 하나로 제공한다. 내부 데이터는 성격에 따라 분리한다.
정책 설정은 문법 검증 후 atomic replace하고 content hash를 policy_revision으로 사용한다.
각 호출은 현재 정책 파일을 확인한다. 불완전/잘못된 새 설정이면 mutation은 실행하지 않고 정확한 설정 오류를 반환한다.
노드 속성 변경은 expected_revision으로 갱신한다. 병렬 변경은 재조회 후 반영하며 조용히 덮어쓰지 않는다.
운영자가 두 저장소를 직접 맞추는 절차를 만들지 않는다.

## 4. 공통 계약

| 계약 | 최소 정보 | 책임 |
| --- | --- | --- |
| Principal | principal_id, 인증 출처, 허용 capability/scope | ingress가 인증에서 생성. caller JSON의 주장만 신뢰하지 않음 |
| Node | node_id, name, role?, group?, revision, active | 논리 작업 공간/표시와 라우팅 |
| Connection | connection_id, node_id, kind, instance/session, endpoint, generation | 실제 MCP/browser endpoint와 연결 세대 |
| Work | work_id, request_summary, authorized_scope, owner_principal_id, assignment_epoch, state | 사용자 요청과 현재 변경 주체 |
| Operation | operation_id, work_id, request_digest, capability, target, evidence, outcome | 실제 실행 한 건 |
| Decision | ALLOW / APPROVAL_REQUIRED / DENY, reason_code, next_action, policy_revision, approval_ref? | 공통 권한 판단 결과 |
| Result | operation_id, outcome, evidence_refs, error?, timing | transport와 무관한 실행 결과 |

node_id는 생성 후 변경하지 않는 논리 UUID다. name/role/group은 자유롭게 바꿀 수 있다.
인증 주체와 Node는 서로 다르다. 조직 역할은 기술 권한을 부여하지 않는다.
작업은 node가 사라져도 남는다. 소유권은 principal과 assignment_epoch로 확인한다.
모든 작업에 별도 task/attempt/lease ID 세트를 사용자에게 입력시키지 않는다.
기존 ACT attempt/lease가 필요한 임시 연결에서는 adapter가 exact mapping을 관리하며 현재 guard를 지킨다.

authorized_scope는 사용자 요청/기존 명시적 승인에서 만든다.
실행 AI가 임의로 넓힌 scope를 사용자 승인으로 기록해서는 안 된다.
프로젝트 밖의 사용자가 지정한 대상도 검토할 수 있으며 미등록 프로젝트라는 이유만으로 차단하지 않는다.
OS 권한이나 다른 인증 주체의 권한을 BCT 설정만으로 넘어설 수는 없다.

## 5. 노드 변경 계약

- 이름 변경: revision만 갱신. work_id, principal, 연결 및 권한 유지.
- role/group 변경: 이후 기능적 라우팅에 적용. 진행 중 operation 대상은 변경하지 않음.
- 연결 교체: 인증된 관리 요청과 새 endpoint 증거를 확인하고 generation 증가.
- 이전 연결의 뒤늦은 결과: 원래 operation/connection generation에 기록. 새 연결의 결과로 재해석 금지.
- 진행 중 send가 있으면 연결 주소만 바꿔 동일 send를 새 대상에 재실행하지 않음.
- 여러 탭/여러 연결을 node에 연결할 수 있지만 실행 대상은 exact connection_id로 선택.
- node 비활성화: 새 라우팅 중단. 활성 작업·operation·기록은 보존.
- 실행자 인계: old/new principal과 assignment_epoch를 원자적으로 갱신.
- 이름/role/endpoint만으로 자동 인계 또는 다른 사람의 작업 claim 금지.

노드가 없어도 인증된 로컬 개발 작업은 가능하다.
MCP 연결 재접속 또는 Chrome 대화 변경은 그 자체로 새로운 기술 권한 생성 사유가 아니다.
브라우저 창의 화면상 연속성과 실행 권한의 신원은 분리한다.

## 6. 권한 경계와 사용자 승인

정책 판단 순서:
1. ingress 인증 및 요청 형식 검증.
2. 기존 operation 조회 시 인증된 principal의 해당 work/result 조회 권한을 먼저 확인. 동일 ID+다른 요청이면 DENY; 동일 요청이면 허용된 기존 결과/진행 상태만 반환.
3. authenticated principal의 범위와 사용자 요청 범위 확인.
4. 실제 변경 대상과 효과를 feature가 해석. 호출자가 보낸 위험도 라벨만 믿지 않음.
5. 공통 policy가 ALLOW / APPROVAL_REQUIRED / DENY 결정.
6. execution 직전 현재 policy_revision, ownership epoch와 대상 상태를 다시 검증.

일반적인 요청 범위 내 읽기·편집·테스트·commit은 반복 승인 없이 진행한다.
deploy/restart는 요청에 포함되거나 유효한 기존 승인 범위일 때만 실행한다.
삭제, 인증/권한 확대, 결제, 복구 불가능한 덮어쓰기 등은 영향과 복구 가능성을 보여주고 필요한 명시 승인을 받는다.
비밀정보의 불필요한 읽기/로그 출력/외부 전송은 일반 프로젝트 접근으로 자동 허용하지 않는다.
승인은 principal, work, action/target, request_digest에 묶고 유효 범위를 저장한다.
이름 변경·재접속·같은 operation 결과 재조회는 재승인 사유가 아니다. 대상/내용/효과가 바뀌면 기존 승인의 범위 밖이다.

인증 실패, 실제 foreign writer, stale HEAD/hash, 경로 우회, 불명확한 prior side effect는 구체적인 이유로 차단한다.
과거 task 실패나 비활성 node가 존재한다는 이유만으로 새 unrelated work를 막지 않는다.
단, 대상이 같은 unresolved operation/resource claim은 새 ID로도 우회하지 못한다.

Decision을 bearer 권한 토큰처럼 다른 프로세스에 재사용하지 않는다.
원격 feature는 기존 인증 경계를 보존하고 실제 요청 내용과 대상에 대해 검증한다.
정책 판단, 실제 변경 직전 precondition 검사, OS 인증은 서로 다른 책임이다.

## 7. 동시 변경과 인계

독립 worktree는 병렬 사용 가능하다. 같은 물리 파일/서비스/브라우저 대상의 충돌은 원자적 resource_claim으로 막는다.
Git 변경은 repo/index 단위 충돌도 확인하고, 파일 변경은 canonical path·reparse 경계를 검증한다.
같은 work 소유 파일의 재편집은 이전 operation의 확인된 post-hash를 다음 expected-hash로 사용한다.

resource_claim에는 work/operation, principal, assignment_epoch, 실제 실행 fingerprint와 확인 시각을 기록한다.
heartbeat 만료는 조사 신호다. 만료만으로 lock을 해제하거나 성공으로 처리하지 않는다.
이전 실행 부재와 terminal/NOT_APPLIED 증거가 확인되면 기록을 보존하고 자동 인계 가능하다.
이전 실행이 없더라도 결과가 UNKNOWN이면 해당 대상의 재실행은 차단한다.
프로세스 시작 뒤 기록 전 crash 가능성을 feature가 어떻게 확인하는지 지원 여부를 명시한다. 증거를 복원할 수 없다면 UNKNOWN 유지.

BCT claim만으로 ACT writer를 막을 수 있다고 가정하지 않는다.
첫 검증은 격리된 새 프로젝트/워크트리에서 수행한다.
공유 LIVE 대상은 기존 조정 경로가 확인되거나 기존 writer가 정지한 bounded 전환에서만 소유권을 넘긴다.
두 시스템이 같은 작업을 독립 실행하는 기간을 만들지 않는다.

## 8. 중복 실행, 결과와 복구

Operation의 영속 상태:
- RECORDED: 요청과 digest가 기록됐고 실행 시작 전.
- RUNNING: executor 진입이 기록됨. 외부 실행 여부는 이 상태만으로 확정하지 않음.
- FINISHED: outcome/evidence가 기록됨.

outcome:
- APPLIED: 요청 효과가 검증됨.
- NOT_APPLIED: 효과가 발생하지 않았다는 증거가 있음.
- FAILED: 실패가 확인됨. 부분 효과/rollback 여부를 evidence에 명시.
- UNKNOWN: 효과를 증명하지 못함. 자동 재실행 금지.

실행 의도 기록은 operations.py 한 곳이 소유한다.
feature의 세부 단계 증거는 같은 operation에 추가하고 두 번째 독립 intent를 만들지 않는다.
operation_id는 사용자 소유 인스턴스 안에서 유일하다. digest에는 capability, 대상, 입력, work, 의미상 precondition을 포함하고 표시 이름은 제외한다.
동일 ID 재호출은 read/reconcile만 수행하고 executor를 다시 호출하지 않는다.
NOT_APPLIED 후 재시도가 필요하면 원래 결과와 연결된 새 operation_id를 발급하고 새 precondition을 검증한다.
UNKNOWN 상태에서 ID만 바꿔 같은 효과를 실행하려 하면 관련 resource claim이 차단한다.
FINISHED는 결과 기록 완료이지 항상 claim 해제를 의미하지 않는다. UNKNOWN이나 잔여 부분 효과가 있으면 claim을 유지한다.
claim은 실행 부재와 검증된 terminal 결과/완료된 rollback 등 안전한 해제 증거가 있을 때만 해제한다. FAILED만 보고 자동 해제하지 않는다.

외부 UI/프로세스/네트워크에 일반적인 exactly-once 보장을 주장하지 않는다.
보장 목표는 durable intent + 중복 dispatch 차단 + 정확한 증거 기반 reconciliation이다.
RCC 제출 확인과 응답 완료는 별도 기능 단계다. 응답 지연 때문에 확인된 submit을 재전송하지 않는다.

## 9. 기능 계약과 소스 이전

Feature는 validate/execute/inspect_outcome 세 역할을 구현한다.
validate는 효과 없이 대상/precondition을 확인하고, execute는 조정된 operation 한 건을 실행한다.
inspect_outcome은 지원되는 경우 기존 효과를 읽어서 판정하며 재실행하지 않는다.
공통 정책은 core가 판단하고 feature는 실행에 필요한 local precondition만 확인한다.

가져올 때 기능마다 다음만 기록한다:
- 기존 repository/commit/path와 원본 SHA, 라이선스/외부 의존성.
- BCT의 실제 코드/test 위치와 삭제 가능한 ACT 내부 의존성.
- 공개 입력·출력과 기존 동작 acceptance.
- 운영 설치 경로, 연결 identity, 필요한 reload, backup/rollback.
- 아직 이전되지 않은 기능과 source/runtime 상태.

모든 소스를 무작정 복사하거나 기존 runtime DB/프로필/비밀정보를 저장소에 넣지 않는다.
feature마다 단일 BCT 소스 정본을 두고 ACT/BCT 양쪽을 동시에 수정하지 않는다.
ACT 내부 구현 직접 import를 영구 요구하지 않는다.
기능 전체 보존은 목표이며 검증된 목록만 compatible로 표시한다.

MCP 이전 acceptance:
- 기존 connection 주소/실행 진입점을 유지할 수 있는지 확인.
- 공개 tool name/schema 및 결과 계약 보존.
- source/loaded runtime/catalogue 일치, reconnect 확인.
- 승인된 최소 reload. 새 중복 서버를 띄우지 않음.

RCC 이전 acceptance:
- extension ID, 프로필, Native Host 이름/경로/허용 origin 보존 여부 확인.
- 기존 탭/대화/binding 보존, 기존 UNKNOWN send 재실행 금지.
- BCT 소스에서 정확한 파일만 배포하고 reload 후 synthetic operation으로 검증.
- unpacked extension 또는 서명/패키지 방식에 따라 경로 변경 영향이 다르므로 실측 전 무재설정 보장 금지.

## 10. 첫 구현의 범위와 통과 기준

표준 Python + SQLite로 시작하고 ACT의 검증된 언어/라이브러리를 필요한 범위만 가져온다.
범용 workflow engine, 별도 role 관리 서버, 이벤트 소싱, 새 오류 장부, 모든 기능용 빈 plugin은 만들지 않는다.

첫 구현:
1. 공통 계약, 한 정책 경로, node/connection revision, operation 원자적 claim/result.
2. 격리된 disposable Git 프로젝트에서 read → edit → re-edit → create file → test → commit.
3. 사용자 요청 범위, wrong principal, foreign dirty, stale HEAD/hash, duplicate operation, crash gap 검증.
4. node rename/group change/reconnect/handoff가 작업과 권한에 주는 영향 검증.
5. 문서의 acceptance matrix를 실제 테스트 결과로 연결.

이 첫 단계는 구현과 CI까지 완료했다. MCP/RCC 전환과 LIVE acceptance는 후속 상태로 각각 보고한다.
상세 검토 결과는 CORE_DESIGN_REVIEW.md, 완료 증거는 exec-plans/completed/BCT_FOUNDATION.md를 따른다.

GitHub integration V1도 후속으로 완료했다. BCT operation/claim 위에서 exact-SHA push,
idempotent PR creation, required-check gated merge, verified-main fast-forward를 제공한다.
그 구현 계약과 실제 PR/CI/main 수용 증거는 `docs/GITHUB_INTEGRATION.md`와
`docs/exec-plans/completed/BCT_GITHUB_INTEGRATION.md`를 따른다.

## 11. 근거와 남은 검증

이전 조사에서 BOOTSTRAP.md blob a3218f316ca67b754ba370cf8670880949d6c0fe는 tab+conversation을,
ACT AGENTS.md blob 2b73bacad77bc3789bacc126f72f05305c7c0e54는 physical window continuity를 강조했다.
이는 문서상 기준 차이이며 실행 코드 충돌의 증명은 아니다.

현재 결정은 사용자 요구와 기본 설계 원칙에 따른 구현 기준이다.
기존 feature의 exact API/의존성/운영 설치 방식, 전체 이전 일정은 아직 확인하지 않았다.
첫 구현에 필요한 부분만 조사하며 ACT 전체 역사 복원으로 확대하지 않는다.
