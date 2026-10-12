# Monitor Organization Model

목적: 다음 노드가 Monitor의 조직 구조를 역할명이나 화면 배치로 추측하지 않고, **연결(edge)과 authority** 기준으로 이해하게 한다.

## 1. Authority

- ACT가 node identity / number / role / task / organization의 authority다.
- Monitor의 구조 화면은 ACT 조직을 편집하기 위한 projection + draft UI다.
- `chrome.storage.local`의 structure 값은 draft/override/cache이며 system-wide authority가 아니다.
- 실제 확정은 `monitorStructureSave()`이 ACT layout save를 성공한 뒤에만 성립한다.

## 2. 조직의 핵심 단위

역할 자체보다 **누가 누구에게 연결되어 있는가**가 우선이다.

기본 계층:

```text
ORCHESTRATOR
  └─ AUX (있을 때)
      └─ DESK MANAGER
          ├─ WORKER
          ├─ WORKER
          └─ WORKER
```

AUX가 없으면 DESK MANAGER는 ORCHESTRATOR에 직접 연결된다.
ORCHESTRATOR도 없으면 그 상위 edge는 만들지 않는다.

가장 중요한 규칙:
- 하나의 대화 C-Node는 조직도에서 정확히 한 번만 표시한다. C-Node의 맥락 정체성은 `conversation_key`이고, ACT `D<n>-<slot>` 번호와 `tab_id + conversation_key`는 현재 legacy projection/attachment 판정에만 쓴다. 같은 conversation key가 여러 탭에 열렸다면 하나의 카드에 attachment 위치를 표시하며, 역할·작업·맥락을 중복 투영하지 않는다. 저장 key 변경과 기존 번호의 이전은 별도 migration scope다.
- HWND는 노드 동일성이 아니다. 하나의 Chrome 창과 HWND에 여러 대화 탭/노드가 함께 존재할 수 있고, 특히 창 최소화 시에도 각 노드를 별도로 유지해야 한다.
- 대화 키가 교체되는 순간 이전·현재 관측이 함께 들어와도 같은 실제 노드를 manager와 worker에 중복 투영하지 않는다.
- Desk에 manager가 있으면 그 Desk의 worker들은 처음부터 **각자 manager를 parent로 갖는다.**
- “manager가 Desk 전체를 암묵적으로 관리한다”는 별도 규칙을 두지 않는다.
- 관리 관계는 전부 explicit parent edge로 표현한다.
- 따라서 열외/분리는 특수한 node type이 아니라 **edge를 끊는 것**으로 표현한다.

### 같은 Desk 안의 기본 형태와 예외

화면에서 worker가 여러 줄이나 여러 열로 배치되어 보여도 시각적 인접 관계로 상하관계를 추론하지 않는다. 별도 편집이 없다면 같은 Desk의 일반 worker는 모두 그 Desk manager의 직속 노드다.

```text
M
├─ W1
├─ W2
├─ W3
├─ W4
└─ W5
```

W4와 W5가 화면 오른쪽에서 위아래로 놓여 있다는 이유만으로 `W4 → W5` 관계가 생기지 않는다. 사용자가 두 노드 사이에 명시적 지휘선을 만들었을 때만 기본 manager 연결을 대체하여 다음과 같이 해석한다.

```text
M
├─ W1
├─ W2
├─ W3
└─ W4
   └─ W5
```

즉 기본 구조는 manager 아래의 평평한 직속 목록이고, worker 간 계층은 explicit reparent override다. 역할 색은 노드의 행동 역할만 나타내며 parent 결정이나 실행 권한을 만들지 않는다.

화면 배치는 선을 읽고 편집하기 위한 표현 계층이다. 연결선이 다른 노드를 가로지르지 않도록 worker를 여러 행이나 계단 형태로 배치할 수 있지만, 배치 좌표만으로 edge를 만들지 않는다. 조직도 렌더러는 저장된 parent edge를 먼저 읽고 그 선을 명확하게 그릴 수 있는 위치를 계산해야 한다.

조직도 카드의 시각 언어도 역할과 제어를 섞지 않는다. `O`, `C1`, `C2`, `M`은 역할 위치 표기이고 실제 노드 번호는 동일한 크기의 카드 안에 표시한다. 카드 전체 클릭은 그 노드의 AUTO 상태만 전환하며, 별도 분할 버튼을 만들지 않는다. AUTO 활성화는 카드 전체의 밝기/광택으로 표현한다.

