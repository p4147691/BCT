# BCT RCC 대화 이름 변경: 원인 분석·복구·완료 전달서

상태: `HANDOFF_READY / IMPLEMENTATION_OWNED_ELSEWHERE`

## 목표와 완료 정의

대화 이름 변경의 응답 유실 또는 결과 확인 실패는 그 이름 변경 하나만 안전하게
보류·복구해야 한다. 다른 탭, 다른 대화, 새 orchestration session, Issue #111 E2E를
막아서는 안 된다.

완료 조건:

1. rename은 exact instance/tab/conversation만 claim한다.
2. 동일 rename의 중복 전송은 계속 차단한다.
3. 재전송 없이 durable receipt와 external state를 대조해 `APPLIED`, `NOT_APPLIED`,
   또는 좁은 범위의 `UNKNOWN`으로 판정한다.
4. legacy broad claim은 완전한 증거가 있을 때만 canonical transaction으로 재분류 또는
   종결한다.
5. 한 대화의 rename UNKNOWN이 다른 unclaimed target의 node-sync 및 새 #111 E2E를
   막지 않는 회귀가 증명된다.

## 절대 보호 규칙

- `rcc-localbridge-rename-tab594833023-20261015-02`, 그 claim 및
  `BCT-ISSUE111-LIVE-20261015` ACTIVE work를 재전송·직접 삭제·강제 release·takeover
  하지 않는다.
- Chrome 탭, conversation binding, composer draft, role, manager epoch, existing
  UNKNOWN을 진단 중 변경하지 않는다.
- 진행 중인 `background.js` 변경을 덮어쓰지 않는다. worktree와 파일 소유권이
  겹치면 구현하지 말고 근거를 전달한다.
- LIVE deploy, RCC reload, 기존 claim 변경은 exact-head CI, preflight 및 canonical
  recovery 단계 전에는 하지 않는다.

## 확인된 원인

### 과도한 claim 범위

기존 rename UNKNOWN은 `rcc-instance:6174664e1c1b4e6db1d4729c841db3c9`라는
instance-wide claim을 보유한다. 새 Issue #111 E2E의 `node-sync`도 같은 instance-wide
claim을 요구하므로 새 assignment나 browser delivery 전에 충돌한다.

- `src/bct/features/rcc.py`는 rename을 포함한 mutating RCC command에
  `rcc-instance:<instance_id>`를 부여한다.
- `src/bct/features/orchestration.py`의 `node-sync`도 instance-wide resource를
  claim한다. binding 집합을 바꿀 수 있으므로 node-sync의 이 범위는 별도로 검토한다.
- BCT에는 `recover-node-sync`가 있으나 rename용 read-first reconciliation은 없다.

### 결과 조회의 불완전성

`modules/rcc/extension/background.js`는 `chrome.storage.local`의 `operations`,
`results`, `pending` 등 여러 durable bucket을 사용한다. preliminary investigation은
rename completion이 `operations`에 있는데 기존 BCT `result` readback이 다른 결과
경로를 읽어 `found=false`가 될 수 있음을 지적했다. 구현 전에는 이 저장 위치와
record shape를 source·fixture·exact request fingerprint로 재현해 확정한다.

이 문제는 UNKNOWN no-retry 원칙이 아니라 **rename resource 모델과 recovery contract의
결함**이다.

## 1단계 — 읽기 전용 조사

1. original BCT operation receipt, request digest, claimed resource, arguments,
   work/principal ownership을 읽는다.
2. RCC extension의 exact deployed baseline에서 rename의 `operationId`, request
   fingerprint, write bucket, read command, current-title observation 경로를 추적한다.
3. `instance_id`, `session_id`, `tab_id`, `conversation_key`, requested title을
   대조한다. 제목 일치만으로 identity를 증명하지 않는다.
4. Native Host/RCC state 조회가 exact instance/session을 fence하는지, secret/token이
   receipt에 남지 않는지 확인한다.
5. active worktree, existing UNKNOWN, binding, pending draft와의 충돌을 확인한다.

조사 기록에는 사실·파일·테스트·record shape만 남긴다. 대화 전문, token, 동적 값,
전체 로그는 저장하지 않는다.

## 2단계 — 구현 설계

### A. 좁은 canonical resource key

`rename-conversation` resource는 다음과 동등해야 한다.

`rcc-conversation-rename:<instance_id>:<tab_id>:<conversation_key>`

기존 instance/session/tab/conversation/title validation을 유지한다. 같은 exact target의
새 operation은 UNKNOWN 동안 거부한다. 다른 tab/conversation rename과 unclaimed
node-sync는 충돌하지 않는다. 실제 instance-wide state를 바꾸는 명령의 claim은 좁히지
않는다.

