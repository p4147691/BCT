# Chain Flow Modules V1 — 대상별 전송 부품

> 현재 원시 부품과 구현 경계를 설명하는 문서다. 사용자에게 보이는 전체
> 작업 흐름과 A 전체 계획/B 실행계획의 구분은
> [Chain Message Recipe V2](CHAIN_MESSAGE_RECIPE_V2.md)를 정본으로 삼는다.
>
> 전체 입구 `bct_chain_message`는 현재 정보 → Set Direction 질문/판단 → 망 준비 →
> A가 정한 여러 대상의 각각의 전송을 조합한다. 아래 1:1은 전체 레시피의 제한이
> 아니라 **대상 하나마다 재사용하는 전송·감시 계약**이다.

## 한 문장

모든 1:1 체인은 **A가 전체 방향과 전체 계획을 정해 대상 X에게 일을 맡기고,
X가 자기 실행계획을 작성한 뒤 한 번에 끝내거나 XX 반복 뒤 XA로 결과를
돌려주는 흐름**이다.

`B`, `C`, `감독관`은 X의 이름 또는 역할일 뿐, 다른 종류의 체인이 아니다.

```text
A → X
X가 끝남       → X → A
X가 더 필요함  → X → X → … → X → A
```

## 원시 부품

| 부품 | 하는 일 | 현재 진입점 |
| --- | --- | --- |
| 현재 보기 | 열린 노드·역할·대화 UUID·RCC·경고를 읽는다 | `bct_status(scope="bct")` |
| 범위 목록 읽기 | 탭이 닫혀도 남아 있는 활성/종결 대화망 범위와 역할 수를 읽는다 | Check Conversation Network 내부 원시 읽기 |
| 역할 표지 | 한 노드가 이번에 어떤 창구 역할인지 기록한다 | 현재 노드 정보 설정 경로 |
| 방향 정리 | 현재 정보와 내부 질문을 읽고 A가 다음 판단과 대상별 지시를 남긴다 | `bct_set_direction` / `bct_get_direction` |
| 정확한 메시지 전달 | 이미 고른 정확한 대상에게 한 메시지를 보낸다 | `bct_send_message` |
| 감시·alarm | 대상 X의 응답 완료와 입력 가능 상태를 확인한다 | Delayed Send 내부 원시 부품 |
| 예약 취소 | 아직 기다리는 정확한 반복 하나를 멈춘다 | `bct_delayed_send_cancel` |

역할 표지는 권한이 아니다. `감독관`은 메인 통합 작업을 한 창구에 모으고 싶을
때 붙이는 이름이며, 없으면 A가 기존 노드에 붙이거나 새 노드를 준비할 수 있다.

## 부분 레시피

```text
대화망 확인·준비 (조회 뒤 A의 Direction 판단을 거쳐 설정)
  A → bct_check_conversation_network
      현재 열린 노드 + 저장된 범위 목록 + 역할 상태를 함께 읽음
      이전 활성 범위: 이어가기 / 다른 범위와 병합 / 새 범위 중 A가 판단
      supervisor=PRESENT: 원래 작업 계획으로 진행
      supervisor=MISSING: A가 기존 노드 하나를 고르거나 새 노드를 준비
        → 감독관 초기 지시를 한 번 보냄
        → 대화 UUID 확인 뒤 supervisor 역할을 기록
        → bct_check_conversation_network 재확인
      supervisor=MULTIPLE: A가 어느 하나를 정리할지 판단
  → 필요하면 bct_set_conversation_network(node-info-set)으로
      대화망·노드 이름·역할·메모·담당 작업을 함께 기록
  → bct_check_conversation_network로 다시 확인

대상 고르기
  현재 보기
  → 필요한 역할의 후보를 본다
  → A가 이번 작업을 맡길 정확한 X를 고른다

통합 경로 고르기
  A가 변경 대상·외부 효과·rollback을 확인
  → LOCAL_FIRST
      로컬 검증 → 로컬 main → 영향 대상 LIVE E2E → GitHub 게시·CI 감사
  → GUARDED_CI_FIRST
      로컬 검증 → exact 후보 CI·리뷰 → 로컬 main → LIVE E2E → GitHub 게시·main CI
  → 분류 불가
      GUARDED_CI_FIRST로 유지하고 불명확한 경계를 보고

체인 시작
  A의 지시문 + 정확한 X
  → 감시 선준비
  → A → X 한 번 전송
  → X 응답 감시 시작

내부 반복
  X의 이전 판단=계속
  → 감시 조건 충족
  → alarm
  → X → X
  → 다음 응답 감시

반환
  X의 이전 판단=반환
  → 감시 조건 충족
  → alarm
  → X → A 결과 보고

방향 정리
  A가 결과 보고를 읽음
  → COMPLETE / NEW_TASK / ASK_USER / HOLD 기록

종료
  A의 판단=COMPLETE
  → 새 X를 만들거나 메시지를 보내지 않음
```

