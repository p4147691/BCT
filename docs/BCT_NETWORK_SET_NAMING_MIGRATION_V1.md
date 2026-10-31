# BCT Network Get/Set·Store 명칭 통일 및 구형 명칭 제거 계획 V1

## 원칙
- 공개 조회는 Get, 공개 변경은 Set. 구형 update/upsert/patch/assign은 정식 공개 경로에서 단계적으로 제외한다.
- JStore는 JSON 기반 저장소. DStore는 DB 저장소의 명명 규칙으로 검토하되, 기존 SQLite Core Store를 이름 때문에 새로 만들거나 DB 테이블을 바꾸지 않는다.
- BCT 기존 Store는 여러 영역의 Work·Operation·영수증·대화망을 담당하는 공통 SQLite 접근 계층이다. 특정 대화망용 ConversationNetworkDStore를 새로 만들지 않는다.
- DB 테이블, 영속 ID, 기존 영수증, node-sync 및 PR #381의 계약은 보존한다.

## 정식 경로
- bct_network_get: 대화망 및 참여 노드 조회
- bct_network_set: name-based node-info-set(소속/역할/메모/담당작업) 및 network-name-set(대화망 전체 이름 변경). 내부 operation 이름은 API 하위 동작이며 사용자 명령과 구분한다.
- Monitor 우클릭: 동일 configure_conversation_scope Core 저장 함수 재사용. Monitor가 꺼져 있어도 AI 경로는 Core에 독립적으로 접근.
- 기존 project-upsert/membership-assign/role-patch와 bct_conversation_network_update는 당분간 호환 경로로 유지하되 새로운 호출자는 사용하지 않는다.

## 제거 게이트
1. 전체 호출자/테스트/문서/자동화에서 구형 명령 사용처를 수집하고 각 호출자의 대체 경로를 명시한다.
2. Monitor·MCP·Core·노드 상태 조회·회귀 테스트를 새 경로로 이전한다. 과거 영수증 원문을 다시 쓰거나 재실행하지 않는다.
3. 별도 CI·LIVE E2E에서 새/구 경로 동등성, 권한, CAS, idempotency, 이름 충돌, 미소속, 메모/담당작업, 역할, 대화망 전체 이름 변경 검증.
4. 구형 명령 사용량이 0이고 독립된 외부 호출자와 자동화가 남지 않았다는 증거를 확보한 뒤 별도 PR에서 구형 공개 등록을 제거한다.
5. 내부 별칭·호환 분기는 모든 사용처 제거 후 별도 단계로 삭제한다. 제거가 불확실하면 HOLD, 영구 방치는 금지한다.

## Task Run 직전 게이트
- Run Check 기존 프로젝트/맥락과 현재 상태 대조 → Run Plan 버전 저장 → Network Get → 필요 시 Set → Get 재조회 → 노드/RCC/세션/Work 상태 검증 → Task Run.
- 실제 ChatGPT 탭 생성/메시지 전송은 별도 RCC 경로이며 Network Set만으로 수행하지 않는다.
- 본 문서는 마이그레이션 계획이며 제거 완료, CI 성공, LIVE 배포를 의미하지 않는다.
