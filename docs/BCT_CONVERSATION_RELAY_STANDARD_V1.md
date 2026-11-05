# BCT 대화망·영속 릴레이 표준 V1 — 기능 정본 카탈로그

기준 시각: 2026-10-23 (Asia/Seoul).
범위: BCT의 대화망을 이용한 Manager / Worker 메시지 전달. **Browser Bridge는 별도의 로컬 컴퓨터 연결 프로젝트**이며 영속 대화 제품 자체가 아니다.
상태: **표준 설계안 및 정리 기준 / LIVE 전체 왕복 미수락**. 이 문서의 작성이나 소스 정리만으로 운영 배포 또는 브라우저 전송이 이루어지지 않는다.

## 1. 불변 원칙

- **브라우저 API 우선**: Google Chrome 공식 tabs.sendMessage / scripting API로 동일 확장의 탭 수신기에 전달. 기존 RCC Service Worker, Content Script, runtime.connectNative Native Host를 재사용한다. API 자체는 Google이 제공하고 API를 사용하는 RCC 구현은 우리의 코드다.
- **대화망은 사용 가능한 노드 명단**: BWM에서 드래그하여 그룹에 넣거나 빼는 것은 conversation_network_memberships의 ACTIVE/EXCLUDED 변경을 뜻한다. N 번호는 안정적인 표시 식별자; 내부 식별은 conversation UUID. Manager/Worker 역할 태그는 LLM에게 알려주는 *권고 정보*이지 실행 권한이 아니다.
- **노드가 업무 판단**: Manager가 현재 그룹 명단 중 Worker를 골라 계획/위임/결과 판정. BCT는 최신 구성원을 설명하고 그 판단을 전송하지만 업무 자체를 임의로 만들어 결정하지 않는다.
- **실행 시점만 별도 검사**: 그룹 구성원 여부와 실시간 RCC tab/session/UUID, Work별 허용 범위는 다른 개념이다. 새 지시 직전에 현재 구성원, 연결 상태, 소유권을 검증하되 그룹 편집만으로 새 관리 절차를 요구하지 않는다. 이미 제출된 작업은 그룹 이동 때문에 재전송하거나 과거 영수증을 삭제하지 않는다.
- **고정 메시지는 행동 지침**: BCT에서 사용자 요청 + 현재 명단 + 역할별 노트 + 완료/반환 계약을 조립한다. 실제 권한/효과/응답 확인은 BCT Core와 RCC에서 검증한다. 모델 출력만으로 물리적 성공을 주장하지 않는다.
- **ONE LOGICAL DELIVERY / NO BLIND RETRY**: 메시지 ID·대상 UUID·원문 SHA·소유 Work를 묶어, 접수/제출/응답/Manager 소비 상태를 단일 장부에서 기록한다. 불명확한 제출은 UNKNOWN/NEEDS_REVIEW 보존, 새 ID로 재전송 금지. 사용자에게 내부 영수증을 반복 노출할 필요는 없다.

## 2. 현재 구현 위치 — 정본 / 설치 / 격리