Local/External LLM은 조직도에서 각각 `L-LLM`, `E-LLM`으로 표기하고 일반 노드와 같은 크기의 카드로 렌더한다. 가용성은 별도 `READY`/`OFFLINE` 문자를 반복하지 않고 카드나 행의 명도로 표현한다. 밝은 흰색은 사용 가능, 흐린 회색은 오프라인/미확인을 뜻하며 상세 상태는 접근성 이름과 tooltip에 남긴다.

## 3. Default + Override

현재 구조 계산은 두 층으로 본다.

1. `monitorStructureDefaultParents(layout)`
   - 현재 layout으로부터 기본 parent map을 만든다.
2. `monitorStructureLinkOverrides`
   - 사용자가 바꾼 연결만 덮어쓴다.
3. `monitorStructureEffectiveParents(layout)`
   - default + override를 합친 최종 parent map이다.

override 의미:
- `child -> "parentKey"`: parent 변경
- `child -> null`: 기본 연결도 끊어서 detached
- override 없음: default 연결 사용

이 방식은 모든 node를 기본 구조에 자동 편입시킨 뒤, 사용자가 선만 끊거나 바꾸는 모델이다.

## 4. Edge와 다른 상태를 섞지 않는다

다음은 서로 다른 개념이다.

- `MANAGES` edge: node ↔ node 조직 연결
- desk membership: 어느 Desk에 속하는가
- role assignment: MANAGER / WORKER / ORCHESTRATOR / AUX
- resource edge: supervisor가 Local/External/Codex resource를 사용하는 연결
- physical desktop/HWND: 실제 Windows 위치

Desk membership이나 화면 위치를 보고 관리 edge를 추론하지 않는다.
반대로 관리 edge 변경이 곧 physical window move를 뜻하지도 않는다.

## 5. 저장 payload

ACT로 보낼 조직 저장 payload는 다음 의미를 가진다.

- `assignments`: node별 workplace/role/slot
- `workplaces`: D1, D2 ... Desk 목록
- `edges`: effective parent map을 `{parent_key, child_key, relation:"MANAGES"}`로 변환한 것
- `detached_children`: override가 명시적으로 null인 node
- `resource_edges`: 별도의 resource 사용 연결
- `expected_generation`: stale save 방지
- `actor: "USER_MONITOR"`

저장 순서상 실제 Desk 이동이 먼저 일어날 수 있으므로 ACT save 실패 시 physical move rollback 규칙을 유지한다.

## 6. Cycle / self-link 방지

`monitorStructureSetParent(child,parent)`는:
- child == parent 금지
- `monitorStructureWouldCycle()`로 cycle 금지
- 변경 직후에는 local draft만 바꾸고 ACT에는 즉시 쓰지 않음
- 사용자가 실행/저장을 눌러야 ACT에 반영

## 7. Resource 연결

Local LLM / External LLM / Codex 같은 resource는 node parent tree와 별도다.
`monitorStructureResourceEdges`를 사용하며 supervisor key ↔ resource id 관계를 저장한다.

resource를 node처럼 parent tree 안에 넣지 않는다.

## 8. 2026-09-21 Phase A 적용 상태

`monitorStructureDefaultParents(layout)`에 Desk worker -> Desk manager 기본 edge 규칙을 적용했다.

```text
for each desk:
  if manager exists:
    for each worker in desk:
      if worker != manager:
        defaultParents[worker] = manager
```

검증 결과:
- 새/기존 Desk worker는 explicit override가 없으면 manager를 parent로 갖는다.
- `child -> 다른 parent` override는 default를 대체한다.
- `child -> null` override는 default도 끊고 `detached_children`으로 직렬화된다.
- 기존 ORCHESTRATOR/AUX/MANAGER command-layer parent 계산은 유지된다.
- `monitorStructureBuildSavePayload()`가 worker-manager 관계를 `relation:"MANAGES"` edge로 ACT payload에 포함한다.
- `resource_edges`, `expected_generation`, `actor:"USER_MONITOR"` 의미는 유지된다.
- Node syntax / function index / structure checker가 통과했다.
- `tools\check_monitor_organization_model.py`가 새 node 자동 연결, Desk 이동, manager 교체, explicit reparent/detach, cycle 방지, ACT save payload, UI edge projection을 반복 검증한다.
- `tools\check_monitor_live_organization.py`는 `18765`의 health/hierarchy/resources/ai-nodes/workspaces를 **GET만 사용해** 확인하고, source가 맞아도 live daemon이 오래된 경우를 별도로 잡는다.
- `monitorStructureDrawLinks(layout)`는 `monitorStructureEffectiveParents(layout)` 전체를 그리므로 worker-manager 기본 edge도 별도 렌더 경로 없이 즉시 선으로 표시된다.
- manager socket 변경과 Desk 이동은 기존 `renderMonitorStructure()`를 호출하므로 draft topology가 즉시 다시 계산·표시된다.

