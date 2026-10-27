# 프로젝트 맥락과 노드 연속 V1

## 목적

새 ChatGPT 노드가 과거 전문을 전부 읽지 않아도 같은 프로젝트를 이어간다.
원문 증거와 현재 맥락을 구분하며, B의 자기 연속은 명시된 예산 안에서만 허용한다.

## 기록 계층

1. 원본 근거: Delivery 영수증·응답 원문·선택된 화면 스냅샷. 기본으로 모두 읽지 않는다.
2. 중앙 프로젝트 맥락: 프로젝트마다 현재본 하나. 목표, 범위, 구조/경로 지도, 확정 결정,
   활성 작업, 위험, 다음 우선순위와 근거 링크만 적는다.
3. 작업 일지: `프로젝트 + Work`마다 하나. 물리 노드나 탭에 묶지 않는다. 담당 노드가
   바뀌어도 같은 일지를 이어 쓴다. 현재 목표, 확인 사실, 결과, 차단 사유, 다음 재개점만 적는다.

중앙 맥락은 다른 요약을 복제하지 않는다. 원문이나 상세 결과가 필요하면 `links`의 근거를 연다.
과거 리비전은 검증용으로 남지만, 기본 열람 대상은 현재본 하나다.

## 새 노드가 받는 맥락

기본 묶음은 `중앙 프로젝트 맥락 + 할당 Work 일지 + 연결 Work의 제목/상태/결론`이다.
다른 Work 일지와 대화 원문은 필요할 때만 읽는다. BCT는 이 기록만으로 ChatGPT가
자동으로 알게 만들지 않는다. A가 새 노드에 전송할 메시지에 이 묶음을 포함하거나,
노드가 `project_context` 조회를 호출해야 한다.

## MCP 기록 명령

`project_context` capability의 `record`는 기존 Project Memory V1 형식이다.

- `central-get`, `central-save`: 프로젝트 중앙 현재본
- `worklog-get`, `worklog-save`: `journal_work_id`가 붙은 작업 일지
- `overview`: 중앙 현재본과 작업 일지 현재본 목록

저장은 `expected_revision` CAS를 요구한다. 작업 일지는 `links`에 정확한
`{"type":"bct_work","id":"<journal_work_id>"}`를 포함해야 한다.
이 기능은 브라우저 본문을 캡처하거나 메시지를 보내지 않는다.

## B -> B 연속

`send-to-self`는 `orchestration_session_id + node_id`로 현재 RCC 결합을 해석한다.
호출자가 탭·창·세션·대화 UUID를 추측해서 넣지 않는다. 대상 탭이 생성 중이면
`idle_timeout_s` 동안 정확한 같은 탭이 idle이 될 때까지 기다린다. 대상이 바뀌면 전송하지 않는다.

`node-continue`는 그 전송을 예산화한 조합 명령이다.

- `phase=open`: A가 B에 최초 지시를 보내며 `max_self_turns`, `total_timeout_s`를 한 번만 고정
- `phase=continue`: B가 필요한 다음 작업을 자기 탭에 보낸다. 성공한 B->B만 횟수를 소비
- `phase=close`: 최종 B->A 반환 뒤 종료 표시만 남긴다. 메시지를 보내지 않는다.

연속 상태는 `ACTIVE`, `BUDGET_EXHAUSTED`, `EXPIRED`, `UNKNOWN`, `CLOSED` 중 하나다.
전송 효과가 UNKNOWN이면 해당 연속은 UNKNOWN으로 봉인하고 자동 재전송하지 않는다.
최종 B->A 반환은 여전히 기존 `send-to-tab` 또는 Delivery return의 책임이다.

## 전달 방식과 Manager 대체 규칙

`send-to-tab`은 A->B, B->A, B->B 모두에 쓸 수 있는 **한 번의 정확한 탭 전송**이다.
호출자는 현재 관찰한 `session_id`, `tab_id`, `window_id`, `conversation_key`를 함께
제시한다. 이 명령은 대기열·대체 노드 선택·새 노드 생성을 하지 않는다. 정확한 대상이
바뀌거나 전송 효과가 UNKNOWN이면 재전송하지 않는다.

대체가 필요한 지속 작업은 Manager Wake의 `FOLLOW_UP` successor로 만든다. successor에는
대상과 완료 기준 외에 선택적으로 아래 `routing`을 넣는다.

```json
{
  "affinity": "REQUIRED | PREFERRED | ANY",
  "fallbacks": [{"node_id": "standby-1", "attachment_id": "att-1", "attachment_generation": 1}],
  "allow_provision": false
}
```

- `REQUIRED`: 지정 노드만 처리한다. 해당 노드가 바쁘면 `required_node_hold_seconds`까지
  보류하고, 만료 뒤에는 다른 노드로 보내지 않고 Manager에 상향한다.
- `PREFERRED` / `ANY`: 아직 브라우저에 제출되지 않은 경우에만
  `worker_reroute_wait_seconds` 뒤 idle fallback으로 변경할 수 있다.
- `allow_provision=true`: 자동으로 탭/노드를 만들지 않는다. `PROVISION_REQUIRED`를 남겨
  Manager가 기존 담당·예비 노드 재확인 또는 새 노드 생성을 판단하게 한다.

이 라우팅은 제출 전의 용량 결정일 뿐이다. 이미 APPLIED 또는 UNKNOWN인 delivery에는
대체본을 보내지 않는다. Manager 결과는 내구성 wake 대기열에 누적되고, 한 wake를 소비해
결정을 커밋한 뒤에만 successor outbox가 만들어진다. Manager가 장시간 멈췄을 때의 후임은
새 epoch로 영구 승계하며, 기존 Manager가 나중에 돌아와도 권한을 되돌려 주지 않는다.
대기 한도는 운영 정책의 `manager_failover_seconds`로 조정한다.
