# BCT Chrome N번호 파비콘 이벤트 계약 V1 — 격리 통합 후보

기반: PR #352 / `a3bd848baed3bf50828b80b6648a8c47f81c0e4c` (19/19 PASS).
이번 별도 브랜치에서 PR #352 사용자 스크립트 자체는 수정하지 않는다.

## 도메인과 이벤트 생산 시점

영구 N번호 정본은 SQLite `conversation_network_node_labels`이다. 다음 **세 경로의 신규 INSERT**만 `NODE_LABEL_ASSIGNED` 이벤트와 `node_label_notification_outbox` PENDING 행을 **동일 트랜잭션**에 기록한다.

1. `upsert_conversation` — 처음 발견된 정확한 UUID에 번호 할당.
2. `ensure_observed_node_labels` — 기존 RCC 관측 UUID의 미할당 번호 할당.
3. `configure_conversation_scope` — 아직 등록되지 않은 대화에 번호 할당.

재조회·대화명 갱신·역할 변경·대화망 이동은 **새 N번호 이벤트가 아니다**. 영구 번호의 삭제·재할당 API는 기존 Core에 없고 이번 개발에서 임의 추가하지 않는다. Chrome 탭 OFFLINE은 번호 해제와 다르며, 기본 파비콘 복원은 기존 사용자의 SPA·페이지 수명 및 탭 매칭으로 처리한다.

DB COMMIT 실패 시 이벤트도 롤백한다. COMMIT 성공 뒤에만 `Store.emit_node_label_notification`이 기존 서버 내부 이벤트 큐를 깨운다. 네트워크 전송을 HTTP `/monitor/state` 요청 스레드에서 실행하지 않는다.

## 권한·전달·ACK

`NodeLabelNotifier`는 신규 상주 폴러가 아니라 큐에서 변경 이벤트만 기다리는 단일 워커다. 내부 BCT Work `bct-node-label-notifications`, Principal `bct-core-node-label-notifier`, capability `relay_browser`를 고정한다. 작업 영역·Work 정합화에 실패하면 서버가 fail closed 한다.

1. PENDING 이벤트의 event_id + conversation_uuid와 실제 DB의 영구 번호가 여전히 일치하는지 확인.
2. 인증된 기존 `NamedPipeRelayClient.request(command=state)`로 실제 RCC instance/session/endpoint를 읽는다.
3. 정확한 UUID에 대해 OPEN 탭이 **딱 하나**일 때만 tabId, windowId, sessionId를 고정한다. 다른 Chrome이나 같은 UUID 중복 탭으로 대체하지 않는다.
4. PENDING→STARTED를 원자적으로 점유하고 event_id·tabId에서 결정된 고유 BCT Operation ID로 `relay_browser(command=node-label-notify)` 실행. 이 시점부터 실패가 불분명하면 UNKNOWN으로 보존하고 재실행하지 않는다.
5. RCC Legacy Command Policy는 `node-label-notify`만 NODE_LABEL_NOTIFY 명령으로 허용한다. Native Host는 기존 세션·SID 검증 Named Pipe와 `host:command`을 재사용한다.
6. RCC Background는 instanceId/sessionId, Chrome tabId/windowId/URL/UUID, 중복 탭 여부를 실제 API로 재검증한다. 번호나 페이지 텍스트는 **전달하지 않는다**.
7. 기존 `browserGateway.sendWithReceiver` → `relay:nodeLabelNotify` content handler. RCC extension senderId·현재 대화 UUID 검증 뒤 정확히 하나의 `bct:conversation-roster-changed` 이벤트를 DOM에 발생시킨다.
8. 기존 PR #352 사용자 스크립트는 서버 `/monitor/state`에서 정확한 번호를 다시 확인하여 파비콘만 갱신한다. `document.title`, ChatGPT 본문, RCC 전송 메시지에는 영향이 없다.
9. Content ACK·전후 탭 동일성·RCC host result·Core BCT Operation 결과가 확인되면 outbox ACKED. 단순 호출 성공/DOM 이벤트 조작만으로 Core 성공 판단 금지. 실패/연결 유실 UNKNOWN 보존.

## 재연결·중복·무폴링

