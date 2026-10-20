# RCC 재구축 7F단계 — Browser Tab Reload Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`의 `chrome.tabs.reload` 직접 호출을 탭 재로드 전용 Adapter로 분리한다.
재로드 전에 정확한 탭 ID·ChatGPT URL·대화 UUID를 대조하고, 재로드 뒤 같은 탭의 navigation 완료와
content receiver 응답을 확인한 경우에만 성공 영수증을 만든다. 탭 생성·이동·닫기, 창 생성,
확장 reload, 메시지 제출은 포함하지 않는다.

## 분리한 경계

- `browser/tab_reload_contract.js`: 탭 재로드 intent, fingerprint, 최소 영수증 계약
- `browser/tab_reload_adapter.js`: 정확한 대상 사전 대조, `tabs.reload` 단일 호출, navigation·receiver 확인
- `background.js`: 기존 worker reload 목록 모양을 유지하고 탭 재로드 효과만 Adapter에 위임

Adapter는 `tabs.sendMessage`를 직접 소유하지 않는다. 기존 background의 read-only `relay:probe`
콜백을 받아 사후 receiver 준비 상태만 확인한다. 제목·URL·대화 본문·probe 전문은 영수증에
기록하지 않는다.

## 영수증 상태

| 상태 | 뜻 | 자동 재시도 |
| --- | --- | --- |
| `RELOADED_CONFIRMED` | 정확한 탭 재로드, navigation 완료, receiver 응답 확인 | 안 함 |
| `NOT_APPLIED` | 재로드 호출 전에 탭 부재 또는 대화 정체 불일치 확인 | 안 함 |
| `RELOAD_UNKNOWN` | 재로드 호출 이후 오류 또는 사후 조건을 증명하지 못함 | 금지 |

`tabs.reload`를 호출한 뒤에는 오류가 나도 `NOT_APPLIED`로 되돌리지 않는다. Adapter는 효과를
한 번만 호출하고, navigation·receiver에 대한 읽기 전용 확인만 제한적으로 반복한다.

## 안전 경계

- source만 변경한다.
- `reload-workers` legacy 차단 정책과 `reload-extension` maintenance 경로는 그대로 유지한다.
- 설치된 RCC payload, 확장 reload, Native Host, Chrome 탭·창, binding, storage와 실제 ChatGPT
  대화는 변경하지 않는다.
- LIVE 배포와 실제 탭 재로드 수락 시험은 별도 허용 전까지 하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_tab_reload_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node --check modules/rcc/extension/browser/tab_reload_contract.js
node --check modules/rcc/extension/browser/tab_reload_adapter.js
python -m unittest tests.test_rcc_source_baseline -v
RCC extension test_*.js 전체
git diff --check
```

## 다음 단위

정확한 탭 대상 content message를 기능별 계약으로 분류하기 전에, `sendToChatTab` 호출군을
읽기 확인·전달·상태 갱신으로 나누는 source-only 경계를 먼저 설계한다. 이번 탭 재로드 Adapter에
content message 전송 효과를 추가하지 않는다.