| 기능 | 권위 소스 | 런타임·상태 | 표준 처리 |
|---|---|---|---|
| 대화망 구성 및 순서 | src/bct/conversation_network.py | SQLite ACTIVE/EXCLUDED 및 역할 태그 | **유지: 유일한 구성원 명단** |
| 그룹 명단 읽기 | src/bct/project_run.py | _members는 현재 ACTIVE 소속/역할/순서를 직접 읽음 | **재사용: 중복 멤버 저장소 만들지 않기** |
| 런 단위 실행 상태 | src/bct/project_run.py; src/bct/features/orchestration.py | PLANNED/READY, Work/session, exact attachment | 간편 시작 버튼 뒤에서 사용; 사용자에게 지휘권 등록을 요구하지 않음 |
| 지시문 고정 노트 | D:/BCT/runtime/config/manager-relay-note.txt 및 worker-relay-note.txt | 전송 때마다 읽음; UTF-8/UTF-16/CP949 지원 | **유지하고 모든 정식 메시지 경로에서 합성** |
| 기존 할당/Worker RESULT | src/bct/features/orchestration.py; src/bct/core/orchestration.py | RCC send + 정확한 RESULT 봉투 | 기존 영수증과 계약 유지; 신규 전송은 통합 계획에 맞춰 |
| Project Run Delivery | src/bct/features/rcc.py; src/bct/core/delivery_ledger.py | NOT_SENT→SENT_WAITING→REPLY_CAPTURED→RETURNED | **새 왕복의 공식 전달 장부 후보** |
| RCC 브라우저 게이트웨이 | modules/rcc/extension/platform/browser_gateway.js | tabs.sendMessage / content receiver 설치 및 검사 | **공식 탭 내부 전송 수단** |
| RCC Native Messaging | modules/rcc/extension/platform/native_transport.js | connectNative / 기존 Native Host; 연결 끊김 시 재연결 | **로컬 Core 연결로 유지**, 브라우저 내부 전송에 매번 경유할 필요 없음 |
| RCC 할당 실행/응답 | modules/rcc/extension/domain/orchestration_relay_service.js; content/orchestration_relay_executor.js | 정확한 바인딩, 제출 전 기록, 결과 수집 | 기존 구현 재사용, 새 물리 E2E 확인 필요 |
| RCC Delivery 실행 | modules/rcc/extension/domain/delivery_ledger_service.js | 현재 정확한 Worker/Manager UUID, 실제 사용자 턴, 반환 검증 | Orchestration 결과 관리와 단일화 검토 |
| Manager 결과/후속 결정 | src/bct/core/manager_decision.py; src/bct/features/orchestration.py | COMPLETE/FOLLOW_UP, 소유 세션 및 결과 digest 대조 | Manager가 판단, BCT가 소비·기록 |
| RCC Simple Relay V0 | modules/rcc/extension/domain/simple_relay_service.js; content/simple_relay_executor.js | 현재 활성 로더에 연결, 기존 실험 저장값 존재 | **간단한 수락시험·장애 분리 도구로만 유지** |
| RCC 레거시 차단기 | modules/rcc/extension/legacy/command_policy.js | 현재 설치본에서 실제 사용 중 | **삭제 금지: 차단 정책 자체** |
| CDP 영속 조회 | src/bct/integrations/cdp_connection.py; src/bct/features/cdp_inspect.py | PR #280 MERGED; 현행 manager는 list_pages만 허용 | 진단/보조 조회에 유지 |
| CDP 기존 탭 1회 제출 | PR #282 feat/cdp-chat-send-once-20261022 | CI PASS, OPEN, 미병합·운영 수락 미확인 | **조건부 보조 경로 후보, 지금 정식 전송으로 채택하지 않음** |
| Browser Bridge | modules/browser-bridge | 독립 로컬 명령 통로 프로젝트; PR #262/#281 분리 | 본 표준의 제품/주 전송에서 제외 |
| Desktop UI Automation 및 CfT SDK | 별도 도구 | 격리 테스트/최후 대체 수단 | 현 통합 대상 제외 |

주의: 저장된 원문/응답, 전송 시도, ACK, RESULT 소비, Manager 결정은 서로 다른 단계다. Chrome API 성공만으로 ChatGPT 응답을 확인했다고 주장할 수 없다.

## 3. 메시지 조립 계약 — BCT가 담당

현재 고정 노트는 Orchestration의 _result_envelope와 _manager_wake_envelope(schema 2)에 자동 삽입된다. **Project Run delivery-start에는 같은 노트를 공통 조합한다는 증거가 없다.** 이 누락을 우선 통합한다.

새 지시는 반드시 다음 의미 순서로 조립한다.

1. **공통 안전 지침**: 작업 범위, UNKNOWN 원문 재전송 금지, 외부 작업의 경계, 검증 없는 성공 주장 금지.
2. **대화망 명단 스냅샷**: group_id, 현재 ACTIVE 멤버의 UUID/N표시/역할 태그 및 관측 시각. 목록은 전달 직전에 BCT의 단일 명단에서 계산. 그룹에 없거나 연결이 미확인된 노드를 AI가 임의로 추가하지 못하도록 검사.
3. **역할 노트**: Manager라면 manager-relay-note.txt, Worker라면 worker-relay-note.txt. 파일은 **프로토콜 JSON을 직접 바꾸는 정책 파일이 아니라 LLM의 업무 지시**다.
4. **업무 지시 및 완료 조건**: 사용자의 목표, 위임 내용, 완료 기준. '4줄 보고'처럼 명시된 출력 형식은 이 계층에서 선택적으로 적용한다.
5. **종료·복귀 계약**: 완료 시 수신한 BCT RESULT 봉투(세션·할당·세대·nonce·SHA)를 정확히 반환, Manager는 결과를 읽어 COMPLETE 또는 FOLLOW_UP 결정. Worker 모델이 실제 BCT 도구를 갖지 않았다면 가상의 호출 성공을 쓰지 않는다.
6. **전송 ID/해시**: Work ID, delivery ID, 정확한 대화 UUID와 content fingerprint. 이 값은 구조적·권한 검증 대상이며 LLM 지시만으로 신뢰하지 않는다.

