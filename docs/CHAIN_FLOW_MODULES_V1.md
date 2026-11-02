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
| 범위 목록 읽기 | 탭이 닫혀도 남아 있는 활성/종결 대화망 범위와 역할 수를 읽는다 | Check Network 내부 원시 읽기 |
| 역할 표지 | 한 노드가 이번에 어떤 창구 역할인지 기록한다 | 현재 노드 정보 설정 경로 |
| 방향 기록 | A가 보고를 읽고 다음 판단을 남긴다 | `bct_set_chain_direction` / `bct_get_chain_direction` |
| 정확한 메시지 전달 | 이미 고른 정확한 대상에게 한 메시지를 보낸다 | `bct_send_message` |
| 감시·alarm | 대상 X의 응답 완료와 입력 가능 상태를 확인한다 | Delayed Send 내부 원시 부품 |
| 예약 취소 | 아직 기다리는 정확한 반복 하나를 멈춘다 | `bct_delayed_send_cancel` |

역할 표지는 권한이 아니다. `감독관`은 메인 통합 작업을 한 창구에 모으고 싶을
때 붙이는 이름이며, 없으면 A가 기존 노드에 붙이거나 새 노드를 준비할 수 있다.

## 부분 레시피

```text
대화망 확인·준비 (전체 Chain Message의 고정 첫 블록, 읽기 부분 레시피)
  A → bct_check_network
      현재 열린 노드 + 저장된 범위 목록 + 역할 상태를 함께 읽음
      이전 활성 범위: 이어가기 / 다른 범위와 병합 / 새 범위 중 A가 판단
      supervisor=PRESENT: 원래 작업 계획으로 진행
      supervisor=MISSING: A가 기존 노드 하나를 고르거나 새 노드를 준비
        → 감독관 초기 지시를 한 번 보냄
        → 대화 UUID 확인 뒤 supervisor 역할을 기록
        → bct_check_network 재확인
      supervisor=MULTIPLE: A가 어느 하나를 정리할지 판단
  → 필요하면 bct_set_network(node-info-set)으로
      대화망·노드 이름·역할·메모·담당 작업을 함께 기록
  → bct_check_network로 다시 확인

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

`대화망 확인·준비`은 대화망을 꼭 새로 만드는 단계가 아니다. 같은 설정 경로로
노드 이름·역할·메모·담당 작업도 함께 다루는 준비 블록이다. 모든 Chain Message는
`bct_check_network`에서 `supervisor` 역할이 정확히 하나인지 먼저 본다. 없으면
A가 기존 노드를 고르거나 새 노드를 준비해 역할을 기록하고 다시 확인한다.
둘 이상이면 자동 삭제하지 않고 A가 정리 방향을 고른다. 이 확인은 레시피의
준비 규칙이며, BCT가 감독관을 자동 선택·생성하거나 체인 전송을 몰래 막는
강제 권한 규칙은 아니다.

`bct_check_network`는 원시 명령 하나가 아니라, 위의 현재 보기·범위 목록·역할
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
→ bct_set_network(node-info-set)으로 supervisor 역할·이름·메모를 기록
→ bct_check_network에서 supervisor=PRESENT 확인
```

초기 지시는 빈 창을 실제 노드로 묶기 위한 한 번의 부트스트랩이며, 이후의
프로젝트 작업 지시와는 구분한다. BCT는 그 지시 내용을 스스로 쓰거나 보내지
않는다.

역할만 기록할 때는 `bct_set_network(operation="node-info-set")`으로 한 노드의
`role_tags`에 `supervisor`를 넣는다. 실제 대화망 구성까지 필요할 때만 같은
설정 경로의 대화망 생성·소속 설정 단계를 이어 붙인다. 이 설정은 대상 선택을
도울 뿐, 권한을 만들거나 메시지를 보내지 않는다.

`체인 시작`은 현재 `bct_chain_message`가 제공하는 부분 레시피다. 이 명령의
정식 인수는 `target_tab_id`, `target_window_id`, `target_conversation_key`와
`origin_conversation_key`다. 기존 `worker_` / `manager_` 인수는 이전 호출을
깨지 않도록 남긴 호환 별칭이다. 개념상 Target은 **이번 정확한 대상 X**를
뜻한다. X가 B든 C든 감독관이든 같은 경로를 쓴다.

## 전체 레시피

### 전체 Chain Message 레시피

```text
현재 보기
→ 대화망 확인·준비 (bct_check_network는 항상 실행)
→ 실행 전 점검
→ A의 작업 방향 정리
→ 대상 X 고르기
→ 체인 시작: A → X
→ X 내부 반복 또는 X → A 반환
```

여기서 `bct_chain_message`는 마지막의 **체인 시작** 부분 레시피다. 전체
Chain Message 레시피가 대화망 준비까지 포함한다고 해서, 전송 부품 하나가
대화망을 몰래 바꾸는 것은 아니다.

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