새 저장 스키마는 추가하지 않았다. 기본 연결은 layout에서 결정론적으로 계산하고 예외만 기존 `linkOverrides`에 저장한다.

## 9. Authority round-trip 정규화

ACT의 GET /organization/hierarchy는 최종 MANAGES edge를 돌려준다. 여기에는 기본 edge와 사용자 override가 함께 들어 있으므로, 응답의 모든 edge를 그대로 monitorStructureLinkOverrides로 복사하면 기본 연결까지 explicit override로 굳어지는 문제가 생긴다.

정본 규칙:
1. monitorStructureAuthorityOverrides(data, layout)가 현재 monitorStructureDefaultParents(layout)을 계산한다.
2. ACT edge가 현재 default와 같으면 local override로 저장하지 않는다.
3. default와 다른 edge만 explicit reparent override로 남긴다.
4. detached_children은 항상 child -> null explicit override로 남긴다.
5. 따라서 ACT 저장 -> 다시 읽기 후에도 manager 교체/Desk 이동 시 기본 worker는 새 default parent를 따라가고, 사용자가 명시적으로 바꾼 연결만 고정된다.

초기화에서도 ACT 조회 성공 후에는 조회 전 chrome.storage.local의 오래된 links/node-controls를 다시 덮어쓰지 않는다. local structure 값은 ACT 조회 실패 시 fallback으로만 사용하고, MONITOR_STRUCTURE_TEMP_DRAFT_KEY가 있을 때만 사용자의 미저장 draft를 의도적으로 overlay한다.

UI projection도 같은 의미를 직접 드러낸다.
- 상태줄의 선=실제 관리 연결은 화면의 선이 monitorStructureEffectiveParents(layout) 결과임을 뜻한다.
- Desk의 `M` 표시는 manager 역할 위치다. override가 없는 Desk node가 그 manager를 기본 parent로 갖는 관계는 화면 문구가 아니라 effective parent edge로 표현한다.
- Desk wrapper는 중복된 button/group role 재지정 없이 최종 role=group 하나만 유지한다.

## 10. 변경 시 지켜야 할 불변식

- node identity/number는 조직 edge 변경으로 바뀌지 않는다.
- worker의 기본 parent는 같은 Desk의 manager다.
- D2+에 node가 하나라도 있으면 초기 projection이 첫 node를 M slot에 배치하며, 이 선택은 같은 Desk worker의 기본 parent 계산에도 사용한다. 빈 Desk에는 가짜 manager를 만들지 않는다.
- detach는 node 삭제가 아니라 `override child=null`이다.
- reparent는 node 복제가 아니라 `override child=parent`다.
- default 구조를 바꿔도 사용자가 저장한 explicit override가 항상 우선한다.
- resource edge와 MANAGES edge를 합치지 않는다.
- ACT save 성공 전 local draft를 authoritative라고 부르지 않는다.

## 11. ACT transport / backend contract

조직 UI의 backend 정본은 `D:\ACT\runtime\agent-orchestrator`다. 실행 entry는 `orchestrator.py`, HTTP route 구현은 `src\agent_orchestrator\server.py`다. 과거 `D:\AI_TOOLS\AGENT-ORCHESTRATOR` 사본을 현재 runtime authority로 사용하지 않는다.

Monitor는 localhost port를 직접 고정하지 않고 `monitor-act-transport.js`가 노출하는 `actFetch("act:/...")` 경계만 사용한다. transport가 Agent Orchestrator `/health`를 확인해 현재 ACT endpoint를 결정한다.

조직 contract의 핵심 route는 다음과 같다.
- `GET /organization/hierarchy`: 저장된 MANAGES edge / detach / generation을 읽는 authority 경로. Structure refresh의 필수 read다.
- `POST /organization/layout-save`: assignments + workplaces + effective MANAGES edges + detached children + resource edges를 `expected_generation`과 함께 한 번에 commit하는 정식 전체 저장 경로다.
- `GET /organization/resources`: resource edge와 LLM resource projection.
- `GET /organization/ai-nodes`: AI workforce node projection.
- `GET /organization/workspaces`: workspace projection.
- `GET|POST /organization/node-control`: node auto-control 상태의 전용 경로.
- `GET /metrics/executors`: Structure 화면의 executor telemetry 보조 정보.
- `POST /organization/hierarchy`: hierarchy-only 저장 호환 경로. 전체 조직 저장의 기본 경로로 새 코드에서 우회 사용하지 않는다.

