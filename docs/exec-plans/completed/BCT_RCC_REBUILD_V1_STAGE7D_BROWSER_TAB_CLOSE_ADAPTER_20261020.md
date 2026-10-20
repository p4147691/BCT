# RCC 재구축 7D단계 — Browser Tab Close Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`의 `chrome.tabs.remove` 직접 호출을 탭 닫기 전용 Adapter로 분리한다.
닫기 전에 탭 ID·창 ID(제공된 경우)·ChatGPT URL·대화 UUID를 대조하고, 닫기 뒤 탭 부재를
증명한 경우에만 성공 영수증을 만든다. 탭 생성·이동·창 생성·focus·재로드·메시지 제출은
포함하지 않는다.

## 분리한 경계

- `browser/tab_close_contract.js`: 닫기 intent, fingerprint, 최소 영수증 계약
- `browser/tab_close_adapter.js`: 정확한 대상 사전 대조, `tabs.remove` 단일 호출, 사후 부재 확인
- `background.js`: 기존 native 명령 모양과 작업 ID ledger를 유지하고 닫기 효과만 Adapter에 위임

영수증에는 작업 ID, endpoint identity, 탭·창 ID, 대화 UUID와 전후 최소 증거만 기록한다.
탭 제목·URL·대화 본문은 기록하지 않는다.

## 영수증 상태

| 상태 | 뜻 | 자동 재시도 |
| --- | --- | --- |
| `CLOSED_CONFIRMED` | 정확한 대상을 닫은 뒤 탭 부재 확인 완료 | 안 함 |
| `NOT_APPLIED` | 닫기 호출 전에 탭 부재 또는 대상 불일치 확인 | 안 함 |
| `CLOSE_UNKNOWN` | 닫기 호출 뒤 오류 또는 탭 부재를 증명하지 못함 | 금지 |

`tabs.remove`를 호출한 뒤에는 오류가 나도 `NOT_APPLIED`로 되돌리지 않는다. 같은 작업 ID 재호출은
기존 idempotency ledger의 저장 결과만 반환하며 Adapter 자체는 자동 재시도하지 않는다.

## 안전 경계

- source만 변경한다.
- `close-conversation-tab` legacy 차단 정책은 그대로 유지한다.
- 설치된 RCC payload, 확장 reload, Native Host, Chrome 탭·창, binding, storage와 실제 ChatGPT
  대화는 변경하지 않는다.
- LIVE 배포와 실제 탭 닫기 수락 시험은 별도 허용 전까지 하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_tab_close_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node --check modules/rcc/extension/browser/tab_close_contract.js
node --check modules/rcc/extension/browser/tab_close_adapter.js
python -m unittest tests.test_rcc_source_baseline -v
RCC extension test_*.js 전체
git diff --check
```

## 다음 단위

창 생성 또는 정확한 탭 대상 content message 중 하나만 선택해 별도 Adapter·영수증 계약으로
분리한다. 이번 탭 닫기 Adapter에 다른 Browser effect를 추가하지 않는다.
