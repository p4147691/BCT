# RCC Rebuild V1 — 이해 가능한 대화 제어 구조

상태: `PLANNED_BEFORE_LEGACY_EXECUTION_RETIREMENT`

## 사용자에게 보이는 모델

RCC는 Chrome 안의 ChatGPT 대화를 찾고 읽고 전송하는 제품이다. Manager·Worker는 RCC
Core 자체가 아니라 Relay 모듈의 방향 이름이다. 사용자는 내부 tab/window/session ID를
알거나 전달할 필요가 없다.

```
Relay binding
  Manager 대화 UUID ── Worker 대화 UUID
       │
       ▼
RCC Core: UUID로 열린 탭 발견 → 상태 읽기 → 원문 제출 → 메시지 읽기
       │
       ▼
Relay: Manager→Worker / Worker→Manager / 최소 영수증
```

## 고정 설치 정체성 — 변경 금지

다음은 재구축 과정에서 바꾸지 않는다.

- Chrome extension ID `ocbidbaplechjjdacmokhnfbdmgjkphf`
- installed path `D:\ChromeExtensions\RCC\extension`
- Native Messaging host name `com.ai_workspace_relay.host`
- Native Host registry registration, manifest path 및 executable path
- Chrome profile/extension storage, 기존 ChatGPT conversation UUID 및 열린 탭

새 extension ID, 두 번째 unpacked extension, 다른 Chrome profile, 다른 Native Host 이름이나
등록 경로를 만들지 않는다. source 변경은 항상 기존 installed path의 exact-file backup,
payload hash match, same-ID reload, Native Host state 및 등록된 대화 UUID 확인을 거친다.

## 상태와 Relay binding 계약

`simpleRelayV0Binding`이 Relay의 유일한 영속 binding이다. 저장하는 값은 아래뿐이다.

```json
{
  "schemaVersion": 1,
  "managerConversationId": "UUID",
  "workerConversationId": "UUID"
}
```

- conversation UUID는 논리 주소다. 사용자가 대화를 교체할 때 해당 UUID 하나만 바꾼다.
- Manager/Worker는 사람 이름이 아니라 Relay 기능 안의 방향 이름이다.
- ChatGPT 대화 제목은 Chrome에서 그때그때 읽어 상태에 표시할 수 있지만, binding·권한·경로로 저장하지 않는다.
- tab/window/session ID는 매 요청에서 UUID로 발견하는 관측값이며 binding에 저장하지 않는다.
- UUID가 열린 탭에서 사라지면 `MISSING`, 중복이면 `AMBIGUOUS`, 생성 중이면 `BUSY`를
  명시한다. 조용한 재바인딩·다른 탭 전송·자동 대체는 금지한다.

## 모듈 경계

| 모듈 | 책임 | 금지된 책임 |
| --- | --- | --- |
| `rcc-core/identity` | URL→conversation UUID, exact tab resolution | 역할·노드 판단 |
| `rcc-core/conversation` | 상태 관측, composer 제출, 메시지 읽기 | 전달 규칙·재시도 |
| `rcc-relay/binding` | Manager/Worker 대화 UUID의 관계와 상태 표시 | tab/window/session/사람 이름 저장 |
| `rcc-relay/delivery` | 원문 단방향 전달·반환·최소 영수증 | 요약·의미 판단·자동 작업 분배 |
| `rcc-optional/*` | 제목 변경, 기록 조회, 창 조작, 측정 | Core/Relay 상태 변경 |
| `rcc-legacy-readonly` | 과거 receipt 조회 | 새 메시지 전송·새 역할 등록 |

## 전환 단계

1. **관측 계약**: Relay binding과 `CONNECTED / MISSING / AMBIGUOUS / BUSY` 상태를 read-only로
   노출한다. 새 binding schema는 기존 V0 binding에서 무손실 승격한다.
2. **Core 추출**: UUID resolve, 상태, 제출, 메시지 읽기를 작은 파일과 독립 테스트로
   분리한다. 기존 5,000줄 worker는 이 시점에는 여전히 실행되지만 새 전송에는 사용하지
   않는다.
3. **Relay 전환**: 현재 Simple Relay V0를 새 Core API만 사용하도록 바꾸고 Manager↔Worker
   single-delivery/return acceptance를 반복한다.
4. **Legacy 차단**: legacy send/register/create/queue/orchestration native commands를 새
   ingress에서 차단한다. 기존 receipt/result inspection만 read-only로 남긴다.
5. **Legacy 제거**: live state에 pending/UNKNOWN legacy effect가 없고 read-only export가
   검증된 뒤에만 이전 실행 코드를 source와 installed payload에서 제거한다.

## 매 단계의 경로 보호 gate

각 단계는 아래 모두 PASS 전에는 다음 단계나 새 기능으로 진행하지 않는다.

1. source main clean HEAD와 installed payload hash가 정확히 일치
2. extension ID·installed path·Native Host registration이 이전 snapshot과 일치
3. same-ID reload 뒤 Native Host `state`가 `ok`이고 build ID가 예상값과 일치
4. Relay binding의 두 UUID가 각각 정확히 하나의 열린 ChatGPT 대화로 resolve
5. 한 번의 원문 전달 또는 read-only 상태 확인으로 acceptance. 실패·UNKNOWN은 자동 재시도 금지
6. 실패 시 직전 exact-file backup으로 복원하고, 재로드 후 1~4를 다시 확인

## 현재 결론

현재 extension 1.0.23의 Simple Relay V0는 전환 단계 3의 임시 기반이다. 이를 최종 Core라고
부르지 않는다. 다음 구현은 새 binding schema와 read-only route status이며, 그 뒤에야 legacy
execution 경로를 교체한다.