2026-09-21 기준 위 route는 현재 ACT runtime source에 연결했고 offline HTTP smoke 후 supervisor가 관리하는 ACT child만 재기동하여 live GET route를 검증했다. ACT supervisor `ops\run_orchestrator.ps1` 자체는 유지하고 child만 교체한다.

backend 장애 시 local draft나 화면 배치를 새 authority로 승격하지 않는다. hierarchy authority read가 실패하면 원인을 ACT/runtime contract에서 고치고, 저장 성공 응답을 받은 뒤에만 ACT 저장 상태로 간주한다.

## 12. Desk 내부 조직도 projection

- O/C/M은 전역 장식 행이 아니라 실제 소속 Desk 사각형 안에 표시한다. 역할과 물리 Desk 소속은 서로 다른 축이며 save assignment에 둘 다 보존한다.
- D1은 O/C1/C2의 고정 command slot을 가진 최상단 Desk다. 실제 역할 노드가 아직 없어도 세 slot과 D1 자체는 남는다. manager를 선출하지 않는다.
- D2부터는 실제 Desk membership만 투영한다. 명시된 MANAGER가 있을 때만 M 카드를 보이며, 일반 worker를 보기 좋게 하려고 M으로 승격하지 않는다. 노드와 자원이 모두 없으면 header와 이동용 `+`만 보이는 빈 Desk로 남는다.
- 기본 자원방은 존재하는 여섯 번째 Desk(D6)다. Local/External LLM 및 Google/Naver Codex의 아직 배치되지 않은 활성 resource만 D6에 기본 배치하며, D6이 아직 없을 때에는 worker Desk로 임의 배치하지 않는다.
- node/resource의 Desk 이동은 카드 교환이나 Desk 전체 drop이 아니라 해당 Desk의 명시적인 `+` slot에 놓을 때만 일어난다.
- 짧은 node 카드 클릭은 AUTO 상태를 전환한다. 드래그는 배치/연결 편집이며 click suppression으로 AUTO 토글과 충돌하지 않는다.
- Google Codex와 Naver Codex는 별도 resource card와 별도 Desk assignment를 갖는다. 예전 단일 `codex` 배치값은 두 카드의 초기 위치로 한 번 승계한다.

### 현재 UI 단계 — Desk/node composition + edge editing

