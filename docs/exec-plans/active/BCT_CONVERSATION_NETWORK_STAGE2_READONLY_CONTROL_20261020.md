# BCT 대화망 — 2단계 BCT Control 읽기 조회 (source-only)

상태: `SOURCE_COMPLETED / LIVE_NOT_CHANGED`

## 제공 기능

BCT Control MCP에 `bct_conversation_network_get(project="표시 이름")`를 추가했다.

이 도구는 등록된 프로젝트 하나의 다음 표시 정보를 읽기만 한다.

- 프로젝트 표시 이름과 활성 상태
- 노드 표시 이름, 안내용 역할 태그, 활동 상태
- Monitor가 마지막으로 관측한 원문 표기(예: `D1-3`), title, presence, 대조 상태
- Monitor에만 관측되어 프로젝트에 자동 추가되지 않은 노드

사용자는 프로젝트의 표시 이름을 쓰면 되고, 내부 project ID도 지원하되 기억할 필요는 없다.
같은 표시 이름이 둘 이상이면 임의 선택하지 않고 `INVALID_REQUEST`로 멈춘다.

UUID, tab/window/session ID, snapshot ID는 결과에 노출하지 않는다. 대화 route identity는 계속
내부의 UUID로만 유지하며, Monitor 표기는 사람이 보는 원문 표기다.

## 안전 경계

- 호출은 work·operation receipt를 만들지 않는 read-only 조회다.
- Monitor 호출·polling, RCC/Native Host/Chrome extension, 탭, binding, storage, relay 전달은
  전혀 수행하지 않는다.
- 실사용 BCT runtime 배포·재시작·확장 reload는 하지 않았다.

## 검증

`tests.test_mcp_integration`에서 임시 runtime에 프로젝트, 대화, Monitor snapshot을 넣고 실제
MCP 연결로 다음을 검증했다.

1. 새 도구가 catalogue와 capabilities에 노출된다.
2. 표시 이름 `BCT RCC`로 조회한다.
3. `D1-3` 표기가 그대로 반환된다.
4. conversation UUID와 snapshot ID는 반환되지 않는다.

추가로 `tests.test_conversation_network` 및 `tests.test_rcc_source_baseline`을 통과했다.

## 다음 단계

실사용 runtime에 배포하고 BCT Control을 재시작하려면 별도 허용이 필요하다. 배포 뒤에도
이 도구는 기존 durable 데이터만 읽는다. Monitor snapshot을 실제로 입력·갱신하는 연결은
별도 단계다.
