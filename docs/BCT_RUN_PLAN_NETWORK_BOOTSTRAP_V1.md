# BCT 독립 정보 확인 → run-plan → 대화망 구성 계약 V1

## 결정
- 독립 명령의 책임은 **정보 확인(읽기)**, **run-plan(계획 검증·버전 저장)**, **network setup(대화망·역할 실제 변경)**으로 분리한다.
- 기존 PR #381 task-run/chain-run과 분리. Core Gen255, 운영 DB·Chrome/RCC·Monitor 변경 금지.
- 단일 A 노드로 시작 가능. 필요 없으면 대화망·매니저 생성 강제하지 않음.
- AI는 요구사항과 확인된 맥락을 근거로 목표·완료 조건·단계·가정·재량을 작성한다. BCT는 AI 판단을 중복하지 않고 계약 검증과 영속 저장을 맡는다.

## 순서
```text
1. info-check (논리적 독립 조회; 기존 status node/rcc + project-context 재사용)
   현재 노드, 프로젝트 유무, 이전 Work, 실제 탭/대화 식별, 사용 가능한 작업자
   └─ 증거 부족: 추가 조회 → 합리적 가정 표기 → 핵심 결정만 사용자 질문
2. run-plan (신규 독립 명령 후보)
   입력: project_id? / request / objective / acceptance / steps[] /
         assumptions[] / assigned_nodes[] / discretion / expected_version?
   출력: plan_id / version / 0-N 단계 / source_refs / setup_required / status
   └─ 같은 요청 재호출은 중복 생성하지 않음. 수정은 새 버전과 변경 사유로 기록
3. network-setup (별도 실행 명령 후보)
   기존 대화망 재사용 또는 필요 시 생성, 노드 역할·소속 수정, 부족하면 새 탭/창
   ├─ 기존 upsert_project/upsert_conversation/set_membership 기능 재사용
   ├─ 기존 conversation_network_update membership-assign/role-patch 재사용
   └─ 역할 메타데이터는 실행 권한이 아님. 대상 연결 검증은 별도
4. session-start / node-sync / 필요한 경우 project-run-bind
   계획/세션/실제 RCC attachment의 관계를 영속 기록하고 실행 직전 재검증
5. task-run / chain-run → read-only status → 필요한 경우 chain-resume
```

## 계획 재량
- 기본: 목표·완료조건·허용 범위를 유지하며 세부 순서/방법/검증을 자율 조정.
- 단계/담당자/범위가 바뀌면 계획 버전을 증가시키고 변경 이유 기록.
- 보호된 main/LIVE, 권한 확대, 외부 효과는 기존 Work 권한·승인 경계를 따른다.
- 사소한 미확정 사항은 진행 차단하지 않으며 증거 없는 UNKNOWN/Claim 측정을 결정 근거로 사용하지 않는다.

## 현재 소스에서 확인한 재사용 범위
- `project_run.start_project_run`: 기존 활성 대화망, Manager 역할 태그, 단일 활성 실행을 요구. 일반 run-plan 엔진으로 재사용하지 않음.
- `conversation_network.upsert_project/upsert_conversation/set_membership`: 대화망과 노드 메타데이터 저장.
- `ConversationNetworkUpdateFeature`: membership-assign / role-patch 변경 계약.
- `bct_status(scope=node/rcc)`: 현재 관측 정보. 과거 기록은 project-context 별도 조회.
- `session-start`와 `node-sync`: 실행 세션/attachment 영속 기록.
- `task-run` / `chain-run`: PR #381, 아직 LIVE 미적용.

## 구현 게이트
- 먼저 정보 조회는 기존 도구 조합으로 제공하되 새 중복 DB를 만들지 않는다.
- run-plan 영속 저장은 기존 ProjectMemoryStore/Work journal과의 정확한 ID·버전·원자성·권한 계약 확인 후 구현.
- 대화망 생성은 Monitor 우클릭과 동일한 기존 저장 경로를 재사용하는 명령으로 분리.
- 빈 프로젝트, 기존 프로젝트, A 단독, 신규 작업자, 중간 계획 변경, 중복 호출, 잘못된 노드 ID를 격리 테스트.
- 이 문서는 계약 설계이며 **새 공개 명령 구현 완료를 뜻하지 않는다**.
