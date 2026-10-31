# BCT Network Set 공통 경로 통합 — 구현 계약 V1
2026-10-31 · 격리 설계/구현 준비, 운영 미변경

## 실제 코드 조사
- Monitor 우클릭: monitor.js -> monitor-bct-shell.js updateConversationScope -> POST /monitor/conversation-network/update -> runtime_server.run_monitor_conversation_scope_update -> conversation_network.configure_conversation_scope -> 기존 SQLite DB.
- AI: bct_network_set -> conversation_network_update capability -> ConversationNetworkUpdateFeature -> upsert_project / assign_conversation_membership / patch_conversation_role_tags -> 같은 SQLite DB.
- configure_conversation_scope에는 이미 이름 기반 기존 대화망 조회, 미존재시 UUID 기반 내부 ID 발급, 원자적 참여/미소속/이동, 역할 태그, 노드 메모/담당 작업 보존이 구현돼 있다.
- 전체 대화망 이름 변경(기존 ID 유지)은 별도 Core 변경 함수가 필요하다. 현재 project-upsert는 ID 지정 갱신은 가능하나 사용자 중심 이름변경 계약과 명확히 분리해야 한다.

## 통합 설계
1. 사용자/AI 공개 용어는 Network Get / Network Set으로 통일한다. 기존 conversation_network_update 세부 작업은 호환 진입점으로만 보존하고 별도 DB·엔진은 만들지 않는다.
2. Network Set 노드 편집은 configure_conversation_scope를 공통 Core 함수로 직접 재사용한다. Monitor의 기존 POST도 같은 함수를 유지한다. AI 호출에는 기존 Work/Operation/권한·영수증 경계를 적용한다.
3. 노드의 독립 메모/담당 작업은 conversation_network_conversations의 정본 필드로 보존한다. 역할 태그는 소속 관계의 메타데이터이며 실행 권한이 아니다.
4. 새 이름: 이름 일치시 기존 ID 참여, 없으면 원자적으로 새 ID 생성. 빈 이름: 미소속 전환(독립 기록 보존). 일부 변경: 해당 노드만 이동. 전체 이름 변경: 정확한 기존 ID와 기대 기존 이름을 확인하고 단일 트랜잭션으로 대화망 레코드의 표시 이름만 변경한다. 모든 노드의 표시 이름은 동일 ID 조인으로 반영한다.
5. 다른 대화망의 이름과 충돌하면 자동 병합 금지. 이름 정규화·대소문자 비교를 일관되게 처리한다.
6. 동시 변경은 현재 소속 ID·역할 태그 해시 및 필요시 대화망 이름 버전을 대조해 stale write를 차단한다. 기존 Monitor 호출자 호환성을 유지하되 AI 경로는 정확한 사전 상태를 요구한다.
7. 대화망 전체 이름 변경과 노드 하나의 소속 이동을 구별한다. 과거 참여 이력과 빈 대화망은 삭제하지 않는다.
8. Network Get 재조회로 결과를 검증한다. 실제 RCC·탭·세션 연결은 기존 상태 조회로 확인하고 Network Set이 브라우저를 직접 조작하지 않는다.

## 필수 회귀
- Monitor 우클릭/AI 동등 결과; 기존 이름 참여; 새 이름 자동 생성; 빈 이름 미소속; 일부 노드 이동; 전체 이름 변경(동일 ID·모든 노드 표시); 이름 충돌; 동시 수정 충돌; 노드 메모·담당 작업·역할 보존; 과거 기록 보존; 중복 호출 영수증; 권한 부족; Monitor 비실행.
- 운영 DB·Chrome/RCC·Monitor LIVE는 검증 전 변경하지 않는다. 기존 PR #381 및 node-sync 보존.
- 이 문서는 구현 완료 또는 CI PASS를 뜻하지 않는다.
