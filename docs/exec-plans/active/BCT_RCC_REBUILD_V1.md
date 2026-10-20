# RCC Rebuild V1 — 연결을 유지한 내부 재구축

상태: `STAGE_0_BASELINE_COMPLETED / STAGE_1_SOURCE_ONLY_COMPLETED / STAGE_2_NOT_STARTED`

## 1. 목표와 비목표

RCC의 외부 연결은 그대로 둔 채 내부 구현만 이해 가능한 작은 모듈로 바꾼다.

RCC가 제공할 기본 기능은 아래 네 가지다.

1. conversation UUID로 정확한 ChatGPT 대화를 찾는다.
2. 그 대화의 생성 중 여부와 입력 가능 상태를 읽는다.
3. 원문 한 건을 정확히 한 번 제출한다.
4. 제출 뒤 새로 생긴 응답 원문을 읽는다.

Manager·Worker는 사람이나 별도 계정이 아니라 Relay의 두 방향 이름이다. 자동 작업 분배,
Manager의 판단, 결과 요약은 RCC Core의 책임이 아니다.

이번 재구축에서 하지 않는 일:

- 새 확장 설치, 확장 ID 변경, 두 번째 unpacked extension 생성
- Chrome profile이나 기존 ChatGPT 대화 교체
- Native Host 이름·등록 위치·실행 파일 경로 변경
- 기존 대화 내용을 다른 저장소로 이관
- ACK 감시, 자동 노드 생성, 자동 작업 분배 같은 새 기능 추가
- 실패한 전송을 구경로로 자동 재시도

## 2. 현재 정상 기준선

2026-10-20 읽기 전용 확인값이다. 구현 직전 다시 측정하며, 값이 달라졌다면 변경 원인을
확인하기 전까지 배포하지 않는다.

| 연결 층 | 현재 기준선 | 재구축 원칙 |
| --- | --- | --- |
| Chrome 확장 | ID `ocbidbaplechjjdacmokhnfbdmgjkphf`, version `1.0.23` | ID 불변 |
| 설치 payload | `D:\ChromeExtensions\RCC\extension` | 경로 불변, 파일만 원자적으로 교체 |
| Native Host 등록 | `com.ai_workspace_relay.host` | 이름과 registry 값 불변 |
| Native Host manifest | `D:\ChromeExtensions\RCC\native\com.ai_workspace_relay.host.json` | 경로와 allowed origin 불변 |
| Native Host executable | `D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe` | 이번 재구축 대상 아님 |
| Manager 대화 | UUID `6ad5afa4-b1e0-83ee-8692-aec4bb51523e` | binding 유지 |
| Worker 대화 | UUID `6ad4bb5d-6624-83ee-b045-e57fdad5120e` | binding 유지 |
| 현재 build | `2026-10-20-simple-relay-return-v0` | 전환 전 rollback 기준 |
| source | clean HEAD `a4e21201c1199f22a856708d14372a34e689ed91` | 구현 시작 기준 |

확인 당시 두 대화는 각각 정확히 하나의 열린 탭으로 해석됐고 `OPEN / IDLE`이었다. source와
installed payload의 핵심 파일 해시도 일치했다. tab/window/session ID는 재시작 때 바뀔 수
있는 관측값이므로 기준선이나 binding으로 저장하지 않는다.

## 3. 끊기면 안 되는 연결의 정의

“연결 유지”는 단순히 확장 아이콘이 보이는 상태가 아니다. 다음 다섯 층을 모두 유지해야
한다.

```text
Chrome extension identity/storage
        ↓
Native Messaging registration/host
        ↓
BCT Core ↔ RCC pipe protocol
        ↓
conversation UUID ↔ 열린 ChatGPT 탭 해석
        ↓
탭 안의 content protocol ↔ 입력/읽기 기능
```

한 층이라도 확인되지 않으면 메시지를 보내지 않는다. `MISSING`, `AMBIGUOUS`, `BUSY`,
`PROTOCOL_MISMATCH`, `UNKNOWN_EFFECT`를 성공처럼 취급하거나 조용히 다른 탭에 보내지 않는다.

## 4. 최종 구조

```text
rcc/
├─ boot/
│  └─ background_loader             고정 진입점과 active build 확인
├─ core/
│  ├─ identity                      URL ↔ conversation UUID, exact tab resolve
│  ├─ state                         OPEN/IDLE/BUSY/MISSING/AMBIGUOUS 관측
│  ├─ conversation                  원문 제출과 새 메시지 읽기
│  └─ transport                     Native Host/BCT 요청·응답 계약
├─ relay/
│  ├─ binding                       Manager UUID ↔ Worker UUID
│  ├─ delivery                      Manager→Worker 원문 한 건
│  ├─ return                        Worker→Manager 새 응답 원문 한 건
│  └─ receipt                       전송 전후 증거와 effect 상태
├─ optional/
│  └─ ...                           제목/창/측정 등 기본 릴레이와 분리
└─ legacy_readonly/
   └─ receipt_reader                과거 기록 조회만 허용
```

