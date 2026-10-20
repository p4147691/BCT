# RCC Rebuild V1 — 7단계 대화망 기반 (source-only)

상태: `SOURCE_FOUNDATION_COMPLETED / LIVE_NOT_CHANGED`

## 목적

고정된 Manager/Worker 두 역할을 권한 계층으로 확대하지 않는다. 프로젝트 안의 모든 ChatGPT
대화창을 동등한 노드로 보고, 사용자와 AI가 알아보기 위한 표시 이름·역할 태그·관측 상태와
전달 건의 사실 기록을 분리한다.

역할 태그는 `구현`, `CI`, `병합`, `배포`, `조정` 등 사용자가 언제든 추가·삭제하는 안내
문자열이다. 태그는 권한, 차단, 자동 배정 또는 승격을 만들지 않는다. 명시적으로 지정한
대화창은 태그와 관계없이 계속 유효한 대상이다.

## 이번 source-only 추가

- `network/directory.js`
  - project → conversation node 목록의 순수 계약
  - 표시 이름, 중복 제거된 역할 태그, 활성/보류/제외 안내 상태, 마지막 관측 사실
  - 한 방향 전달 건의 원문 스냅샷, 반환 건 parent link, 상태 전이 계약
- `relay/envelope.js`
  - A→B 전달 말미의 반환 안내문과 B→A 반환 말미의 후속 판단 안내문
  - 원문과 안내문을 분리해 저장하며, 실제 전송 문구는 두 내용을 합친 스냅샷
  - 기본 문구는 v1이며 이후 Manager가 작업별로 교체할 수 있다. BCT가 몰래 바꾸지 않는다.
- `test_conversation_network_v7.js`
  - 태그의 중복 제거, 대화창 중복 거부, 방향별 안내문, 원문 보존, 상태 전이를 검증

## 최소 왕복 모델

```text
A → B: 전달서 원문 + “처리 결과 전문은 A로 반환됩니다.”
B → A: 처리 결과 원문 + “검토 후 다음 전달서 또는 완료를 정리하세요.”
```

Worker는 후속 담당자가 필요하다고 제안할 수 있다. 다음 전달, 새 대화창 추가, 완료의 선택은
기본적으로 Manager가 한다. 이후 자동화를 추가하더라도 BCT가 임의 자연어를 실행하지 않고,
Manager가 작성한 명시적 단발 요청만 별도의 실행 계약으로 처리한다.

## 안전 경계

- 이 단계는 source와 pure background contracts만 바꾼다.
- installed extension, extension reload, Native Host, Chrome 탭, storage, 기존 binding,
  실제 ChatGPT 메시지는 변경하지 않는다.
- `UNKNOWN`은 성공으로 바꾸거나 자동 재시도하지 않는다.
- legacy 탭/창 생성·이동·닫기 기능을 제거하거나 복구하지 않는다. 필요한 대화 관리 기능은
  Browser Adapter 분리 단계에서 이 대화망 계약을 소비하도록 별도 이식한다.

## 검증

```text
node modules/rcc/extension/test_conversation_network_v7.js
node modules/rcc/extension/test_architecture_boundaries_v35.js
node modules/rcc/extension/test_rcc_core_v1.js
node modules/rcc/extension/test_simple_relay_v0.js
node --check modules/rcc/extension/network/directory.js
node --check modules/rcc/extension/relay/envelope.js
git diff --check
```

## 다음 단계

이 계약을 실제 BCT durable record와 RCC Browser Adapter에 연결하기 전, 다음을 별도 설계·검토한다.

1. 프로젝트별 목록의 저장·조회 화면과 `마지막 확인` 관측 갱신 주체
2. 방향별 안내문을 실제 single relay에 붙이는 exact payload/receipt 변경
3. 명시적 단발 후속 요청의 문법·소비 영수증·중복 방지
4. 탭 생성·이동·닫기를 대화 관리 Adapter로 분리해 재도입하는 기준