`대화망 확인·준비`은 대화망을 꼭 새로 만드는 단계가 아니다. 같은 설정 경로로
노드 이름·역할·메모·담당 작업도 함께 다루는 준비 블록이다. 모든 Chain Message는
`bct_check_conversation_network`에서 `supervisor` 역할이 정확히 하나인지 먼저 본다. 없으면
A가 기존 노드를 고르거나 새 노드를 준비해 역할을 기록하고 다시 확인한다.
둘 이상이면 A가 정리 방향을 고른다. BCT가 감독관을 스스로 선택하지 않는다.
질문 기반 Direction의 전송은 A가 기록한 유일한 Supervisor와 현재 역할·소속이
일치하는지 검사한다. 불일치는 `NETWORK_PREPARATION_REQUIRED`로 명시한다.

`bct_check_conversation_network`는 원시 명령 하나가 아니라, 위의 현재 보기·범위 목록·역할
상태·권한 있는 프로젝트 맥락 요약을 조립한 **읽기 부분 레시피**다. 활성 범위는
그 소속 탭이나 Manager/Worker가 닫혀도 사라지지 않는다. A가 명시적으로 종결
처리하기 전까지 다음 작업은 그 범위를 이어가거나, 다른 활성 범위와 병합할지
판단할 수 있다. 대화 본문을 몰래 보관하는 것은 아니며, 프로젝트 맥락의 본문은
기존 Project Context 원장에서 Work 권한으로 읽는다.

이 준비 단계는 감독관에게 곧바로 병합·배포 일을 맡기는 단계가 아니다. 예를
들어 원래 작업이 A→B라면, 감독관이 없을 때의 실제 순서는 `감독관 C 초기화 →
C 역할 기록 → A→B`다. C는 이후 B의 결과가 메인 병합·배포·LIVE E2E로 이어질
때만 그 통합 체인의 대상이 된다.

### 깨끗한 새 감독관 노드의 부트스트랩

오래 누적된 대화의 맥락·화면 반응이 부담이라면 A는 기존 노드를 재사용하지
않고 `create-chat-window`로 새 창을 만들 수 있다. 이 시점의 새 탭은 아직
대화 UUID가 없는 `PENDING_UNBOUND` 후보일 뿐, 노드 정보나 역할을 기록할 수
있는 노드는 아니다. 정확한 순서는 다음과 같다.

```text
새 Chat 창 생성
→ 첫 감독관 초기 지시를 정확히 한 번 보냄
→ ChatGPT가 대화 UUID를 생성하고 RCC가 이를 확인
→ bct_set_conversation_network(node-info-set)으로 supervisor 역할·이름·메모를 기록
→ bct_check_conversation_network에서 supervisor=PRESENT 확인
```

