# RCC 재구축 7C단계 — Browser Tab Create Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`의 모든 `chrome.tabs.create` 직접 호출을 탭 생성 전용 Adapter로 분리한다.
빈 ChatGPT 대화 탭 생성과 차단된 legacy `ensure`의 특정 대화 탭 생성을 같은 안전 경계로 보내고,
탭 이동·닫기·창 생성·focus·메시지 제출은 포함하지 않는다.

## 분리한 경계

- `browser/tab_create_contract.js`: 생성 intent, payload fingerprint, 최소 영수증 계약
- `browser/tab_create_adapter.js`: 선택한 창의 존재를 먼저 확인하고 `tabs.create`를 한 번 호출한 뒤
  생성된 탭의 URL·대화 UUID·창 ID를 다시 확인
- `background.js`: endpoint identity와 기존 작업 ID ledger를 유지하고 생성 효과는 Adapter에 위임

`background.js`에는 더 이상 `chrome.tabs.create` 직접 호출이 없다. `chrome.windows.create`는 별도
창 생성 기능이므로 이번 단계에서 이동하지 않는다.

## 영수증 상태

| 상태 | 뜻 | 자동 재시도 |
| --- | --- | --- |
| `PENDING_UNBOUND` | 빈 ChatGPT 탭 생성과 정확한 탭·창 확인 완료 | 안 함 |
| `CREATED_CONFIRMED` | 지정 대화 UUID 탭 생성과 확인 완료 | 안 함 |
| `NOT_APPLIED` | 생성 호출 전에 지정 창 불일치가 확인됨 | 안 함 |
| `CREATE_UNKNOWN` | 생성 호출 이후 오류 또는 생성 탭의 정체를 증명하지 못함 | 금지 |

영수증에는 작업 ID, fingerprint, 탭·창 ID, endpoint identity, 대화 UUID와 binding 상태만 담고
탭 제목·대화 본문은 담지 않는다. 빈 탭의 기존 `PENDING_UNBOUND` 및 `creationReceipt` 모양은
후속 `send-to-created-tab` 검증과 호환되도록 유지한다.

## 안전 경계

- source만 변경한다.
- `create-chat-tab`, `ensure`의 legacy 차단 정책은 그대로 유지한다.
- 설치된 RCC payload, 확장 reload, Native Host, Chrome 탭·창, binding, storage와 실제 ChatGPT
  대화는 변경하지 않는다.
- LIVE 배포와 실제 탭 생성 수락 시험은 별도 허용 전까지 하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_tab_create_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node --check modules/rcc/extension/browser/tab_create_contract.js
node --check modules/rcc/extension/browser/tab_create_adapter.js
python -m unittest tests.test_rcc_source_baseline -v
RCC extension test_*.js 전체
git diff --check
```

## 다음 단위

탭 닫기 또는 창 생성 중 하나만 선택해 독립 Adapter·영수증 계약으로 분리한다. 이번 탭 생성
Adapter에 다른 Browser effect를 추가하지 않는다.
