# RCC Rebuild V2 — 통합 종료 계획

상태: `V2_5_RC1_ROLLED_BACK / RC2_FIX_PENDING_CI / LIVE_BASELINE_RESTORED`

V1의 API별 Adapter 추가 방식은 여기서 종료한다. 이 문서는 RCC를 실제로 끝낼 수 있도록
남은 책임 전체, 한 번에 묶을 전환 단위, LIVE 전환 시점과 완료 조건을 다시 고정한 실행 계획이다.

## 1. 왜 계획을 다시 세우는가

2026-10-20 source HEAD `40083383a236072d7e14cea4530eb1719adc327e` 기준으로
`modules/rcc/extension/background.js`는 5,103줄, `content.js`는 4,458줄이다.
background에는 다음 Chrome 경계가 아직 직접 섞여 있다.

- `chrome.storage.local` 61곳, `chrome.storage.session` 2곳
- `chrome.scripting.executeScript` 14곳
- `chrome.tabs.get` 13곳, `chrome.tabs.sendMessage` 3곳
- tab/window/webRequest/runtime lifecycle listener와 Native Messaging 연결

그러나 현재 정책이 실제로 허용하는 변경 경로는 Simple Relay V0의 bind/send/return뿐이다.
runtime message도 상태·pending·activity 읽기만 허용된다. 과거 ACT 자동화, 등록, rename,
일반 browser mutation 구현은 정책 앞에서 차단되지만 구현과 보조 함수가 같은 파일에 남아 있다.

따라서 남은 문제는 “다음 Chrome API 하나를 Adapter로 옮기는 일”이 아니다. 먼저 현재 계약상
도달할 수 없는 레거시를 제거하고, 실제 활성 기능 전체를 책임 경계별로 분리해야 한다.

## 2. 이번 재구축의 고정 범위

### 유지할 활성 기능

1. conversation UUID로 정확한 열린 ChatGPT 대화를 찾고 상태를 읽는다.
2. Manager→Worker 원문 한 건을 제출하고 영수증을 남긴다.
3. Worker 응답 원문 한 건을 Manager로 반환하고 영수증을 남긴다.
4. 상태, 결과, probe, bounded diagnostics 같은 읽기 전용 조회를 제공한다.
5. 수신기가 없을 때 content receiver를 주입하고 한 번만 재확인한다.

### 활성 경로에서 제거할 기능

- 정책이 이미 차단한 ACT orchestration, registration, rename, manual/automatic send 경로
- 차단된 native/runtime command 전용 구현과 호출자가 없는 보조 함수
- 활성 계약에서 도달할 수 없는 content message handler와 DOM 자동화
- 구경로 fallback 및 효과가 불명확한 자동 재시도

### 보존하되 활성화하지 않을 기능

이미 분리한 tab move/create/close/reload, window create Adapter와 영수증 계약은 향후 BCT가
명시적으로 browser management capability를 공개할 때 재사용할 수 있도록 source에 보존한다.
이번 재구축에서 active loader나 Simple Relay 권한에 연결하지 않는다.

## 3. 목표 구조

```text
modules/rcc/extension/
├─ boot/
│  └─ background_app                 조립, route 등록, 시작·종료만 담당
├─ platform/
│  ├─ chrome_state_repository        모든 chrome.storage 접근
│  ├─ browser_gateway                exact tab 조회, message, receiver 주입
│  ├─ observation_gateway            tab/window/webRequest 관측 event
│  ├─ native_transport               Native Host 연결·응답·재연결
│  └─ lifecycle                      확장 lifecycle/reload 경계
├─ domain/
│  ├─ endpoint_service               UUID·상태·presence
│  ├─ simple_relay_service           bind/send/return
│  ├─ simple_relay_receipts          intent·terminal receipt
│  └─ readonly_diagnostics           허용된 bounded 조회
├─ content/
│  ├─ content_router                 활성 message 종류만 분기
│  ├─ conversation_dom               exact 대화·editor·응답 읽기
│  ├─ simple_relay_executor          원문 제출·응답 원문 반환
│  └─ activity_reporter              bounded activity 관측
├─ optional/browser_management/      보존된 browser mutation Adapter
└─ legacy/command_policy             호환 오류와 fail-closed 경계만 담당
```

의존 방향은 `boot → domain → platform`, `content_router → content modules`로 고정한다.
domain은 `chrome.*`를 직접 호출하지 않는다. optional 기능은 active loader가 불러오지 않는다.
정책이 차단한 구현을 active bundle 안에 남겨 두지 않는다.

