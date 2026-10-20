# BCT 대화망 — 1단계 durable Monitor snapshot (source-only)

상태: `SOURCE_COMPLETED / LIVE_NOT_CHANGED`

## 이번에 고정한 최소 기반

BCT는 대화의 내용을 판단하거나 역할에 권한을 부여하지 않는다. 이 단계에서 BCT가 저장·조회할
사실은 아래뿐이다.

- 프로젝트와 프로젝트에 속한 ChatGPT 대화 UUID
- 사용자가 붙인 표시 이름, 안내용 역할 태그, 활동 상태
- Monitor가 읽어 준 원문 노드 표기와 UUID의 관측 시점

Monitor 표기는 예를 들어 `D1-3` 그대로 opaque 문자열로 저장한다. BCT는 이를 새 번호로
만들거나 해석·재형식화하지 않으며, 실제 대화 식별은 UUID만 사용한다.

## snapshot 입력 계약

```json
{
  "schema": "BCT_MONITOR_NODE_SNAPSHOT_V1",
  "source": "MONITOR",
  "snapshot_id": "monitor.20261020.001",
  "observed_at": "2026-10-20T03:18:00Z",
  "completeness": "COMPLETE",
  "nodes": [
    {
      "node_label": "D1-3",
      "conversation_key": "6ad5afa4-b1e0-83ee-8692-aec4bb51523e",
      "title": "오류 병목 감시 측정기",
      "presence": "OPEN"
    }
  ]
}
```

- `completeness`: `COMPLETE`, `PARTIAL`, `UNAVAILABLE`.
- `UNAVAILABLE` snapshot에는 노드가 들어갈 수 없다.
- 동일 snapshot 안에서 label 또는 UUID가 중복되면 전체를 거부한다.
- 같은 `snapshot_id`는 같은 원문일 때만 idempotent하게 수락한다. 내용이 다르면 충돌로
  거부한다.
- snapshot은 append-only다. `PARTIAL`에서 빠진 노드를 제거로 취급하지 않고,
  `UNAVAILABLE`도 마지막 확인 관측을 지우지 않는다.

## 조회 대조 상태

- `MATCHED`: 프로젝트 대화 UUID가 최신 관측에 있으며 Monitor 표기를 표시할 수 있다.
- `NETWORK_UNOBSERVED`: COMPLETE 관측에는 없지만 프로젝트 등록은 유지한다.
- `PARTIAL_UNOBSERVED`: PARTIAL 관측에서 보이지 않았다. 부재·삭제로 추정하지 않는다.
- `MONITOR_UNAVAILABLE`: 최신 시도가 Monitor 불가였다. 과거 관측은 보존한다.
- `monitor_only`: Monitor에만 보이는 대화다. 프로젝트 멤버로 자동 등록하거나 전달 대상이
  되지 않는다.

## 안전 경계

- `src/bct/conversation_network.py`와 SQLite schema만 추가했다.
- 실제 Monitor 조회, BCT Control 도구 노출, RCC/Native Host/Chrome extension, 탭, binding,
  storage, 메시지 전송은 전혀 변경하지 않았다.
- 프로젝트·대화 레코드도 실제 LIVE 값으로 등록하지 않았다. 위 UUID는 테스트 fixture다.

## 검증

```text
python -m unittest tests.test_conversation_network -v
python -m unittest tests.test_rcc_source_baseline -v
git diff --check
```

## 다음 단계

별도 source 단계에서만 BCT Control에 read-only snapshot 입력·프로젝트 조회를 연결한다.
그 뒤에도 LIVE Monitor polling이나 실제 relay 전송은 별도 변경으로 다룬다.