초기 지시는 빈 창을 실제 노드로 묶기 위한 한 번의 부트스트랩이며, 이후의
프로젝트 작업 지시와는 구분한다. BCT는 그 지시 내용을 스스로 쓰거나 보내지
않는다.

역할만 기록할 때는 `bct_set_conversation_network(operation="node-info-set")`으로 한 노드의
`role_tags`에 `supervisor`를 넣는다. 실제 대화망 구성까지 필요할 때만 같은
설정 경로의 대화망 생성·소속 설정 단계를 이어 붙인다. 이 설정은 대상 선택을
도울 뿐, 권한을 만들거나 메시지를 보내지 않는다.

`체인 시작`은 `bct_chain_message` 내부에서 대상마다 재사용하는 부분 레시피다.
기존 정확 대상 호출의
정식 인수는 `target_tab_id`, `target_window_id`, `target_conversation_key`와
`origin_conversation_key`다. 기존 `worker_` / `manager_` 인수는 이전 호출을
깨지 않도록 남긴 호환 별칭이다. 개념상 Target은 **이번 정확한 대상 X**를
뜻한다. X가 B든 C든 감독관이든 같은 경로를 쓴다.

### Chain Message 전송 전 권한·응답 출력 계약 (선택형)

`bct_chain_message(action="preflight", ...)`는 실제 `start`에 사용할 **같은 Work,
Task/Operation ID, 정확한 대상·발신자 식별자와 지시문**을 입력받아 기존
Work의 `browser` 작업 권한 및 출력 계약을 점검한다. 이 호출은
**읽기 전용**이다. Chain Direction 연결 상태를 예약하거나 감시를 선등록하거나
메시지를 보내지 않으며 Work에 작업 권한을 자동 추가하지 않는다.

- `READY`: 현재 Work가 ACTIVE이고 소유자가 맞으며 `browser` 권한을
  이미 보유한다. 반환하는 `outgoing_instruction_sha256`은 그대로 전송할
  최종 UTF-8 문자열의 SHA-256이다. 실제 RCC 창·탭 상태와 이후 외부 전송
  성공을 증명하는 것은 아니므로 기존 전송 사전 검사/Operation 영수증은 계속 필요하다.
- `BLOCKED` + `CHAIN_MESSAGE_BROWSER_ACTION_REQUIRED`: 해당 Work에
  브라우저 권한이 없다. 기존 Work는 변경하지 않는다. 호출자가 별도 승인된
  적합한 Work를 선택·생성한 뒤에만 재검토한다.
- `INVALID_REQUEST`: 대상/지시문·출력 계약이 부적합하다. 어떤 외부
  Operation도 예약하지 않는다.
- `continuation_output_contract="none"` (기본값): 종전 지시문을 바이트
  그대로 보존하며 기존 Chain/Delayed Send 응답 정책을 변경하지 않는다.
- `continuation_output_contract="explicit-next-task-v1"` (선택): Worker가
  **스스로 결정한** SELF 또는 MANAGER 경로를 실제 응답 마지막 줄에
  `NEXT TASK — SELF: 구체적 다음 작업` 또는
  `NEXT TASK — MANAGER: 구체적 검토/수용 작업`으로 명시하도록 요청하는
  짧은 고정 문구를 덧붙인다. 이 확장된 **동일한 원문**이 Delayed Send
  선예약의 `planned_send_text`와 단일 `send-message`의 `text`가 된다.
  연결된 Chain Direction의 A 작성 원본 `direction_text`는 수정하지 않는다.
  기존 정확 대상 호출에서는 명시적으로 선택해야 붙는다. 질문 기반 Direction을
  사용하는 전체 입구는 대상별 지시에 이 계약을 함께 붙인다.

