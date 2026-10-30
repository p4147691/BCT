# RCC 처음 사용하기

일반 ChatGPT 대화가 RCC로 다른 ChatGPT 탭에 처음 메시지를 보낼 때의 기본 규칙이다.

## 먼저 기억할 한 가지

**새 메시지 제출의 단일 공개 진입점은 `send-message`다.** 내부적으로 기존 탭은 `send-to-tab`, BCT 생성 탭은 `send-to-created-tab` 계약으로 연결된다.

대화 UUID가 이미 있든, 아직 빈 새 탭이든 명령은 같다. 빈 새 탭은
`conversation_key`만 빈 문자열(`""`)이다.

```text
instance_id + session_id + tab_id + window_id + conversation_key + text
```

- `instance_id`: 현재 RCC 인스턴스
- `session_id`: 현재 RCC 연결 세션
- `tab_id`: Chrome 탭 식별자
- `window_id`: 그 탭을 관찰했을 때의 Chrome 창 식별자
- `conversation_key`: ChatGPT 대화 UUID. 빈 새 탭은 `""`.
- `text`: 보낼 원문

`state` 또는 `windows-list`로 이 값을 먼저 읽고, 같은 관찰 결과에서 받은 값만
사용한다. 추측하거나 이전 세션의 값을 재사용하지 않는다.

## 가장 흔한 두 경우

| 대상 | 호출 |
| --- | --- |
| 이미 대화가 있는 탭 | `send-message` + 해당 UUID |
| 기존 빈 ChatGPT 탭 | `send-message` + `conversation_key: ""` |

빈 탭의 첫 전송이 확인되면 영수증에 새 `conversation_key`가 기록된다. 이후 후속
메시지는 그 UUID와 같은 `tab_id`를 사용해 다시 `send-message`로 보낸다.

## 지속 작업으로 이어갈 때: `node-continue`

`node-continue`는 빈 탭을 찾거나 첫 메시지를 보내는 명령이 아니다. 위 첫 전송으로
UUID를 확인한 뒤 해당 탭을 대화망의 노드로 결합했을 때, **같은 노드가 자기 작업을
여러 차례 이어 가게 하는 조합 명령**이다.

1. `send-message`로 최초 지시를 보내고 UUID를 영수증에서 확인한다.
2. 해당 탭을 정확한 orchestration session의 node로 결합한다.
3. `node-continue`의 `phase: "open"`으로 최초 연속 작업을 연다. 이때만
   `max_self_turns`와 `total_timeout_s` 예산을 정한다.
4. 같은 노드는 응답 완료(idle) 뒤 `phase: "continue"`로 자기 자신에게 다음 지시를
   보낼 수 있다. 예산은 중간에 늘리거나 바꾸지 않는다.
5. 작업이 끝나면 `phase: "close"`로 닫는다. `close`에는 전송할 `text`가 없다.

`node-continue`에는 탭 UUID를 직접 넣지 않는다. `orchestration_session_id`와
`node_id`로 현재 결합을 해석하므로, 탭·세션·대화가 바뀌면 실패하고 다른 탭으로
추측 전송하지 않는다. 단순한 한 번의 자기 메시지는 같은 결합을 쓰는
`send-to-self`를 사용한다.

## 새 탭을 BCT가 직접 만들 때만

`create-chat-window` 또는 `create-chat-tab`으로 BCT가 새 탭을 만들었다면, 반환된
생성 영수증을 근거로 `send-message`에 `create_operation_id`를 전달한다. 사용자가 이미 열어 둔 빈 ChatGPT 탭에는 이 값을
만들거나 요구하지 않는다.

## 새 호출에서 쓰지 않을 명령

- `create-and-send`: 창에 새 탭을 만들고 첫 메시지를 보내는 이전 조합 명령이다.
  기존 빈 탭의 `window_id`를 넣는 용도가 아니다.
- generic `send`: 대상이 탭·세션·대화로 고정되지 않는 호환용 명령이다.

둘은 기존 영수증·호출 호환을 위해 남아 있지만, 일반 ChatGPT 노드 전송의 새 호출에는
쓰지 않는다.

## 결과가 불명확할 때

`UNKNOWN`은 실패나 성공으로 바꾸지 않는다. 같은 전송을 새 operation ID로 다시
보내지 말고, 원래 `relay_id`로 `result`를 조회해 영수증을 확인한다.