재시작 시 PENDING만 1회 재평가한다. 이미 STARTED/UNKNOWN인 외부 효과는 새 Operation ID로 재시도하지 않는다. 기존 Monitor의 `/monitor/state` 관측 시 기존 RCC instance·session·tab·UUID 토폴로지가 실제 변했을 때만 PENDING을 다시 큐에 등록한다. 동일 토폴로지 조회·대화망 태그 변경은 이벤트를 만들지 않는다.

Core 큐(최대 2048), RCC Background/content 중복 eventId 보관(최대 1024)은 유한하다. 새 `setInterval`, CDP watcher, SSE, WebSocket, MCP 또는 node-sync 수정이 없다.

## PR #351 교차 검토

PR #351은 기존 `content/content_router.js`의 이름 변경 진단과 `release/rcc_v2_rc.json`을 수정한다. 이 후보 역시 정확한 수신 메시지·RCC 릴리스 해시 때문에 두 파일을 건드린다. **파일 경계 중복은 실제로 존재하며 병합 시 무조건 재검증해야 한다.**

이 PR을 PR #352 브랜치 기반의 별도 스택 PR로 검토한다. 감독관은 PR #351 수락 HEAD를 선행 확인한 다음 다음 파일의 이름 변경 진단 결과를 보존하면서 콘텐츠 수신 블록을 함께 통합한다. 릴리스 manifest `candidateInventory`·`aggregateSha256`·`messageMatrix`·`activeLoaderGraph`은 최종 통합 소스에서 다시 생성하고 검증한다. 기존 PR #351의 이름 변경 테스트를 빼거나 덮어쓰면 안 된다.

## 격리 검증

- `python -m unittest discover -s tests -p test_node_favicon_event_delivery.py -v`: 실제 Core 세 저장 경로, 롤백, 무변경, exact Work/Operation, UNKNOWN, UUID 중복, 연결 토폴로지 수락.
- `python -m unittest discover -s tests -p test_node_favicon_rcc_integration.py -v`: Node 기반 RCC 정확 대상 전송·content 이벤트·PR352 사용자 스크립트 체인.
- `node modules/rcc/extension/test_node_favicon_notify_v1.js`: 8가지 RCC 명령·보안 경계.
- `node modules/rcc/extension/test_node_favicon_fullchain_v1.js`: 백그라운드 이벤트→N번호 PNG→원래 로고 복원.
- `node modules/rcc/favicons/test_chatgpt_node_favicon.cjs`: PR #352 기존 19개 모의 회귀.
- `node modules/rcc/favicons/test_chatgpt_node_favicon_browser.cjs`: 격리 Chrome PNG 64x64 렌더·SPA.
- `python modules/rcc/release/verify_release_candidate.py`: 정확한 소스 명세·로더·정책·해시 검사.

이 시험은 운영 Chrome이 아니라 격리 VM/브라우저의 증거이며 실제 Chrome 탭 헤더 픽셀 검증을 대신하지 않는다.

## 감독관 배포/롤백·실사용 수락 게이트

운영 환경 변경 권한은 감독관 담당이다. 먼저 PR #352와 본 스택 PR의 HEAD·CI, PR #351의 충돌 통합을 확인한다. Core·RCC는 별도 배포 대상이다. 보호된 BCT 배포로 각각 이전 정확한 SHA/해시·manifest와 RCC 확장 설치 상태를 기록한다. 원래 Tampermonkey 스크립트 설치 상태와 구형 CDP 15/30초 감시기의 중복 writer를 확인하되 임의 프로세스 중단·재시작 금지.

독립 프로필에서 OPEN 새/기존/배경 탭, UUID 일치·불일치, 중복 UUID, SPA 전환, tab/window/session 재할당, Core/RCC 연결 끊김 및 복구, 이벤트 중복, UNKNOWN 보존, BCT Work/Operation 수락 영수증을 검증한다.

최종 운영 Chrome 화면에서 **탭 헤더 실제 N번호 픽셀**을 확인하고 제목·대화·입력·포커스·RCC 메시지 송수신과 ACK를 확인한다. 실패 시 각각 이전에 수락된 Core/RCC release를 정확한 해시로 롤백하고 새 기능만 비활성화하되 기존 로그·영수증·UNKNOWN·Claim을 보존한다. 이 격리 개발자는 main 병합·LIVE 적용·Chrome 재로드를 수행하지 않는다.
