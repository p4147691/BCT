# RCC 재구축 7E단계 — Browser Window Create Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`의 `chrome.windows.create` 직접 호출을 창 생성 전용 Adapter로 분리한다.
빈 ChatGPT 대화가 들어 있는 일반 창 하나를 생성하고, 생성 후 정확한 창 ID·탭 ID·빈 대화 URL을
확인한 경우에만 성공 영수증을 만든다. 탭 생성·이동·닫기·재로드·focus 변경·메시지 제출은
포함하지 않는다.

## 분리한 경계

- `browser/window_create_contract.js`: 창 생성 intent, fingerprint, 기존 bootstrap 호환 영수증 계약
- `browser/window_create_adapter.js`: `windows.create` 단일 호출과 생성 후 창·탭 정체 확인
- `background.js`: 기존 native 명령 모양과 작업 ID ledger를 유지하고 창 생성 효과만 Adapter에 위임

기존 `send-to-created-tab`이 사용하는 `PENDING_UNBOUND` 및 `creationReceipt` 필드는 유지한다.
제목·대화 본문은 기록하지 않으며 URL은 고정된 빈 ChatGPT 주소만 기록한다.

## 영수증 상태

| 상태 | 뜻 | 자동 재시도 |
| --- | --- | --- |
| `PENDING_UNBOUND` | 새 창·빈 ChatGPT 탭의 정확한 정체 확인 완료 | 안 함 |
| `CREATE_UNKNOWN` | 생성 호출 이후 오류 또는 생성 창·탭을 증명하지 못함 | 금지 |

`windows.create`를 호출한 뒤에는 오류가 나도 효과 없음으로 간주하지 않는다. 같은 작업 ID 재호출은
기존 idempotency ledger의 저장 결과만 반환하며 Adapter 자체는 자동 재시도하지 않는다.

## 안전 경계

- source만 변경한다.
- `create-chat-window` legacy 차단 정책은 그대로 유지한다.
- 설치된 RCC payload, 확장 reload, Native Host, Chrome 탭·창, binding, storage와 실제 ChatGPT
  대화는 변경하지 않는다.
- LIVE 배포와 실제 창 생성 수락 시험은 별도 허용 전까지 하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_window_create_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node --check modules/rcc/extension/browser/window_create_contract.js
node --check modules/rcc/extension/browser/window_create_adapter.js
python -m unittest tests.test_rcc_source_baseline -v
RCC extension test_*.js 전체
git diff --check
```

## 다음 단위

탭 재로드 또는 정확한 탭 대상 content message 중 하나만 선택해 별도 Adapter·영수증 계약으로
분리한다. 이번 창 생성 Adapter에 다른 Browser effect를 추가하지 않는다.