## 4. 통합 실행 단계

### V2-0 — 기준선과 계획 동결

- 현재 source HEAD, 설치본 identity/hash, extension ID, Native Host 이름·경로, binding UUID를 기록한다.
- 허용 native command/runtime message matrix와 storage key, wire message 이름을 계약 테스트로 고정한다.
- V1의 API별 Adapter 연속 작업을 중단하고 이 계획을 유일한 후속 기준으로 삼는다.
- source 코드, 설치본, Chrome, Native Host, binding은 변경하지 않는다.

통과 조건: 이 문서와 V1 superseded 표시가 main에 있고 CI가 통과한다.

### V2-1 — 죽은 레거시 일괄 제거 (source-only)

- command policy 앞에서 항상 차단되는 native/runtime branch를 한 묶음으로 삭제한다.
- 그 branch만 호출하던 background/content helper와 listener를 call graph 증거로 함께 제거한다.
- Simple Relay, exact conversation 조회, 읽기 전용 diagnostics는 이름과 결과 계약을 유지한다.
- browser management Adapter는 optional source로 보존하되 active loader에서 제외한다.

2026-10-20 실행 결과는
`BCT_RCC_REBUILD_V2_STAGE1_LEGACY_PRUNE_20261020.md`에 기록한다. 이 단계는 source와
테스트만 변경하며 설치본·Chrome·Native Host·binding에는 반영하지 않는다.

통과 조건:

- 허용 호출의 결과 계약이 이전과 동일하다.
- 차단 호출은 이전과 같은 fail-closed 오류를 반환한다.
- Simple Relay와 read-only 회귀 테스트가 통과한다.
- 제거 대상마다 활성 caller가 0임을 정적 검사 또는 테스트로 증명한다.

### V2-2 — 플랫폼 경계 일괄 분리 (source-only)

- 모든 storage 접근을 `chrome_state_repository`로 모은다.
- exact tab 조회, message, receiver 주입을 하나의 `browser_gateway`로 모은다.
- Native Messaging, 관측 listener, lifecycle을 각각 transport/observation/lifecycle 경계로 옮긴다.
- API 호출 하나마다 새 단계나 새 Adapter를 만들지 않는다. 기존 browser mutation Adapter는
  gateway가 필요할 때 조합하는 optional 효과 구현으로만 둔다.

2026-10-20 실행 결과는
`BCT_RCC_REBUILD_V2_STAGE2_PLATFORM_BOUNDARIES_20261020.md`에 기록한다. active background의
Chrome 효과는 다섯 플랫폼 모듈로 이동했고, 이 단계도 source와 테스트만 변경한다.

통과 조건:

- domain과 boot 조립 코드에 직접 `chrome.*` 호출이 0개다.
- storage key, native wire command, content message 이름이 바뀌지 않는다.
- background 진입점은 조립과 route 등록만 수행한다.

### V2-3 — 활성 도메인·content 일괄 분리 (source-only)

- endpoint, Simple Relay, receipt, read-only diagnostics를 독립 domain service로 옮긴다.
- content의 활성 router, DOM 판별, submit/read, activity 관측을 분리한다.
- 활성 메시지에서 도달할 수 없는 content handler와 helper를 제거한다.
- 원문을 요약·변환하지 않으며 전송 방향과 UUID binding 의미를 바꾸지 않는다.

2026-10-20 실행 결과는
`BCT_RCC_REBUILD_V2_STAGE3_DOMAIN_CONTENT_20261020.md`에 기록한다. background와 content 진입점은
각각 3줄 조립 파일이 되었고, domain/content 활성 구현은 책임별 파일로 이동했다. 이 단계도
source와 테스트만 변경한다.

통과 조건:

- `background.js`와 `content.js`는 각각 조립/router 중심의 600줄 이하 파일이다.
- active loader가 불러오는 파일에는 zero-caller 구현이 없다.
- Manager→Worker 및 Worker→Manager fixture가 원문 byte 기준으로 동일하다.
- 전체 RCC JavaScript/Python 회귀 테스트가 통과한다.

600줄은 코드를 잘게 쪼개기 위한 목표가 아니라 다시 여러 책임이 한 파일에 합쳐지는 것을 막는
상한이다. 더 작은 파일 수 자체는 완료 조건이 아니다.

### V2-4 — 통합 Release Candidate 검증 (아직 비-LIVE)

