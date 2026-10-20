# RCC 재구축 7A단계 — Browser Read Adapter (source-only)

상태: `SOURCE_IMPLEMENTED / LOCAL_TESTED / LIVE_NOT_CHANGED`

## 목적

RCC `background.js`에 섞여 있던 ChatGPT 탭 조회·정확한 endpoint 관측·활동 상태 probe를
`browser/read_adapter.js`로 분리한다. 이 단계는 이후 대화 관리 기능을 독립 Adapter로 이식하기
위한 첫 경계이며, legacy 실행 코드를 삭제하거나 실제 릴레이를 바꾸지 않는다.

## 추가한 경계

`RccBrowserReadAdapter`는 아래 관측 API만 제공한다.

- ChatGPT 탭 목록 조회 및 URL 판정
- 안전한 공개 탭 메타데이터 투영
- 창 bounds 읽기
- content의 `relay:activityProbe` 읽기 요청

Adapter 자체에는 `tabs.create`, `tabs.move`, `tabs.remove`, `tabs.reload`, `windows.create`,
`windows.update`가 없으며, 테스트가 이를 고정한다. 메시지 제출, 탭·창 관리, binding 저장,
Native Host 변경은 이번 단계의 범위가 아니다.

## 안전 경계

- source만 변경한다.
- 설치된 RCC payload, extension ID, Native Host, Chrome 탭, 기존 binding, storage와 실제 ChatGPT
  메시지는 변경하지 않는다.
- read adapter는 관측과 활동 상태 probe만 수행하며, effect가 있는 Browser API는 노출하지 않는다.

## 검증

```text
node modules/rcc/extension/test_browser_read_adapter_v1.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node modules/rcc/extension/test_rcc_core_v1.js
node modules/rcc/extension/test_simple_relay_v0.js
node --check modules/rcc/extension/browser/read_adapter.js
node --check modules/rcc/extension/background.js
git diff --check
```

## 다음 단위

각 effectful Browser 기능(정확한 탭 대상 content message, 탭 생성·이동·닫기)은 별도 Adapter와
receipt 계약으로 하나씩 분리한다. 어떤 기능도 이 read-only Adapter에 추가하지 않는다.
