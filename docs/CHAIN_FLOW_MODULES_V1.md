# 1:1 Chain Flow Modules V1

## 한 문장

모든 1:1 체인은 **A가 선택한 대상 X에게 일을 맡기고, X가 한 번에 끝내거나
XX 반복 뒤 XA로 결과를 돌려주는 흐름**이다.

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
| 역할 표지 | 한 노드가 이번에 어떤 창구 역할인지 기록한다 | 현재 노드 정보 설정 경로 |
| 방향 기록 | A가 보고를 읽고 다음 판단을 남긴다 | `bct_set_chain_direction` / `bct_get_chain_direction` |
| 정확한 메시지 전달 | 이미 고른 정확한 대상에게 한 메시지를 보낸다 | `bct_send_message` |
| 감시·alarm | 대상 X의 응답 완료와 입력 가능 상태를 확인한다 | Delayed Send 내부 원시 부품 |
| 예약 취소 | 아직 기다리는 정확한 반복 하나를 멈춘다 | `bct_delayed_send_cancel` |

역할 표지는 권한이 아니다. `감독관`은 메인 통합 작업을 한 창구에 모으고 싶을
때 붙이는 이름이며, 없으면 A가 기존 노드에 붙이거나 새 노드를 준비할 수 있다.

## 부분 레시피

```text
대상 고르기
  현재 보기
  → 필요한 역할의 후보를 본다
  → A가 이번 작업을 맡길 정확한 X를 고른다

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

`체인 시작`은 현재 `bct_chain_message`가 제공하는 부분 레시피다. 이 명령의
기존 내부 인수 이름에 `worker`가 남아 있어도, 개념상 Worker는 **이번 정확한
대상 X**를 뜻한다. X가 B든 C든 감독관이든 같은 경로를 쓴다.

## 전체 레시피

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
- 1:N 분배·점유·결과 수집은 이 1:1 모듈 위에 나중에 별도 레시피로 만든다.