Worker가 지시를 따르지 않아 마커를 누락하거나, 서로 충돌하거나, 구체적인
후속 지시가 없다면 기존 `extract_next_instruction`과 durable watch가
**임의의 SELF/MANAGER 후속 작업을 생성하지 않는다**.
응답은 정확한 응답 턴에 결합된 채 `MANAGER_DECISION_REQUIRED` /
`NEXT_INSTRUCTION_UNAVAILABLE`로 A의 검토를 기다린다. 불확실한 전송의
자동 재전송도 없다.

응답 해석과 결정 기록까지 끝났지만 후속 SELF/MANAGER 전송이 RCC에서
확정적으로 `NOT_APPLIED`이면, 이는 효과가 불확실한 `UNKNOWN`이 아니다.
watch는 `MANAGER_DECISION_REQUIRED` / `CONTINUATION_SEND_NOT_APPLIED`로
종료하고 정확한 응답·결정·미적용 alarm을 보존한다. BCT는 재전송하지 않으며
A가 보존된 응답을 검토해 새 메시지를 작성한다. 외부 효과가 실제로
불명확한 경우에만 기존 `UNKNOWN` 경계를 유지한다.

## 전체 레시피

### 전체 Chain Message 레시피

```text
현재 보기 + 저장된 대화망 비교
→ Set Direction 질문을 토대로 A 판단: 방향·통합 경로·대상별 지시
→ 필요한 망·역할 준비
→ 현재 역할·대상 재확인
→ 각 대상마다 체인 시작: A → X
→ X 구체적 Execute Plan·실행 → XX 또는 XA
→ 반환 뒤 A가 전체 입구부터 재판단
```

`bct_chain_message`는 위 전체 흐름의 입구이며, 내부에서 대상별 **체인 시작**
부분을 재사용한다. 망 변경은 A가 Direction에 명시한 기존 setter 인수만 적용하고,
변경 영수증과 각 전송 영수증은 따로 보존한다.

통합 경로 역시 `bct_chain_message`가 자동으로 정하지 않는다. A가 현재 공통
운영 정책과 실제 영향 범위를 읽고 방향에 기록하며, X는 실행계획과 반환 보고에
선택 경로·선택 이유·각 단계의 증거를 남긴다. 작업 도중 외부 효과나 rollback
불확실성이 새로 발견되면 `LOCAL_FIRST`를 계속 밀어붙이지 않고 공유 효과 전에
멈춰 `GUARDED_CI_FIRST`로 올려 다시 계획한다.

### 한 번에 끝나는 A-X-A

```text
A → X
X 처리 완료
X → A
A → Chain Direction(COMPLETE)
```

### X 내부 반복이 있는 A-X-A

```text
A → X
X → X → X → …
X → A
A → Chain Direction(COMPLETE 또는 NEW_TASK)
```

### 두 번 맡기는 A-X-A-Y-A

```text
A → X
X → A
A → Chain Direction(NEW_TASK)
A → Y
Y → Y → …
Y → A
A → Chain Direction(COMPLETE)
```

여기서 Y는 X와 같은 노드여도, 다른 기존 노드여도, `감독관` 역할이 붙은 C여도
된다. A가 새 체인을 시작하기 전 현재 보기를 읽고 고른다.

## 멈춤의 의미

```text
아직 X의 다음 반복을 기다림
  → 정확한 Delayed Send 취소 가능

X에게 이미 지시문이 도착함
  → 예약 취소만으로 그 지시를 되돌릴 수 없음
  → 필요하면 A가 새 중지·정리 지시를 작성하고 결과를 확인
```

## 하지 않는 것

- BCT는 X가 누구여야 하는지 판단하지 않는다.
- `감독관` 역할은 병합·배포·E2E 권한을 뜻하지 않는다.
- Chain Direction은 A의 다음 지시문을 자동으로 쓰거나 전송하지 않는다.
- 대상별 1:1 계약은 전체 Chain의 1:N 분배에 재사용된다. 여러 결과의 우선순위·
  의존성·통합 판단을 BCT가 대신하지 않는다. A가 각 반환을 읽고 다음 회차를 결정한다.