- V2-1~3 결과를 하나의 coherent payload로 조립한다.
- active loader graph, dependency rule, allowed message matrix, storage/wire 호환성을 자동 검사한다.
- 전체 로컬 테스트와 원격 CI를 통과시키고 exact payload manifest, SHA, backup/rollback 절차를 만든다.
- 설치본과 Chrome은 여전히 변경하지 않는다.

2026-10-20 실행 결과는
`BCT_RCC_REBUILD_V2_STAGE4_RELEASE_CANDIDATE_20261020.md`에 기록한다. Chrome Extensions 공식
API 경계를 재점검해 sender validation, 최소 permission과 read-only popup을 보완했고, exact
46-file candidate와 현재 LIVE 39-file rollback baseline을 비-LIVE에서 검증했다.

통과 조건: main exact SHA의 CI가 통과하고, 후보 payload 전체와 rollback payload 전체의 해시가
검증되며, unknown effect가 없다.

### V2-5 — 단일 LIVE 전환 (별도 명시 허용 후)

- 현재 설치본을 exact backup하고 하나의 coherent payload만 설치한다.
- same-ID 확장을 정확히 한 번 reload한다.
- Native Host 이름·경로, extension ID, Chrome profile, storage, binding UUID는 변경하지 않는다.
- read-only state/probe로 Manager·Worker exact conversation을 먼저 확인한다.
- 사용자가 확인한 원문으로 Manager→Worker 한 건, Worker→Manager 한 건만 acceptance한다.
- 어느 층이든 mismatch/ambiguous/unknown이면 추가 전송 없이 exact backup으로 rollback한다.

통과 조건: source/main/설치 payload/runtime SHA가 연결되고 두 방향 원문 영수증과 postcondition이
일치한다. reload나 부분 배포를 모듈마다 반복하지 않는다.

2026-10-20 첫 RC1 전환은 read-only state/probe까지 통과했으나 첫 Manager→Worker 수락시험에서
실제 생성 정황과 `NOT_APPLIED` 영수증이 충돌했다. 재전송·반환 없이 exact baseline으로 즉시
rollback했다. 원인과 RC2 보완은
`BCT_RCC_REBUILD_V2_STAGE5_LIVE_CUTOVER_20261020.md`에 기록한다. RC2는 CI 통과 전 LIVE에
재적용하지 않는다.

### V2-6 — 정리와 종료

- LIVE에서 호출자가 0임이 다시 확인된 구파일만 삭제한다.
- V1/V2 실행 문서를 completed로 옮기고 최종 구조도, manifest, rollback, acceptance 영수증을 남긴다.
- BOOTSTRAP/REGISTRY/PROJECT_HANDOFF에 완료 상태와 남은 optional 기능만 기록한다.

## 5. 변경 금지선

- V2-4가 통과하기 전에 LIVE 설치본, Chrome, Native Host, binding을 변경하지 않는다.
- 새 extension ID, 새 unpacked extension, 새 profile, storage migration을 만들지 않는다.
- UNKNOWN 전송을 재실행하거나 구경로로 fallback하지 않는다.
- zero-caller 증거 없이 코드를 삭제하지 않는다.
- browser API 하나를 옮겼다는 이유로 별도 사용자 단계, 별도 배포, 별도 reload를 만들지 않는다.
- 구조 정리를 이유로 wire protocol, storage key, 대화 UUID 의미를 동시에 바꾸지 않는다.

## 6. 최종 완료 정의

다음을 모두 만족해야 RCC 재구축이 끝난다.

1. 활성 background/content 진입점은 조립·route 역할만 하며 각 600줄 이하다.
2. domain에는 직접 `chrome.*` 호출이 없고 모든 플랫폼 효과가 한눈에 추적된다.
3. active bundle에는 정책상 영구 차단된 구현과 zero-caller 코드가 없다.
4. Simple Relay의 양방향 원문, exact UUID, 중복 방지, 영수증 계약이 유지된다.
5. optional browser management 기능은 relay 권한과 분리되어 보존된다.
6. 전체 로컬 테스트, 원격 CI, exact-SHA payload 검증이 통과한다.
7. 단 한 번의 same-ID LIVE 전환 후 두 방향 acceptance와 rollback 가능성이 확인된다.
8. 설치 경로, extension ID, Native Host, Chrome profile과 기존 대화가 유지된다.

이 완료 정의를 충족하기 전에는 “Adapter 몇 개를 더 분리했다”를 RCC 재구축 완료로 보고하지 않는다.