모듈 간 데이터 계약은 conversation UUID, 원문, 방향, operation ID, 전송 전후 message count와
상태뿐이다. tab/window/session ID, 대화 제목, 사람 이름은 영속 계약에 넣지 않는다.

Relay binding의 유일한 영속 형태는 다음과 같다.

```json
{
  "schemaVersion": 1,
  "managerConversationId": "UUID",
  "workerConversationId": "UUID"
}
```

## 5. 전환 방식 — 옆에 만들고, 관측하고, 한 경로씩 바꾼다

### 0단계 — 기준선 동결과 복구 묶음

- source HEAD, 설치본 전체 파일 목록·해시, manifest, registry 값, extension storage 중 RCC
  namespace, 두 conversation UUID를 한 묶음으로 기록한다.
- 설치본 전체를 timestamped backup 디렉터리에 보존한다.
- 복구 스크립트는 정확한 설치 경로에 정확한 파일만 되돌리며 확장 ID/registry/storage는
  건드리지 않는다. 첫 rehearsal은 LIVE가 아닌 임시 복원 디렉터리에서 해시 비교로 수행한다.
- 현재 Simple Relay V0로 read-only state를 확인한다. 이 단계에서는 메시지를 보내지 않는다.

통과 조건: 백업을 임시 디렉터리에 복원한 결과가 기준선 파일과 일치하고, LIVE identity 값은
작업 전후 그대로임이 읽기 전용 검사로 확인된다.

### 1단계 — 새 Core를 source에만 분리

- 현재 실행 코드에서 UUID 해석, 상태 관측, 제출, 읽기를 순수 모듈로 추출한다.
- 기존 selector와 wire protocol의 외부 동작은 그대로 둔다.
- 단위 테스트와 기록된 DOM fixture로 `MISSING / AMBIGUOUS / BUSY / IDLE` 및 원문 보존을
  검증한다.
- installed payload와 LIVE loader는 변경하지 않는다.

통과 조건: 테스트가 통과하고 LIVE 파일 해시와 build ID가 0단계 값 그대로다.

### 2단계 — 비활성 후보 파일 배치와 읽기 전용 Shadow

- 새 파일을 기존 설치 경로에 추가하되 loader/manifest에서 실행하지 않는다.
- 해시 검증 뒤 loader가 새 Core의 **관측 기능만** 실행하도록 전환한다.
- 기존 경로와 새 경로가 같은 UUID, 상태, message count를 내는지 비교한다.
- Shadow는 composer 입력, 클릭, 탭 이동, storage migration을 절대 수행하지 않는다.

통과 조건: 두 경로의 읽기 결과가 반복해서 일치하고 Native Host 및 두 binding 상태가 유지된다.
불일치하면 기존 loader로 즉시 파일 복원하며 메시지 수락시험은 하지 않는다.

### 3단계 — content protocol 호환성 전환

- background와 content 사이의 현재 메시지 계약을 먼저 고정 테스트로 만든다.
- 새 background는 기존 content receiver와 호환되어야 한다. 기존 열린 탭을 갑자기 새
  protocol만 요구하도록 만들지 않는다.
- 새 content가 꼭 필요하면 대상 대화가 `IDLE`이고 composer가 비어 있음을 확인한 뒤에만
  해당 탭을 한 번 새로 고친다. 새로 고침 전후 conversation UUID가 같아야 한다.
- protocol 버전이 맞지 않으면 `PROTOCOL_MISMATCH`로 멈추고 전송하지 않는다.

통과 조건: 기존 열린 탭을 유지한 read-only 확인과, 필요한 경우 안전한 탭 새로 고침 뒤의
UUID 동일성 확인이 모두 통과한다.

### 4단계 — Manager→Worker 단일 전송 전환

- active engine을 한 번에 하나만 선택한다. 새 delivery와 legacy delivery를 동시에 실행할 수
  없게 한다.
- 전송 직전에 source/target UUID, target `IDLE`, composer empty, pre-send message count를
  기록한다.
- 사용자가 승인한 고정 원문 한 건만 Worker에 보낸다.
- `SUBMITTED`와 실제 새 user turn의 원문 일치를 확인한다.
- 결과가 `UNKNOWN`이면 같은 요청을 legacy로 재전송하지 않는다.

통과 조건: 정확히 한 user turn만 추가되고 원문이 byte-equivalent하며 binding이 바뀌지 않는다.

### 5단계 — Worker→Manager 반환 전환

- 4단계 receipt의 pre-send assistant count 이후에 생성된 Worker 응답만 반환 후보로 인정한다.
- Worker가 `IDLE`이 되고 새 assistant turn이 정확히 식별될 때만 그 전문을 Manager에 한 번
  제출한다.
- 요약, 접두 문구 삽입, 전달서 재작성은 RCC가 하지 않는다.
- 반환 결과가 불확실하면 재전송하지 않는다.

통과 조건: Worker의 새 assistant 원문이 Manager의 새 user turn 한 건과 일치하고 양쪽 UUID가
유지된다.

### 6단계 — Legacy 변경 경로 차단