### B. read-first rename inspection

새 read-only inspection은 original operation ID와 exact identity를 입력으로 받고 RCC
record와 현재 observed title을 반환한다. rename을 보내거나 tab/binding을 고치지 않는다.

증거로 인정하려면 모두 일치해야 한다.

- original BCT receipt의 request digest와 operation ID
- RCC record의 operation ID와 immutable request fingerprint/digest
- exact instance/session/tab/conversation identity
- requested title과 observed current title
- terminal state 및 observation timestamp

record 누락, bucket/shape 불일치, stale session, identity/title ambiguity는
`unverified`이며 effect를 추정하지 않는다.

### C. canonical reconciliation

별도 reconciliation operation만 original UNKNOWN을 종결할 수 있다. inspection evidence를
만든 뒤 execution 직전에 ownership·request digest·current identity를 재검증한다.

- exact requested title이 증명되면 original `APPLIED`.
- effect absence가 확정되면 original `NOT_APPLIED`.
- 불일치·누락·host failure·ambiguity면 original `UNKNOWN`과 narrow claim 유지.

이 경로는 rename 재전송, title 수정, binding/role 변경을 하지 않는다. 결과와 claim
변경은 하나의 SQLite transaction으로 기록한다.

### D. legacy broad-claim migration

legacy `rcc-instance:<id>` rename claim은 직접 SQL로 수정하지 않는다. original receipt가
exact rename이고 external identity/state와 request digest가 일치하며 같은 broad resource에
의존한 다른 unresolved operation이 없을 때만 canonical transaction에서 terminal 종결 또는
narrow claim 재분류가 가능하다. 그렇지 않으면 broad claim을 보존하고
`REVIEW_REQUIRED` evidence만 남긴다.

## 3단계 — 필수 테스트

### Claim 범위

- 같은 exact target duplicate rename은 한 번만 dispatch.
- 다른 tab/conversation/instance rename key는 분리.
- truly instance-wide command와 node-sync는 적절히 계속 fence.
- rename UNKNOWN이 다른 target의 node-sync/new orchestration session을 막지 않음.
- invalid/missing identity 또는 changed request는 dispatch 전 `NOT_APPLIED`; claim 없음.

### Storage와 inspection

- completion record가 실제 `operations`/`results` 적절한 bucket에서 lookup됨.
- BCT readback이 bucket 역할 차이를 명시적으로 처리함.
- operation ID, fingerprint, identity, title 전부 일치할 때만 terminal evidence 인정.
- wrong operation, stale session, changed conversation, wrong title, missing/malformed
  record, ambiguous title은 UNKNOWN 유지.
- inspection은 추가 `rename-conversation` dispatch를 만들지 않음.

### Reconciliation과 legacy

- confirmed applied → original `APPLIED`, exact claim 처리.
- confirmed no effect → original `NOT_APPLIED`, exact claim 처리.
- ambiguity/error → original UNKNOWN과 claim 유지.
- duplicate reconciliation은 idempotent이며 terminal result를 바꾸지 않음.
- incomplete evidence로 legacy broad claim release/narrowing 금지.
- atomic migration은 unrelated UNKNOWN/claim을 건드리지 않음.

## 4단계 — delivery와 Issue #111 재개

1. focused tests, full `unittest`, `compileall`, `git diff --check`.
2. coherent PR와 exact-head Windows CI.
3. exact tested SHA만 deploy: preflight, rollback proof, runtime health,
   source/runtime manifest identity, RCC payload baseline 확인.
4. historical rename은 read-only inspection 후 complete proof가 있을 때만 canonical
   reconciliation. proof가 없으면 E2E를 강행하지 않는다.
5. fresh unclaimed manager/worker target으로 Issue #111 E2E를 한 번 실행:
   durable worker result → one manager wake → manager ACK/consume → one independently
   authorized next bounded task. polling/status read만으로 성공 처리하지 않는다.

## 담당자 순서

1. 현재 rename implementation과 worktree/file ownership을 확인.
2. storage/fingerprint mismatch를 fixture로 재현·고정.
3. isolated worktree에서 narrow claim → inspection → reconciliation → legacy path 순으로
   구현과 테스트 추가.
4. 진행 중인 rename 담당 변경과 merge-base/diff로 충돌 재확인.
5. CI, exact-SHA deploy, legacy evidence, fresh #111 E2E를 위 순서대로 통과.

이 과제의 결론은 rename을 “성공할 때만 동작”하는 기능이 아니라, 실패·응답 유실·재시작
뒤에도 안전하게 관찰·종결·격리하는 기능으로 만드는 것이다.