- SVG 선은 `monitorStructureEffectiveParents(layout)`를 그대로 투영한다. 드래그한 node는 child, 놓는 채워진 node는 새 parent다. parent는 child별 하나이며 한 parent는 여러 child를 가질 수 있다. 기존 parent가 있으면 override가 교체되고 다른 child 관계는 유지된다.
- node를 조직도 canvas의 빈 공간에 놓으면 해당 node의 parent만 `null` override로 끊는다. 그 node가 parent로 가진 child 연결까지 함께 끊지 않는다.
- node drag 중에는 원본 크기의 ghost frame과 live line을 표시한다. 채워진 node, 빈 O/C/M socket, Desk `+`는 각각 target feedback을 표시한다. 빈 role socket drop은 역할 배치, `+` drop은 Desk 이동, 채워진 node drop은 reparent다.
- 외부 worker/thumbnail drag가 `application/x-dwm-structure-node` payload를 제공하면 동일한 빈 role socket과 Desk `+` drop 경로를 사용한다.
- D1은 유동 Desk 상자 안의 compact command rail이다. 크기 기준은 Desktop thumbnail 외곽의 1/4이 아니라 **thumbnail 안에 보이는 2×2 웹 창 한 칸**이며, 현재 projection에서는 64×40이다. `C1 - O - C2`를 거의 같은 가로선에 놓고 O만 약 7px 올린다. D1 표시는 상자 왼쪽 위에 겹치지 않게 고정하여 별도 header 행을 소비하지 않으며, Desk transfer `+`는 rail 오른쪽의 40×40 compact target이다. D1에 속한 일반 node/resource는 장래의 command 연결선을 가리지 않도록 지휘 rail 오른쪽의 분리 영역에 쌓는다. Desk 상자는 실제 내용 크기만큼 늘어난다. D2가 하나뿐이면 D1 바로 아래 중앙에 놓으며, 둘 이상일 때만 하위 row에 벌어 놓는다.
- D2+는 O/C와 마찬가지로 node 유무와 무관하게 빈 M slot을 항상 가진다. 패널 최초 열기·초기화·자동배치 때 해당 Desk에 node가 있으면 explicit manager 배치, MANAGER 역할 node, 첫 일반 node 순으로 M을 자동 채운다. M 카드와 모든 작업/resource 카드는 같은 64×40 기준을 공유하고, M은 아래 2열 grid의 정확한 중심에 둔다. D번호와 `+`는 별도 header 높이를 만들지 않고 M과 같은 첫 행의 좌우에 배치한다. 나머지 작업 node는 M 아래 2열로 배치하고 LLM/Codex resource는 작업 node 뒤의 마지막 행들에 둔다.
- LLM/Codex는 실제 Desktop window가 없으므로 자동배치/초기화 때마다 현재 존재하는 **마지막 Desk**에 모은다. D6이 존재하고 마지막 Desk라면 자연스럽게 D6이 resource room이 된다. L-LLM, E-LLM, G-CODEX 세 고정 resource slot은 연결 상태와 무관하게 모두 투영하며, 상태는 밝기와 tooltip으로 구분한다.
- M은 별도의 작은 manager 카드가 아니다. 일반 node와 완전히 같은 64×40 카드에 O/C와 같은 좌상단 역할 badge만 겹쳐 표시한다. manager socket의 바깥 테두리/배경은 실제 node가 들어오면 제거하여 이중 상자 때문에 작아 보이는 현상을 만들지 않는다.
- 상태 설명과 초기화/자동배치/실행 버튼은 node/Desk 수에 따라 움직이지 않는 패널 하단 고정 footer다. 설명은 왼쪽, 버튼은 오른쪽의 같은 기준선에 두고 조직도 canvas만 footer 위에서 스크롤한다.
- D1~D6까지는 현재 카드 크기와 한 줄 하위 Desk 배치를 그대로 유지한다. D7부터는 두 번째 줄이나 가로 스크롤을 만들지 않고, 현재 panel 가용 폭과 하위 Desk 전체의 자연 폭을 비교해 D2+ 전체에 하나의 동일 scale을 적용한다. Desk 상자, M/worker/resource 카드, 역할 badge와 `+`가 함께 비례 조정되므로 데스크별 크기 차이는 생기지 않는다.
- D번호는 Desk 내부의 독립 열이나 header 높이를 소비하지 않는다. D1과 D2+ 모두 동일하게 상자 왼쪽 위 테두리에 걸친 작은 tab으로 투영한다. 모든 command/manager/worker/resource 카드는 단일 CSS metric `64×40`을 공유하며 min/max 크기까지 함께 고정한다. D2+ Desk는 160px이고 `+`는 우상단 40×40 overlay다. D1도 번호용 왼쪽 padding을 두지 않는다.
- D1의 O/C command rail 오른쪽에 놓이는 일반 node/resource 영역은 한 열로 세로 누적하지 않는다. 동일한 64×40 metric을 사용하는 2열 grid로 채우며, command rail과 분리된 상태는 유지해 향후 연결선 공간을 침범하지 않는다.
- D1에 일반 node/resource 영역이 생겨도 O의 중심은 D1 상자 중심에서 움직이지 않는다. command rail 자체는 왼쪽 40px balance slot과 오른쪽 40px `+` slot 사이에 `C1 O C2`를 놓아 O를 정확히 중앙에 둔다. 오른쪽 2열 extra 영역이 생기면 그 실제 폭(카드 2개, gap, separator/padding)과 같은 151px balance column을 왼쪽에만 조건부로 만들고 command rail을 중앙 열에 둔다. extra 영역이 없으면 이 바깥 balance column도 만들지 않는다.
- 조직도 상태는 **실제 상태 / 작업 상태 / 기준 상태(Baseline)** 로 분리한다. 창 닫기·다시 열기·F5·확장 리로드는 작업 상태를 바꾸지 않으며, 작업 상태는 별도 working draft로 계속 복원한다. 최초 기준 상태가 없을 때만 현재 실제 Desk/node를 자동배치하여 기준 상태를 만든다. `초기화`는 자동배치를 다시 실행하는 기능이 아니라 마지막으로 확정된 기준 상태로 돌아가는 기능이다. `위치 변경 확정` 또는 전체 `실행`이 성공하면 그 시점의 현재 조직도 상태를 새 기준 상태로 승격한다. ACT authority 조회 실패는 작업 상태나 기준 상태를 폐기하는 이유가 되지 않는다.
- 모든 node/resource 카드는 같은 읽기 가능한 카드 계열을 사용한다. compact node는 Desk가 이미 제공하는 접두사(`D2-`)를 반복하지 않고 short ordinal만 표시하며, 대화 제목은 tooltip/accessibility에만 남긴다.