- 새 Relay 왕복이 안정된 뒤 legacy의 send/register/create/queue/orchestration 진입을
  비활성화한다.
- 과거 receipt와 결과 조회는 `legacy_readonly`에서 계속 가능하게 둔다.
- 숨은 timer, startup hook, 자동 ACK 정책이 메시지를 보낼 수 없는지 검사한다.

통과 조건: 허용된 새 Relay 이외의 변경 명령이 명시적으로 거부되고, 기존 기록 조회는 된다.

### 7단계 — 정리와 제거

- 안정화 기간 동안 연결 상태, protocol mismatch, UNKNOWN effect, 중복 turn이 없는지 확인한다.
- legacy 파일의 실제 호출자가 0임을 정적 검색과 runtime 계측으로 모두 확인한다.
- 그 뒤에만 legacy 실행 코드를 제거한다. 삭제 전 exact backup과 Git history를 보존한다.
- active 계획을 completed로 옮기고 BOOTSTRAP/REGISTRY/HANDOFF에 최종 구조와 복구법을 반영한다.

## 6. 배포 단위와 원자적 전환

각 단계는 하나의 독립 commit과 하나의 배포 영수증을 가진다. 배포 순서는 고정한다.

1. source test
2. GitHub main 반영과 Actions/Runner 확인
3. LIVE exact backup
4. 실행되지 않는 후보 파일 먼저 복사
5. 파일 해시 확인
6. 마지막에 loader/manifest의 최소 변경으로 active build 전환
7. same-ID extension reload
8. Native Host state와 build ID 확인
9. 두 conversation UUID의 exact resolve 확인
10. read-only acceptance 후 필요한 단계에서만 단일 메시지 acceptance

파일 복사 도중의 반쪽 상태가 active가 되지 않도록 loader 전환을 항상 마지막에 한다. 새 build가
시작되지 않으면 loader와 payload를 직전 backup으로 되돌린다.

## 7. 중단 조건과 복구 규칙

다음 중 하나라도 발생하면 즉시 그 단계에서 멈춘다.

- extension ID, installed path, Native Host name/registry/path 중 하나가 기준선과 다름
- 두 conversation UUID 중 하나가 `MISSING` 또는 `AMBIGUOUS`
- 대상이 `BUSY`이거나 composer가 비어 있지 않음
- background/content protocol version 불일치
- source/main/installed 파일 해시의 설명되지 않은 차이
- 이전 operation의 effect가 `UNKNOWN`
- 예상보다 user/assistant turn이 많이 증가함

복구는 “다른 경로로 다시 보내기”가 아니다. 직전 exact-file backup을 같은 설치 경로에 복원하고,
같은 확장 ID로 재로드한 뒤 read-only 상태만 다시 확인한다. 이미 보냈을 가능성이 있는 메시지는
효과가 확정될 때까지 절대 재전송하지 않는다.

## 8. 사용자에게 보이는 상태

기본 상태 화면은 내부 ID를 요구하지 않고 다음만 보여준다.

```text
RCC 연결: 정상 / 차단
확장: 연결됨 (기존 ID·경로)
Native Host: 연결됨
Manager 대화: CONNECTED / MISSING / AMBIGUOUS / BUSY
Worker 대화: CONNECTED / MISSING / AMBIGUOUS / BUSY
실행 엔진: SIMPLE_RELAY_V0 / NEW_CORE_SHADOW / NEW_CORE
미확정 전송 효과: 0건
```

tab/window/session ID와 상세 해시는 진단 상세에서만 보여준다. 사용자가 경로와 내부 ID를 기억하거나
직접 조합하게 하지 않는다.

## 9. 완료 정의

재구축 완료는 파일을 나눈 시점이 아니라 아래가 모두 충족된 시점이다.

- 기존 확장 ID, 설치 경로, Native Host 등록, Chrome storage, 두 conversation UUID가 유지됨
- Core와 Relay의 모듈 경계가 코드와 테스트에서 확인됨
- Manager→Worker 한 건과 Worker→Manager 한 건이 원문 그대로 정확히 한 번 전달됨
- 실패·UNKNOWN에서 자동 재전송이나 잘못된 탭 대체가 없음
- legacy 변경 경로는 호출 불가하고 과거 기록은 읽을 수 있음
- source main, Actions/Runner, installed payload, runtime build가 동일한 릴리스를 가리킴
- 복구 절차가 실제 backup을 이용한 rehearsal로 검증됨

## 10. 다음 실행 단위

0단계의 실제 결과는
`docs/exec-plans/active/BCT_RCC_REBUILD_V1_STAGE0_BASELINE_20261020.md`에 고정했다.

1단계의 실제 결과는
`docs/exec-plans/active/BCT_RCC_REBUILD_V1_STAGE1_SOURCE_CORE_20261020.md`에 고정했다.

다음 단계는 2단계 read-only Shadow 후보 배치다. 이 단계부터는 installed payload 변경과 same-ID
extension reload가 필요하므로, 현재 작업의 source-only 제약 아래에서는 시작하지 않는다.