**호환성**: 기존 Orchestration RESULT JSON, Manager schema-2 결정 형식, 과거 UNKNOWN과 세션 기록을 변경하지 않는다. 새로운 조합 함수가 현재 전달 계약을 깨지 않는지 fixture 검증 후 도입한다.

## 4. 현재 확인한 통합 단절점

1. **고정 메시지 미공통화**: Orchestration 할당·Manager Wake에서만 자동 주입. Delivery Ledger 쪽 직접 start/return 경로는 별도로 조합 필요.
2. **구 Manager Wake 구명령**: BCT Orchestration의 _wake_manager는 send-wakeback을 호출하지만 실제 설치된 RCC 1.0.29 정책은 이를 LEGACY_MUTATION으로 차단. 즉시 차단 해제하지 말고 새 Delivery 반환/Manager 결과 소비 경로와 호환 비교.
3. **구 역할 바인딩 불일치**: N13/N14의 과거 BB_MGR/BB_W1 session/tab과 현재 RCC session/tab 불일치. PR #283 Work 보호를 이용해 정확한 새 지시에만 검증된 라우팅 사용.
4. **두 가지 반환 의미**: Delivery RETURNED는 Manager 사용자 턴 반환 확인; 'Manager가 읽고 다음 판단을 했는가'는 delivery-manager-status와 Manager decision 소비에서 별도 확인해야 한다.
5. **운영 LIVE 수락 미확정**: 격리 JS/Python/CI 성공은 실제 ChatGPT 전체 왕복 성공 증거가 아니다.

## 5. PR 의도와 채택 판정

| PR | 상태 | 판정 |
|---|---|---|
| #183, #185, #184 | MERGED | 역할 노트 + 인코딩 + COMPLETE ACK: 기존 기능 재사용 |
| #149, #150, #152 | MERGED | 영속 Manager 결과 소비/후속 작업: 삭제보다 통합 |
| #202, #226 | MERGED | send-to-tab 직접 전송의 과거 구현: 현행 RCC 차단 정책 우선 |
| #247 | MERGED | UNKNOWN 결과 조회 및 Work 경계: 유지 |
| #270, #271, #272, #275 | MERGED | 그룹·Project Run·Delivery·Manager 응답: 현 표준의 중요 기반 |
| #273 | OPEN | Manager 다음 지시 READ-only preview: 병합 전 기존 결정과 중복·의존 확인 |
| #280 | MERGED | CDP persistent 조회 전용: 유지 |
| #282 | OPEN / CI PASS | 한 번 submit + USER_TURN_VISIBLE까지 설계. 응답 반환·Manager 소비까지는 범위 밖. **운영 수락·즉시 병합 보류**, 보조 수단 단일 E2E 후 재평가 |
| #283 | MERGED | 다른 Work 소유권 격리: 유지. 소스 병합과 운영 Core 적용은 별개 |
| #262, #281 | OPEN | Browser Bridge의 독립 작업: 현 표준으로 섞지 않음 |

## 6. 정리·삭제 정책

