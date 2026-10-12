# DesktopWindow Monitor — Agent Entry

Monitor 작업을 시작한 노드는 코드를 검색하기 전에 아래 순서로 읽는다.

1. `MONITOR_STRUCTURE.md` — runtime/authority/경로
2. `MONITOR_ORGANIZATION_MODEL.md` — 조직 edge/authority/변경 불변식
3. `MONITOR_JS_MAP.md` — `monitor.js` 책임 지도
4. `MONITOR_MODULE_BOUNDARIES.md` — 분리 완료/후보/보류 경계
5. `MONITOR_JS_INDEX.md` — 현재 함수/라인 인덱스

핵심 규칙:
- live node / role / task / organization truth는 ACT가 소유한다.
- physical HWND / desktop / geometry는 Windows Native truth다.
- Monitor는 관제 UI와 trigger/projection이며 별도 authority를 만들지 않는다.
- **합의된 C-Node는 하나의 `conversation_key`가 가진 맥락과 정보다.** 브라우저 탭은 그 대화를 보고 조작하는 body attachment이며, 같은 대화를 여러 탭에서 열어도 작업/맥락을 중복시키지 않는다. 실제 명령은 `conversation_key`와 현재 endpoint (`transport_instance_id + session_id + tab_id`)를 함께 검증한다.
- 현재 deployed ACT/Monitor 저장·번호 projection은 아직 `tab_id + conversation_key` legacy key를 사용한다. 이를 개념적 C-Node identity로 오해하거나 storage key를 즉시 바꾸지 않는다. 같은 대화의 여러 탭, 탭 닫기/재열기, 탭 내 채팅 교체, 복구·승인, handoff의 focused compatibility test와 migration plan 없이 key를 바꾸거나 기존 번호·역할·작업 연결을 bulk migrate하지 않는다.
- `D:\AI_TOOLS\DesktopWindow-Monitor`를 현재 runtime source로 사용하지 않는다.
- active Native binary는 version 이름이 아니라 Native Messaging manifest `path`로 확인한다.
- 같은 physical target에 동시 writer를 두지 않는다.
- active extension 폴더에 임시 patch, `.bak`, 수동 사본을 만들지 않는다.
- 큰 `monitor.js`는 크기만 보고 분할하지 않는다. 책임·입출력·검증 경계가 독립된 경우에만 분리한다.
- 동작 변경 전 현재 hash와 호출 경로를 확인하고, 변경 후 가장 싼 검증부터 실행한다.
- 구조 변경 전후에는 `..\tools\check_monitor_structure.py`를 실행해 정본 경계와 load graph를 확인한다.
- 조직/연결 변경 전후에는 `..\tools\check_monitor_organization_model.py`를 실행해 default edge, override, detach, move, manager 교체, cycle, ACT save payload를 확인한다.
- 실행 중 ACT와 Monitor의 실제 연결 상태는 `..\tools\check_monitor_live_organization.py`로 **읽기 전용** 확인한다. static/source 검증과 live daemon 검증을 섞지 않는다.
- `.reload-token/.reload-ack`은 deployment protocol marker다. auto-reload 지원 runtime은 새 token을 `monitor-reload-extension`으로 연결하지만, legacy/bootstrap runtime은 ACK만 할 수 있으므로 **ACK 단독을 실제 reload 증거로 보지 않는다.**
- 코드 변경 뒤 외부 reload/deployment는 `..\tools\Request-MonitorDeploymentCheck.ps1`만 사용한다. `.reload-token`을 직접 쓰지 않는다. 이 canonical gate는 token 변경 전에 `check_monitor_structure.py`를 실행하고, active load graph의 모든 JavaScript를 `node --check`로 파싱 검증한다. 하나라도 실패하면 **token을 건드리지 않고 fail-closed** 한다.
- 사용자 개입 경고(`NEW_CHAT_REQUIRED` / `RETRY_REQUIRED` / `RECOVERY_REQUIRED`)는 **두 개의 UI surface**를 함께 가진다: (1) ChatGPT 노드 목록의 `.monitor-work-state`, (2) 창/데스크톱 섬네일의 `.monitor-window-pause-overlay`. 경고 로직 변경은 두 surface가 같은 `userAttention` 의미·색·해제 조건을 공유하는지 모두 검증해야 완료로 본다.
- **개별 닫힌 대화 복구**는 같은 탭의 챗 변경 승인과 다른 기능이다. 사용자가 복구를 누르면 닫힌 `conversation_key`를 새 Chrome 탭으로 다시 열어 기존 C-Node에 body attachment를 추가한다. 현재 legacy projection에는 새 `tab_id + conversation_key` 관측이 생기지만, 역할·조직 연결·바인딩을 복사하거나 자동 승인하지 않는다. 이미 열린 정확한 대화는 중복으로 열지 않는다.

`monitor.js`를 변경했다면 `MONITOR_JS_INDEX.md`를 재생성한다.

`MONITOR_JS_INDEX.md`의 source hash가 현재 `monitor.js` hash와 다르면 index가 오래된 것이다.
그 경우 runtime root의 `tools\build_monitor_js_index.py`로 다시 생성한다.
