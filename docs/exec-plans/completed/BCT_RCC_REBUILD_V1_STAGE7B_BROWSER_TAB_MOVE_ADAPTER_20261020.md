# RCC 재구축 7B단계 — Browser Tab Move Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`에 직접 섞여 있던 `chrome.tabs.move` 실행을 탭 이동 전용 Adapter로
분리하고, 이동의 결과를 추측이 아닌 영수증 상태로 반환한다. 탭 생성·닫기·focus·재로드·메시지
제출은 이 Adapter의 책임이 아니다.

## 분리한 경계

- `browser/tab_move_contract.js`: Chrome API에 의존하지 않는 이동 intent·fingerprint·영수증 계약
- `browser/tab_move_adapter.js`: 정확한 탭/대화/원래 창을 다시 확인한 뒤 `tabs.move` 한 번만 실행
- `background.js`: endpoint·대화 대상을 해석하고 기존 작업 ID 중복 방지 ledger를 유지하되,
  실제 이동과 사후 확인은 Adapter에 위임

`background.js`에는 더 이상 `chrome.tabs.move` 직접 호출이 없으며 구조 테스트가 이 경계를
고정한다.

## 영수증 상태

| 상태 | 뜻 | 자동 재시도 |
| --- | --- | --- |
| `MOVED` | 이동 후 같은 탭·대화가 목표 창에서 다시 확인됨 | 안 함 |
| `NOT_APPLIED` | 이동 호출 전에 대상/창/index 불일치가 확인됨 | 안 함 |
| `MOVE_UNKNOWN` | 이동 호출 이후 오류 또는 사후 상태를 증명하지 못함 | 금지 |

영수증에는 작업 ID, payload fingerprint, 탭 ID, 원래/목표 창, 요청 index, 이동 전후의 최소
증거만 기록한다. 제목·URL·대화 본문은 영수증에 넣지 않는다. 동일 작업 ID의 결과는 기존
RCC operation ledger가 재사용하므로 `MOVE_UNKNOWN`을 자동 재실행하지 않는다.

## 안전 경계

- source만 변경한다.
- legacy `move-tab` 차단 정책은 그대로 유지한다.
- 설치된 RCC payload, same-ID 확장, Native Host, Chrome 탭, binding, storage, 실제 ChatGPT
  대화에는 손대지 않는다.
- 새 Adapter가 source에 선택되더라도 현재 LIVE에는 배포·reload하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_tab_move_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node --check modules/rcc/extension/browser/tab_move_contract.js
node --check modules/rcc/extension/browser/tab_move_adapter.js
python -m unittest tests.test_rcc_source_baseline -v
RCC extension test_*.js 전체
git diff --check
```

## 다음 단위

LIVE 전환은 별도 허용과 수락 시험 전까지 하지 않는다. 다음 effectful Browser 기능은 탭 생성
또는 탭 닫기 가운데 하나만 골라, 이번과 같은 독립 Adapter·영수증·UNKNOWN 재시도 금지 규칙으로
분리한다.