1. **지금 소스에서만 제거 가능**: activeLoaderGraph/Content Script 의존 관계에 포함되지 않고, 배포된 RCC 폴더에도 없으며, 릴리스 JSON의 excludedLegacyPayload에 기재된 5개 파일. 구 ACT bridge 4개와 simple_relay_v0.js **호환성 진입점만** 제거한다. 원래 내용과 SHA는 Git History 및 modules/rcc/PROVENANCE.md에 보존.
2. **유지 필수**: legacy/command_policy.js(현행 거부 정책), domain/simple_relay_service.js, domain/simple_relay_receipts.js, content/simple_relay_executor.js(활성 연결), relay/contract.js(현행 계약), domain/delivery_ledger_service.js(정식 경로 후보), Manager Wake/RESULT/UNKNOWN 저장소(과거 영수증 및 수락시험).
3. **안전한 이후 정리**: Simple Relay V0 호출 인터페이스는 정식 왕복 LIVE 수락·저장 상태 격리·기존 receipt 조회 보존을 완료한 다음에만 비활성화/삭제 검토. 레거시 차단 코드는 모든 오래된 호출자가 제거·차단됐음을 다른 규칙으로 입증한 후에만 변경.
4. **경로 이동 금지(현 단계)**: Source / operating installed RCC / runtime configuration / isolated worktrees 분리는 정상이다. 관리가 어려운 것은 중복 역할·접근 경로이지 디렉터리 수 그 자체가 아니다. 운영 프로필·RCC reload·Core deploy·SQLite/레지스트리 변형은 현 검토 범위 밖.

## 7. 다음 구현 순서와 단계별 수락

- **A — 정본 카탈로그/무효 소스 정리**: 이 파일을 기준으로 격리 소스 변경, 릴리스 exclusion guard, RCC 관련 회귀·CI를 통과시킨다. 운영 미배포.
- **B — 명단 기반 BCT Prompt Composer**: 현재 그룹 roster에서 Manager/Worker 후보를 제시하고 업무/역할 노트/종료 봉투를 조립하는 단일 호출. 동일 정본 명단에서만 읽고, 기존 프로토콜을 유지. 그룹 변경 직후 새 위임의 현재 소속 반영을 검증.
- **C — RCC 최신 전송/반환 계약 통합**: 신규 작업에는 기존 browser_gateway + Delivery Ledger를 연결하고 Worker 제출·답변·Manager RETURNED·Manager 판단 소비를 구분. 현행 Orchestration send-wakeback이 필요한 레거시 Work는 구분해 보존.
- **D — 한 번만 LIVE 물리 E2E**: 독립 승인된 두 대화에 Manager→Worker(사용자 턴)→Worker 4줄 RESULT→Manager 반환(사용자 턴)→Manager COMPLETE/FOLLOW_UP 응답 저장을 정확한 ID/해시와 실제 ChatGPT 화면으로 증명. UNKNOWN이면 원본 조사만, 재전송하지 않음.
- **E — 기본 UX 단순화/재정리**: 그룹 이동+Manager/Worker 역할 표시만 사용자 입력으로 유지, Project Run 준비/영수증 경계는 BCT가 내부에서 처리. Simple Relay/옛 전송 코드는 최소 진단에만 노출하며 구식 API 제거는 별도 수락 후 수행.
- **F — CDP #282 독립 보조 전송 물리 시험**: 기본 RCC 통신이 불가한 경우의 진단/대체로만 승인. 임의 스크립트 도구 노출 금지, 운영 Chrome 동의 우회 금지, 응답 수집 기능이라고 과장하지 않음.

수락 보고는 사용자에게 **"지시 전달 / Worker 응답 / Manager 검토 / 후속 지시 / 미확정"**만 먼저 보여준다. 내부 영수증 ID와 해시는 필요한 경우 세부정보로 조회할 수 있도록 하며, 영수증 자체를 새로운 업무 명령이나 영구 자원 예약으로 취급하지 않는다.

## 8. 실재 경로

- 정본 Git main: D:/BCT/source (2026-10-23 검토 시작 시 f089f347fb3141484b88b7880bdf11bc918a2314)
- 운영 Core: D:/BCT/runtime (검토 시작 시 generation 192, release ed98146c327a124108781805ea3e1dde53a8160d)
- 운영 RCC 설치: D:/ChromeExtensions/RCC/extension (검토 시작 시 manifest 1.0.29)
- 사용자 편집 고정 노트: D:/BCT/runtime/config/
- 보존할 기능별 작업본: D:/BCT/worktrees/
- 별도 CDP 도구: D:/TOOLS/ChromeDevToolsMCP/
- 별도 Browser Bridge: D:/BCT/source/modules/browser-bridge/

**운영 상태와 Git 소스 상태는 반드시 구별한다.** 오래된 저장 정보와 마커를 자동으로 현재 실행 권한/전송 성공으로 간주하지 않는다.
